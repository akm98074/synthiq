import asyncio
import base64
import http.server
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from localagent.connectors.browser import (BrowserUnavailable, ChromeProcess, PlaywrightBrowser, browser_tools,
                                           find_chrome)

CHROMIUM = os.environ.get("LOCALAGENT_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
needs_chromium = pytest.mark.skipif(not PlaywrightBrowser.installed() or not Path(CHROMIUM).exists(),
                                    reason="needs Playwright and a Chromium binary")


def script(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "fake-chrome"
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def test_find_chrome_setting(tmp_path):
    app = tmp_path / "Google Chrome.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app / "Google Chrome").write_text("")
    assert find_chrome(str(tmp_path / "Google Chrome.app")) == app / "Google Chrome"
    assert find_chrome(str(app / "Google Chrome")) == app / "Google Chrome"
    assert find_chrome(str(tmp_path / "missing")) is None


def test_chrome_that_exits_reports_why(tmp_path):
    exe = script(tmp_path, 'echo "[ERROR] bad flag --foo" >&2; exit 3')
    with pytest.raises(BrowserUnavailable, match=r"exited straight away \(code 3\).*bad flag"):
        asyncio.run(ChromeProcess(exe, tmp_path / "profile").start())


def test_chrome_that_never_opens_port_is_stopped(tmp_path):
    exe = script(tmp_path, "exec sleep 30")
    cp = ChromeProcess(exe, tmp_path / "profile")
    cp.START_TIMEOUT = 1.0
    with pytest.raises(BrowserUnavailable, match="didn't open its control port"):
        asyncio.run(cp.start())
    assert cp.proc is None


def test_stale_lock_is_cleared_live_lock_is_reported(tmp_path):
    prof = tmp_path / "profile"
    prof.mkdir()
    os.symlink("myhost-999999", prof / "SingletonLock")
    cp = ChromeProcess(script(tmp_path, "exit 3"), prof)
    with pytest.raises(BrowserUnavailable, match="code 3"):
        asyncio.run(cp.start())
    assert not os.path.lexists(prof / "SingletonLock")          # dead pid: cleaned up
    holder = subprocess.Popen(["sleep", "30"])
    try:
        os.symlink(f"myhost-{holder.pid}", prof / "SingletonLock")
        with pytest.raises(BrowserUnavailable, match=f"process {holder.pid}"):
            asyncio.run(cp.start())
    finally:
        holder.kill()


def test_missing_chrome_message(tmp_path):
    b = PlaywrightBrowser(tmp_path / "p", executable=str(tmp_path / "nope.app"))
    with pytest.raises(BrowserUnavailable, match="Google Chrome wasn't found"):
        asyncio.run(b.snapshot())


@needs_chromium
def test_real_chrome_lifecycle_overlay_and_live_view(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("""<title>Shop</title><main><h1>Kettle</h1>
      <input placeholder="Search"><a href="/next.html">Next page</a></main>""")
    (site / "next.html").write_text("<title>Next</title><main><p>Second</p></main>")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(site), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    async def go():
        b = PlaywrightBrowser(tmp_path / "profile", headless=True, executable=CHROMIUM, action_delay_ms=50,
                              agent_name="Ari")
        tools = {t.name: t for t in browser_tools(b)}
        try:
            res = await tools["browser_open"].run({"url": url})
            assert "Kettle" in res.content and b.chrome.proc is not None
            shot = base64.b64decode(res.data["shot"])
            assert shot[:2] == b"\xff\xd8" and len(shot) < 150_000               # a small JPEG
            pill = await b._page.evaluate("document.getElementById('__la_pill').textContent")
            assert pill.startswith("Ari · Opened")
            field = next(e for e in b.la_state["snap"]["elements"] if e["tag"] == "input")
            await tools["browser_type"].run({"ref": field["ref"], "text": "steel"})
            assert await b._page.evaluate("document.querySelector('input').value") == "steel"
            tag = await b._page.evaluate("document.getElementById('__la_tag').textContent")
            assert tag == "Ari: typing in “Search”"
            assert await b._page.evaluate("!!document.getElementById('__la_cursor')")
            link = next(e for e in b.la_state["snap"]["elements"] if e["label"] == "Next page")
            res = await tools["browser_click"].run({"ref": link["ref"]})
            assert "Second" in res.content
            # the user closes the agent's tab: the next step opens a fresh one in the same Chrome
            pid = b.chrome.proc.pid
            await b._page.close()
            res = await tools["browser_open"].run({"url": url})
            assert "Kettle" in res.content and b.chrome.proc.pid == pid
            # Chrome itself goes away: the next step starts it again on the same profile
            b.chrome.proc.kill()
            await b.chrome.proc.wait()
            await asyncio.sleep(0.5)
            res = await tools["browser_open"].run({"url": url})
            assert "Kettle" in res.content and b.chrome.proc.pid != pid
            proc = b.chrome.proc
        finally:
            await b.close()
            httpd.shutdown()
        assert proc.returncode is not None                                   # nothing left running

    asyncio.run(go())


@needs_chromium
def test_reuses_agents_chrome_left_from_earlier_run(tmp_path):
    async def go():
        first = ChromeProcess(Path(CHROMIUM), tmp_path / "profile", headless=True)
        await first.start()                      # e.g. the agent was restarted, Chrome kept running
        try:
            b = PlaywrightBrowser(tmp_path / "profile", headless=True, executable=CHROMIUM, show_actions=False)
            snap = await b.snapshot()
            assert snap["url"] == "about:blank" and b.chrome.proc is None     # attached, not started twice
            await b.close()                                                    # asks that Chrome to quit
            await asyncio.wait_for(first.proc.wait(), 10)
        finally:
            await first.stop()

    asyncio.run(go())
