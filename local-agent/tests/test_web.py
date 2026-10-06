import asyncio
import http.server
import json
import os
import sys
import threading
from pathlib import Path

import pytest

from localagent.connectors.browser import (PlaywrightBrowser, browser_tools, check_url, needs_submit,
                                           render)
from localagent.skills import load_skills, parse_skill, run_skill, sandbox_available, sandbox_profile, scaffold, skill_tools
from localagent.tools.base import ToolError
from conftest import FakeBrowser
from test_actions import chat, decide


def run(coro):
    return asyncio.run(coro)


def el(**kw):
    base = {"ref": 1, "tag": "button", "type": "", "label": "", "submits": False, "value": None,
            "search": False, "editable": False, "href": None, "password": False, "options": None}
    return {**base, **kw}


# ── browser ────────────────────────────────────────────────────────────────
def test_check_url():
    assert check_url("shop.example/item") == "https://shop.example/item"
    assert check_url("http://x.org") == "http://x.org"
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings"):
        with pytest.raises(ToolError):
            check_url(bad)


def test_needs_submit():
    assert needs_submit(el(label="Buy now"))
    assert needs_submit(el(label="Continue", submits=True))
    assert needs_submit(el(tag="input", type="submit", label="Send", submits=True))
    assert needs_submit(el(tag="input", type="button", label="Delete account"))
    assert needs_submit(el(tag="div", label="Place order"))
    assert not needs_submit(el(label="Search", submits=True))
    assert not needs_submit(el(label="Show more"))
    assert not needs_submit(el(tag="a", label="Book a demo", href="https://x.com/demo"))
    assert needs_submit(el(tag="a", label="Delete", href="javascript:void(0)"))
    assert not needs_submit(el(tag="input", type="text", label="Order number"))


def test_browser_tools_guardrails():
    b = FakeBrowser()
    tools = {t.name: t for t in browser_tools(b)}
    assert {t.name: t.tier for t in tools.values()} == {
        "browser_open": "draft", "browser_read": "read", "browser_find": "read", "browser_click": "draft",
        "browser_type": "draft", "browser_submit": "danger"}
    with pytest.raises(ToolError, match="Open a page first"):
        run(tools["browser_click"].run({"ref": 1}))
    res = run(tools["browser_open"].run({"url": "shop.example/item"}))
    assert res.untrusted and "[3] button “Buy now” [commits: use browser_submit]" in res.content
    assert "[1] search field “Search” [search box]" in res.content
    with pytest.raises(ToolError, match="browser_submit"):
        run(tools["browser_click"].run({"ref": 3}))
    with pytest.raises(ToolError, match="never types passwords"):
        run(tools["browser_type"].run({"ref": 4, "text": "hunter2"}))
    with pytest.raises(ToolError, match="no element"):
        run(tools["browser_click"].run({"ref": 99}))
    run(tools["browser_type"].run({"ref": 1, "text": "kettle", "enter": True}))
    assert b.calls[-1] == ("fill", 1, "kettle", True)
    assert "Buy now" in tools["browser_submit"].summary({"ref": 3})
    run(tools["browser_click"].run({"ref": 2}))
    assert b.url == "https://shop.example/details"
    b.la_state["snap"] = {"title": "f", "url": "u", "text": "", "elements": [
        el(tag="input", type="text", label="Name"), el(ref=2, tag="div", label="Notes", editable=True)]}
    with pytest.raises(ToolError, match="search box"):
        run(tools["browser_type"].run({"ref": 1, "text": "x", "enter": True}))
    b.url = "https://shop.example/details"
    run(tools["browser_type"].run({"ref": 2, "text": "hello"}))           # contenteditable is fine


def test_main_content_first_and_find():
    nav = [el(ref=i, tag="a", label=f"Menu {i}", href=f"https://shop.example/m{i}", priority=2)
           for i in range(1, 201)]
    main = [el(ref=201, tag="a", label="Blue Kettle", href="https://shop.example/k", priority=0),
            el(ref=202, label="Add to Cart", submits=True, priority=0),
            el(ref=203, tag="input", type="text", label="Card number", priority=0),
            el(ref=204, tag="input", type="text", label="Security code (CVV)", priority=0)]
    b = FakeBrowser()
    b.pages["https://shop.example/big"] = {"title": "Big", "url": "https://shop.example/big", "text": "x",
                                           "elements": nav + main}
    tools = {t.name: t for t in browser_tools(b)}
    res = run(tools["browser_open"].run({"url": "https://shop.example/big"}))
    listed = res.content.split("Elements (act by number):")[1]
    assert listed.lstrip().startswith("[201]") and "[202] button “Add to Cart”" in listed
    assert "[200]" not in listed and "+84 more elements" in listed
    hit = run(tools["browser_find"].run({"text": "menu 199"}))
    assert "[199] link “Menu 199”" in hit.content
    assert "Nothing found" == run(tools["browser_find"].run({"text": "checkout now"})).display
    for ref in (203, 204):
        with pytest.raises(ToolError, match="payment or ID"):
            run(tools["browser_type"].run({"ref": ref, "text": "4111111111111111"}))
    with pytest.raises(ToolError, match="browser_submit"):
        run(tools["browser_click"].run({"ref": 202}))


def test_snapshot_survives_tool_rebuild():
    b = FakeBrowser()
    run(browser_tools(b)[0].run({"url": "shop.example/item"}))
    click = {t.name: t for t in browser_tools(b)}["browser_click"]
    run(click.run({"ref": 2}))
    assert b.url.endswith("/details")


def test_web_chat_flow_with_approval_for_submit(web_client):
    c = web_client
    ev = chat(c, "open the website for the blue kettle")
    res = next(e for e in ev if e["type"] == "tool_result")
    assert res["tool"] == "browser_open" and res["ok"]
    assert "⚠" in res["display"]                                     # injection text on the page
    ev = chat(c, "click the details link")
    assert next(e for e in ev if e["type"] == "tool_result")["tool"] == "browser_click"
    c.browser.url = "https://shop.example/item"
    chat(c, "open the website again")
    ev = chat(c, "book it now")
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]
    assert ap["tool"] == "browser_submit" and ap["tier"] == "danger" and "Buy now" in ap["summary"]
    assert ("click", 3) not in c.browser.calls
    assert [s["id"] for s in ap["allowed_scopes"]] == ["once"]
    r, ev = decide(c, ap["id"])
    assert r.status_code == 200 and ("click", 3) in c.browser.calls
    assert c.get("/api/connectors").status_code == 200


@pytest.mark.skipif(not PlaywrightBrowser.installed() or not Path(
    os.environ.get("LOCALAGENT_TEST_CHROMIUM", "/opt/pw-browsers/chromium")).exists(),
    reason="needs Playwright and a Chromium binary")
def test_real_playwright_browser(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    nav = "".join(f'<a href="/m{i}.html">Menu {i}</a> ' for i in range(150))
    (site / "index.html").write_text("""<html><head><title>Shop</title></head><body>
      <nav>""" + nav + """</nav><a href="/m0.html">Menu 0</a><main>
      <h1>Blue Kettle</h1><p>Price $39</p>
      <form role="search" action="/results.html"><input name="q" placeholder="Search"><button>Search</button></form>
      <a href="/details.html">Details</a>
      <form action="/thanks.html"><input name="email" type="email" placeholder="Email">
        <input type="password" name="pw"><button>Buy now</button></form>
      <div role="button" style="display:none">Hidden</div></main></body></html>""")
    (site / "details.html").write_text("<title>Details</title><p>1.7 litres</p>")
    (site / "results.html").write_text("<title>Results</title><p>3 kettles</p>")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(site), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    async def go():
        b = PlaywrightBrowser(tmp_path / "profile", headless=True,
                              executable=os.environ.get("LOCALAGENT_TEST_CHROMIUM", "/opt/pw-browsers/chromium"))
        tools = {t.name: t for t in browser_tools(b)}
        try:
            res = await tools["browser_open"].run({"url": url})
            snap = b.la_state["snap"]
            labels = {e["label"]: e for e in snap["elements"]}
            assert "Blue Kettle" in res.content and "Hidden" not in labels
            assert labels["Buy now"]["submits"] and needs_submit(labels["Buy now"])
            assert sum(1 for e in snap["elements"] if e["label"] == "Menu 0") == 1     # duplicate link dropped
            listed = res.content.split("Elements (act by number):")[1]
            assert "“Buy now”" in listed and "more elements not listed" in listed   # main first, nav capped
            assert labels["Buy now"]["priority"] == 0 and labels["Menu 3"]["priority"] == 2
            assert not needs_submit(labels["Search"])
            q = next(e for e in snap["elements"] if e["tag"] == "input" and e["search"])
            pw = next(e for e in snap["elements"] if e["password"])
            with pytest.raises(ToolError):
                await tools["browser_type"].run({"ref": pw["ref"], "text": "x"})
            email = next(e for e in snap["elements"] if e["type"] == "email")
            await tools["browser_type"].run({"ref": email["ref"], "text": "me@example.com"})
            assert any(e.get("value") == "me@example.com" for e in b.la_state["snap"]["elements"])
            res = await tools["browser_type"].run({"ref": q["ref"], "text": "kettle", "enter": True})
            assert "Results" in res.content
            await tools["browser_open"].run({"url": url})
            details = next(e for e in b.la_state["snap"]["elements"] if e["label"] == "Details")
            res = await tools["browser_click"].run({"ref": details["ref"]})
            assert "1.7 litres" in res.content
        finally:
            await b.close()
            httpd.shutdown()

    asyncio.run(go())


# ── skills ─────────────────────────────────────────────────────────────────
def test_parse_and_validate_skills(tmp_path):
    root = tmp_path / "skills"
    folder = scaffold(root, "word-count")
    sk = parse_skill(folder)
    assert (sk.name, sk.tier, sk.network, sk.args, sk.run) == ("word-count", "read", False, ["text"], "python3 main.py")
    assert sk.tool_name == "skill_word_count" and not sk.problems
    bad = root / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: Bad Name\ntier: root\n---\n")
    net = root / "fetch"
    net.mkdir()
    (net / "SKILL.md").write_text("---\nname: fetch\ndescription: Fetch a page\nrun: python3 x.py\n"
                                  "tier: read\nnetwork: true\n---\n")
    guide = root / "packing"
    guide.mkdir()
    (guide / "SKILL.md").write_text("---\nname: packing\ndescription: How I pack for trips\n---\n1. Passport\n")
    skills = {s.name: s for s in load_skills(root)}
    assert len(skills["bad name"].problems) >= 3
    assert skills["fetch"].tier == "write"                      # network forces approval
    tools = {t.name: t for t in skill_tools(root, require_sandbox=False)}
    assert set(tools) == {"skill_word_count", "skill_fetch", "skill_packing"}
    assert tools["skill_packing"].tier == "read"
    assert run(tools["skill_packing"].run({})).content == "1. Passport"
    with pytest.raises(FileExistsError):
        scaffold(root, "word-count")
    with pytest.raises(ValueError):
        scaffold(root, "../evil")


def test_run_skill_and_errors(tmp_path):
    folder = scaffold(tmp_path, "word-count")
    sk = parse_skill(folder)
    (folder / "main.py").write_text((folder / "main.py").read_text().replace("python3", ""))
    sk.run = f"{sys.executable} main.py"
    res = run(run_skill(sk, {"text": "one two three"}, require_sandbox=False))
    assert res.content == "3 words, 1 lines, 13 characters" and not res.untrusted
    (folder / "slow.py").write_text("import time; time.sleep(5)")
    sk.run, sk.timeout = f"{sys.executable} slow.py", 1
    with pytest.raises(ToolError, match="longer than 1s"):
        run(run_skill(sk, {}, require_sandbox=False))
    (folder / "fail.py").write_text("import sys; sys.exit('boom')")
    sk.run, sk.timeout = f"{sys.executable} fail.py", 10
    with pytest.raises(ToolError, match="boom"):
        run(run_skill(sk, {}, require_sandbox=False))
    if not sandbox_available():
        with pytest.raises(ToolError, match="sandbox"):
            run(run_skill(sk, {}, require_sandbox=True))


def test_sandbox_profile(tmp_path):
    home = tmp_path / "home"
    sk = parse_skill(scaffold(home / ".local/share/LocalAIAgent/skills", "word-count"))
    venv = home / ".local/pipx/venvs/localaiagent"
    venv.mkdir(parents=True)
    prof = sandbox_profile(sk, home, [venv, Path("/opt/homebrew")])
    lines = prof.splitlines()
    assert "(deny network*)" in prof and "(deny file-write*)" in prof
    assert f'(subpath "{(sk.folder / "work").resolve()}")' in prof
    deny_home = lines.index(f'(deny file-read* (subpath "{home.resolve()}"))')        # the whole home folder
    for allowed in (sk.folder.resolve(), venv.resolve()):                                # … then only these back
        assert lines.index(f'(allow file-read* (subpath "{allowed}"))') > deny_home
    assert "/opt/homebrew" not in prof                                                   # outside home: not needed
    assert "com.apple.coreservices.appleevents" in prof and '(literal "/usr/bin/osascript")' in prof
    sk.network = True
    assert "(deny network*)" not in sandbox_profile(sk, home)


def test_skill_used_in_chat_and_listed(web_client):
    c = web_client
    folder = scaffold(c.home / "skills", "word-count")
    (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text().replace(
        "run: python3 main.py", f"run: {sys.executable} main.py"))
    conns = {x["id"]: x for x in c.get("/api/connectors").json()}       # reloads skills
    assert [t["name"] for t in conns["skills"]["tools"]] == ["skill_word_count"]
    ev = chat(c, "make a word count of: hello big world")
    res = next(e for e in ev if e["type"] == "tool_result")
    assert res["tool"] == "skill_word_count" and res["ok"], res
    info = c.get("/api/skills").json()
    assert info["skills"][0]["name"] == "word-count" and info["folder"].endswith("skills")


def test_skill_cli(home, monkeypatch):
    from typer.testing import CliRunner

    from localagent.cli import app

    r = CliRunner().invoke(app, ["skill", "list"])
    assert "No skills yet" in r.output
    r = CliRunner().invoke(app, ["skill", "new", "word-count"])
    assert r.exit_code == 0 and (home / "skills" / "word-count" / "SKILL.md").exists()
    r = CliRunner().invoke(app, ["skill", "list"])
    assert "word-count" in r.output and "read" in r.output
    assert CliRunner().invoke(app, ["skill", "new", "Bad Name"]).exit_code == 1


@pytest.mark.skipif(not sys.platform.startswith("linux") or not __import__("shutil").which("bwrap"),
                    reason="needs Linux with bubblewrap")
def test_linux_bwrap_sandbox_really_confines(monkeypatch):
    import shutil as _sh
    import tempfile

    # Not under /tmp: the sandbox gives skills a private /tmp, which would make this test trivial.
    home = Path(tempfile.mkdtemp(dir="/var/tmp", prefix="la-sbx-")) / "home"
    request_cleanup = lambda: _sh.rmtree(home.parent, ignore_errors=True)  # noqa: E731
    data = home / ".local/share/LocalAIAgent"
    (data / "skills").mkdir(parents=True)
    (data / "secrets.json").write_text('{"gmail_refresh_token": "SECRET"}')
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY")
    monkeypatch.setenv("HOME", str(home))
    folder = scaffold(data / "skills", "probe")
    (folder / "main.py").write_text("""
import json, os, socket, sys
out = {}
def tryit(name, fn):
    try:
        out[name] = fn()
    except Exception as e:
        out[name] = "blocked: " + type(e).__name__
tryit("own_file", lambda: open("SKILL.md").read()[:3])
tryit("secrets", lambda: open(os.path.expanduser("~/../.local/share/LocalAIAgent/secrets.json")).read())
tryit("secrets_abs", lambda: open(sys.argv[1]).read())
tryit("ssh", lambda: open(sys.argv[2]).read())
tryit("write_work", lambda: open(os.environ["SKILL_WORK_DIR"] + "/x.txt", "w").write("ok"))
tryit("write_home", lambda: open(sys.argv[3], "w").write("x"))
tryit("network", lambda: socket.create_connection(("1.1.1.1", 53), timeout=2) and "connected")
print(json.dumps(out))
""")
    sk = parse_skill(folder)
    sk.run = f"{sys.executable} main.py {data / 'secrets.json'} {home / '.ssh/id_ed25519'} {home / 'evil.txt'}"
    res = run(run_skill(sk, {}, require_sandbox=True))
    out = json.loads(res.content)
    assert out["own_file"] == "---"
    assert out["write_work"] == 2
    for key in ("secrets", "secrets_abs", "ssh", "write_home", "network"):
        assert str(out[key]).startswith("blocked"), (key, out[key])
    assert not (home / "evil.txt").exists()
    request_cleanup()
