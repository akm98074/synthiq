"""Browser worker: a dedicated Chrome/Chromium profile driven through Playwright.

The model never sees raw HTML. Each page becomes a snapshot: title, URL, readable text,
and a numbered list of the interactive elements (links, buttons, fields). The model acts
by number. Safety comes from the tools, not the model:

  browser_open / browser_read      look (page text is untrusted: fenced and scanned)
  browser_click / browser_type     navigate and fill in, never submit or buy
  browser_submit                   anything that submits, sends, pays, books or deletes:
                                   danger tier, approved every time

The profile lives in the agent's data folder, separate from your own browser, so the
agent is logged in only where you log it in yourself. Passwords are never typed by it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import plistlib
import re
import shutil
import sys
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s
from .forms import SENSITIVE

log = logging.getLogger(__name__)

MAX_TEXT = 6000
MAX_ELEMENTS = 120     # shown to the model per page; the rest are reachable with browser_find
MAX_SCAN = 1500        # tagged per page
# Submit buttons with these labels only search, filter or page; they don't need approval.
SAFE_WORDS = re.compile(r"^\s*(search|find|go|filter|apply filters?|sort|show( more)?|more|load more|next( page)?|"
                        r"previous( page)?|look ?up|🔍)\s*$", re.IGNORECASE)
# Labels that mean "this commits something". Clicking one needs browser_submit.
COMMIT_WORDS = re.compile(
    r"\b(buy|pay|purchase|order|checkout|check out|place|confirm|submit|send|post|publish|delete|remove|"
    r"cancel (my )?(subscription|order|account)|unsubscribe|subscribe|sign ?up|register|book|reserve|"
    r"transfer|donate|accept|agree|authori[sz]e|approve|apply|save changes|update payment)\b",
    re.IGNORECASE,
)

SNAPSHOT_JS = """
(maxEls) => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], '
            + '[role=checkbox], [role=tab], [role=menuitem], [contenteditable=true], summary';
  document.querySelectorAll('[data-la-ref]').forEach((el) => el.removeAttribute('data-la-ref'));
  const MAIN = 'main, [role=main], #dp, #centerCol, #ppd, #content, article';
  const CHROME = 'header, nav, footer, [role=navigation], [role=banner], [role=contentinfo]';
  const out = []; const seen = new Set(); let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= maxEls) break;
    if (!vis(el) || el.disabled) continue;
    const key = el.tagName === 'A' ? el.href + '|' + (el.innerText || '').trim() : null;
    if (key && seen.has(key)) continue;
    if (key) seen.add(key);
    n += 1; el.setAttribute('data-la-ref', String(n));
    const priority = el.closest(MAIN) ? 0 : (el.closest(CHROME) ? 2 : 1);
    const tag = el.tagName.toLowerCase(); const type = (el.getAttribute('type') || '').toLowerCase();
    const own = el.labels && el.labels[0] ? el.labels[0].innerText : '';
    const label = (el.getAttribute('aria-label') || own || el.innerText || el.getAttribute('placeholder')
      || el.getAttribute('title') || el.getAttribute('name') || el.getAttribute('alt')
      || (type === 'submit' || type === 'button' ? el.value : '') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    const form = el.closest('form');
    const submits = tag === 'input' ? (type === 'submit' || type === 'image')
      : tag === 'button' ? (!!form && (type === '' || type === 'submit')) : false;
    let value = null;
    if (tag === 'input' || tag === 'textarea') value = type === 'password' ? (el.value ? '••••' : '') : el.value;
    if (tag === 'select') value = el.options[el.selectedIndex]?.text || '';
    const search = type === 'search' || !!el.closest('[role=search]')
      || /search|query/i.test([el.getAttribute('name'), el.getAttribute('placeholder'),
                               el.getAttribute('aria-label')].join(' ')) || el.getAttribute('name') === 'q';
    out.push({ ref: n, tag, type, label, submits, value, search, editable: el.isContentEditable, priority,
               href: tag === 'a' ? el.href : null, password: type === 'password',
               options: tag === 'select' ? Array.from(el.options).slice(0, 20).map((o) => o.text) : null });
  }
  const main = document.querySelector(MAIN);
  const raw = main && main.innerText.length > 300 ? main.innerText : (document.body ? document.body.innerText : '');
  const text = raw.replace(/\\n{3,}/g, '\\n\\n');
  return { title: document.title, url: location.href, text, elements: out };
}
"""


SHOW_JS = """
(a) => {
  const el = document.querySelector('[data-la-ref="' + a.ref + '"]');
  if (!el) return false;
  el.scrollIntoView({ block: 'center', inline: 'nearest' });
  const r = el.getBoundingClientRect();
  let root = document.getElementById('__la_overlay');
  if (!root) {
    root = document.createElement('div'); root.id = '__la_overlay';
    root.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;';
    root.innerHTML = '<div id="__la_ring"></div><div id="__la_tag"></div>'
      + '<svg id="__la_cursor" width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7 19 2.5-7.5L20 11z" '
      + 'fill="#2f6f5e" stroke="#fff" stroke-width="1.5"/></svg><div id="__la_ripple"></div>';
    document.documentElement.appendChild(root);
    const st = (id, css) => { root.querySelector(id).style.cssText = css; };
    st('#__la_ring', 'position:fixed;border:3px solid #2f6f5e;border-radius:8px;box-shadow:0 0 0 4px rgba(47,111,94,.25);transition:all .35s ease;');
    st('#__la_tag', 'position:fixed;background:#2f6f5e;color:#fff;font:600 12px -apple-system,sans-serif;padding:3px 8px;border-radius:6px;white-space:nowrap;transition:all .35s ease;');
    st('#__la_cursor', 'position:fixed;left:50%;top:50%;transition:left .45s ease,top .45s ease;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4));');
    st('#__la_ripple', 'position:fixed;width:16px;height:16px;border-radius:50%;background:rgba(47,111,94,.5);opacity:0;');
  }
  const ring = root.querySelector('#__la_ring'), tag = root.querySelector('#__la_tag');
  const cur = root.querySelector('#__la_cursor'), rip = root.querySelector('#__la_ripple');
  Object.assign(ring.style, { left: (r.left - 4) + 'px', top: (r.top - 4) + 'px', width: (r.width + 8) + 'px',
                              height: (r.height + 8) + 'px', opacity: '1' });
  tag.textContent = a.text;
  Object.assign(tag.style, { left: Math.max(4, r.left - 4) + 'px', top: Math.max(4, r.top - 30) + 'px', opacity: '1' });
  const cx = r.left + Math.min(r.width / 2, 40), cy = r.top + r.height / 2;
  Object.assign(cur.style, { left: cx + 'px', top: cy + 'px' });
  if (a.ripple) setTimeout(() => {
    Object.assign(rip.style, { left: (cx - 8) + 'px', top: (cy - 8) + 'px', transition: 'none', opacity: '1', transform: 'scale(1)' });
    requestAnimationFrame(() => Object.assign(rip.style, { transition: 'all .5s ease-out', opacity: '0', transform: 'scale(3)' }));
  }, a.delay);
  setTimeout(() => { ring.style.opacity = '0'; tag.style.opacity = '0'; }, a.delay + 1500);
  return true;
}
"""

PILL_JS = """
(text) => {
  let pill = document.getElementById('__la_pill');
  if (!pill) {
    pill = document.createElement('div'); pill.id = '__la_pill';
    pill.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;pointer-events:none;'
      + 'background:rgba(29,29,27,.88);color:#fff;font:500 13px -apple-system,sans-serif;padding:7px 12px;'
      + 'border-radius:999px;box-shadow:0 2px 10px rgba(0,0,0,.3);';
    document.documentElement.appendChild(pill);
  }
  pill.textContent = text;
}
"""


class Browser(Protocol):
    async def goto(self, url: str) -> dict: ...
    async def snapshot(self) -> dict: ...
    async def click(self, ref: int, label: str = "") -> dict: ...
    async def fill(self, ref: int, text: str, enter: bool = False, label: str = "") -> dict: ...
    async def close(self) -> None: ...


class BrowserUnavailable(ToolError):
    pass


MAC_APPS = ["Google Chrome", "Google Chrome Beta", "Google Chrome Canary"]
LINUX_BINS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
WINDOWS_PATHS = [r"Google\Chrome\Application\chrome.exe", r"Google\Chrome Beta\Application\chrome.exe",
                 r"Google\Chrome SxS\Application\chrome.exe"]


def _app_binary(path: Path) -> Path:
    if path.suffix == ".app":
        return path / "Contents" / "MacOS" / path.stem
    return path


def find_chrome(setting: str = "") -> Path | None:
    """The Chrome to use: the browser_executable setting, else an installed Google Chrome."""
    if setting:
        p = _app_binary(Path(setting).expanduser())
        return p if p.exists() else None
    if sys.platform == "darwin":
        for folder in (Path("/Applications"), Path.home() / "Applications"):
            for name in MAC_APPS:
                p = folder / f"{name}.app" / "Contents" / "MacOS" / name
                if p.exists():
                    return p
        return None
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for root in filter(None, roots):
            for rel in WINDOWS_PATHS:
                p = Path(root) / rel
                if p.exists():
                    return p
        return None
    for name in LINUX_BINS:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def chrome_version(exe: Path) -> str:
    """'Google Chrome 141.0.7390.65' from the app's Info.plist (macOS), else the binary name."""
    for parent in exe.parents:
        if parent.suffix == ".app":
            try:
                info = plistlib.loads((parent / "Contents" / "Info.plist").read_bytes())
                return f"{info.get('CFBundleName', parent.stem)} {info.get('CFBundleShortVersionString', '')}".strip()
            except (OSError, plistlib.InvalidFileException):
                return parent.stem
    return exe.name


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class ChromeProcess:
    """Real Chrome started by the agent on its own profile, reachable over the DevTools protocol.

    Chrome is started like a normal app (no automation flags), with --remote-debugging-port=0;
    it writes the port it picked to <profile>/DevToolsActivePort. If a Chrome from an earlier
    run still holds the profile and answers on that port, it's reused instead of started twice.
    """

    START_TIMEOUT = 20.0

    def __init__(self, exe: Path, profile_dir: Path, headless: bool = False):
        self.exe, self.profile_dir, self.headless = exe, profile_dir, headless
        self.proc: asyncio.subprocess.Process | None = None
        self.owned = False
        self._stderr: list[str] = []

    def _port_file(self) -> Path:
        return self.profile_dir / "DevToolsActivePort"

    async def _answering(self, port: int) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as c:
                r = await c.get(f"http://127.0.0.1:{port}/json/version")
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _read_port(self) -> int | None:
        try:
            first = self._port_file().read_text().splitlines()[0].strip()
            return int(first)
        except (OSError, ValueError, IndexError):
            return None

    def _lock_pid(self) -> int | None:
        try:
            target = os.readlink(self.profile_dir / "SingletonLock")   # "<host>-<pid>"
            return int(target.rsplit("-", 1)[1])
        except (OSError, ValueError, IndexError):
            return None

    def _clear_stale_lock(self) -> None:
        pid = self._lock_pid()
        if pid is not None and _pid_alive(pid):
            return
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            try:
                (self.profile_dir / name).unlink()
            except OSError:
                pass

    async def _drain(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                return
            self._stderr = (self._stderr + [line.decode(errors="replace").rstrip()])[-15:]

    def args(self) -> list[str]:
        a = [str(self.exe), "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
             f"--user-data-dir={self.profile_dir}", "--no-first-run", "--no-default-browser-check",
             "--disable-features=ChromeWhatsNewUI", "--window-size=1280,900"]
        if self.headless:
            a.append("--headless=new")
        if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
            a.append("--no-sandbox")   # Chrome refuses to run as root otherwise (containers, CI)
        return a + ["about:blank"]

    async def start(self) -> str:
        """Start (or reuse) Chrome; returns the DevTools endpoint URL."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        port = self._read_port()
        if port and self._lock_pid() and _pid_alive(self._lock_pid()) and await self._answering(port):
            log.info("reusing the agent's Chrome already running on port %s", port)
            self.owned = True   # it's the agent's profile: closing it later is right
            return f"http://127.0.0.1:{port}"
        pid = self._lock_pid()
        if pid and _pid_alive(pid):
            raise BrowserUnavailable(
                f"Another Chrome (process {pid}) is using the agent's browser profile but isn't answering. "
                "Quit the Chrome window titled with the agent's pages (or run: kill " + str(pid) + "), then try again.")
        self._clear_stale_lock()
        try:
            self._port_file().unlink()
        except OSError:
            pass
        self._stderr = []
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.args(), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            raise BrowserUnavailable(f"Couldn't start {self.exe}: {exc}") from exc
        self.owned = True
        self._drain_task = asyncio.create_task(self._drain())
        deadline = asyncio.get_running_loop().time() + self.START_TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            if self.proc.returncode is not None:
                await asyncio.sleep(0.2)
                tail = " | ".join(self._stderr[-3:])
                raise BrowserUnavailable(
                    f"Chrome exited straight away (code {self.proc.returncode})."
                    + (f" It said: {tail[:300]}" if tail else "")
                    + (" If the agent's Chrome window is already open from an earlier run, quit it and try again."
                       if self.proc.returncode == 0 else ""))
            port = self._read_port()
            if port and await self._answering(port):
                return f"http://127.0.0.1:{port}"
            await asyncio.sleep(0.25)
        tail = " | ".join(self._stderr[-3:])
        await self.stop()
        raise BrowserUnavailable(f"Chrome started but didn't open its control port within "
                                 f"{int(self.START_TIMEOUT)} s." + (f" It said: {tail[:300]}" if tail else ""))

    async def stop(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        self.proc = None


class PlaywrightBrowser:
    """The agent's own window in real Google Chrome (own profile), attached over DevTools."""

    def __init__(self, profile_dir: Path, headless: bool = False, executable: str = "",
                 show_actions: bool = True, action_delay_ms: int = 600, agent_name: str = "Agent"):
        self.profile_dir, self.headless, self.executable = profile_dir, headless, executable
        self.show_actions, self.action_delay_ms, self.agent_name = show_actions, action_delay_ms, agent_name
        self._pw = self._browser = self._ctx = self._page = None
        self.chrome: ChromeProcess | None = None
        self.using = ""
        self._lock = asyncio.Lock()

    @staticmethod
    def installed() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    async def _page_ready(self):
        if self._page is not None and not self._page.is_closed() and (
                self._browser is None or self._browser.is_connected()):
            return self._page
        if self._ctx is not None and self._browser is not None and self._browser.is_connected():
            # The user closed the agent's tab: open a fresh one in the same window.
            self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            return self._page
        exe = find_chrome(self.executable)
        if exe is None:
            where = (f"at {self.executable}" if self.executable
                     else "in /Applications or ~/Applications" if sys.platform == "darwin" else "on this computer")
            raise BrowserUnavailable(f"Google Chrome wasn't found {where}. Install it from google.com/chrome "
                                     "(or set browser_executable in Settings), then try again.")
        if not self.installed():
            raise BrowserUnavailable("The browser add-on isn't installed. In Terminal run: "
                                     "pipx inject localaiagent playwright")
        from playwright.async_api import Error as PWError, async_playwright

        await self._disconnect()
        if self._pw is None:
            self._pw = await async_playwright().start()
        self.chrome = ChromeProcess(exe, self.profile_dir, self.headless)
        endpoint = await self.chrome.start()
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(endpoint, timeout=15000)
        except PWError as exc:
            log.warning("connect_over_cdp failed: %s", exc)
            await self.chrome.stop()
            raise BrowserUnavailable(f"Chrome started but the agent couldn't connect to it: "
                                     f"{str(exc).splitlines()[0][:200]}") from exc
        self._ctx = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        self.using = f"{chrome_version(exe)} at {exe}"
        log.info("browser ready: %s", self.using)
        return self._page

    async def _settle(self, page) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:  # noqa: BLE001 - busy pages never go idle; the snapshot is still useful
            pass

    async def _show(self, page, ref: int, text: str, ripple: bool = False) -> None:
        """Muse-style: cursor glides to the element, ring + label, optional click ripple."""
        if not self.show_actions:
            return
        try:
            await page.bring_to_front()
            await page.evaluate(SHOW_JS, {"ref": int(ref), "text": f"{self.agent_name}: {text}",
                                          "ripple": ripple, "delay": self.action_delay_ms})
            await page.evaluate(PILL_JS, f"{self.agent_name} · {text}")
            await asyncio.sleep(self.action_delay_ms / 1000)
        except Exception:  # noqa: BLE001 - the overlay is cosmetic; never block the action
            pass

    async def _pill(self, page, text: str) -> None:
        if self.show_actions:
            try:
                await page.evaluate(PILL_JS, f"{self.agent_name} · {text}")
            except Exception:  # noqa: BLE001
                pass

    async def _shot(self, page) -> str | None:
        """A small JPEG of what's on screen (for the chat's live view)."""
        try:
            w, h, x, y = await page.evaluate("[innerWidth, innerHeight, scrollX, scrollY]")
            cdp = await page.context.new_cdp_session(page)
            try:
                r = await cdp.send("Page.captureScreenshot", {
                    "format": "jpeg", "quality": 50,
                    "clip": {"x": x, "y": y, "width": w, "height": h, "scale": min(1.0, 640 / max(w, 1))}})
            finally:
                await cdp.detach()
            return r.get("data")
        except Exception:  # noqa: BLE001 - a missing thumbnail must never fail the step
            return None

    async def _after(self, page) -> dict:
        snap = await page.evaluate(SNAPSHOT_JS, MAX_SCAN)
        snap["shot"] = await self._shot(page)
        return snap

    async def snapshot(self) -> dict:
        page = await self._page_ready()
        return await self._after(page)

    async def goto(self, url: str) -> dict:
        async with self._lock:
            page = await self._page_ready()
            if self.show_actions:
                await page.bring_to_front()
            await page.goto(url, timeout=30000)
            await self._settle(page)
            await self._pill(page, f"Opened {await page.title() or url}")
            return await self._after(page)

    async def click(self, ref: int, label: str = "") -> dict:
        async with self._lock:
            page = await self._page_ready()
            await self._show(page, ref, f"clicking “{label}”" if label else "clicking", ripple=True)
            await page.locator(f'[data-la-ref="{int(ref)}"]').first.click(timeout=10000)
            await self._settle(page)
            return await self._after(page)

    async def fill(self, ref: int, text: str, enter: bool = False, label: str = "") -> dict:
        async with self._lock:
            page = await self._page_ready()
            loc = page.locator(f'[data-la-ref="{int(ref)}"]').first
            await self._show(page, ref, f"typing in “{label}”" if label else "typing")
            if await loc.evaluate("el => el.tagName.toLowerCase()") == "select":
                await loc.select_option(label=text, timeout=10000)
            else:
                if self.show_actions and len(text) <= 80:
                    await loc.fill("", timeout=10000)
                    await loc.press_sequentially(text, delay=40, timeout=20000)
                else:
                    await loc.fill(text, timeout=10000)
                if enter:
                    await loc.press("Enter")
                    await self._settle(page)
            return await self._after(page)

    async def _disconnect(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()      # for a CDP connection this only disconnects
            except Exception:  # noqa: BLE001
                pass
        self._browser = self._ctx = self._page = None

    async def close(self, keep_open: bool = False) -> None:
        if self._browser is not None and not keep_open and self.chrome is not None and self.chrome.proc is None:
            try:   # reused Chrome from an earlier run: ask it to quit
                cdp = await self._browser.new_browser_cdp_session()
                await cdp.send("Browser.close")
            except Exception:  # noqa: BLE001
                pass
        await self._disconnect()
        if self.chrome is not None and not keep_open:
            await self.chrome.stop()
        if self._pw is not None:
            await self._pw.stop()
        self._pw = None


def element_line(e: dict) -> str:
    kind = e["tag"] if e["tag"] in ("a", "button", "select", "textarea") else f"{e['tag']}:{e['type'] or 'text'}"
    kind = {"a": "link", "input:text": "field", "input:search": "search field", "input:email": "email field",
            "textarea": "text box", "input:password": "password field"}.get(kind, kind)
    extra = ""
    if e.get("value") not in (None, ""):
        extra = f" = “{e['value'][:40]}”"
    if e.get("options"):
        extra += f" options: {', '.join(e['options'][:8])}"
    flag = " [commits: use browser_submit]" if needs_submit(e) else (" [search box]" if e.get("search") and
                                                                       e["tag"] == "input" else "")
    return f"[{e['ref']}] {kind} “{e['label'] or '(no label)'}”{extra}{flag}"


def needs_submit(e: dict) -> bool:
    """True for anything that may commit: a labelled buy/send/delete control, or a form submit
    that isn't plainly a search. Plain web links navigate, so they don't count."""
    label = e.get("label") or ""
    if e["tag"] in ("textarea", "select") or (
            e["tag"] == "input" and e.get("type") not in ("submit", "image", "button", "reset")):
        return False
    if COMMIT_WORDS.search(label):
        return e["tag"] != "a" or not (e.get("href") or "").startswith("http")
    return bool(e.get("submits")) and not SAFE_WORDS.match(label)


def shown(snap: dict) -> list[dict]:
    """Main-content elements first, then the rest, then header/nav/footer; capped."""
    ordered = sorted(snap["elements"], key=lambda e: (e.get("priority", 1), e["ref"]))
    return ordered[:MAX_ELEMENTS]


def render(snap: dict) -> str:
    text = snap["text"].strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n…(page text cut)"
    show = shown(snap)
    els = "\n".join(element_line(e) for e in show) or "(no interactive elements)"
    more = len(snap["elements"]) - len(show)
    if more > 0:
        els += f"\n(+{more} more elements not listed; use browser_find with words from the button or link)"
    return f"Page: {snap['title']}\nURL: {snap['url']}\n\nText:\n{text}\n\nElements (act by number):\n{els}"


def check_url(url: str) -> str:
    url = url.strip()
    if re.match(r"^(javascript|data|file|about|chrome|blob|vbscript|view-source):", url, re.IGNORECASE):
        raise ToolError("Only http(s) web addresses can be opened.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "https://" + url
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ToolError("Only http(s) web addresses can be opened.")
    return url


def browser_tools(browser: Browser) -> list[Tool]:
    # The latest snapshot lives on the browser so element numbers survive a tool rebuild.
    state: dict = getattr(browser, "la_state", None) or {"snap": None}
    browser.la_state = state

    def element(ref: int) -> dict:
        snap = state["snap"]
        if snap is None:
            raise ToolError("Open a page first with browser_open.")
        for e in snap["elements"]:
            if e["ref"] == ref:
                return e
        raise ToolError(f"There's no element [{ref}] on the page; call browser_read to see the current numbers.")

    def result(snap: dict, display: str) -> ToolResult:
        state["snap"] = snap
        return ToolResult(render(snap), display,
                          {"title": snap["title"], "url": snap["url"], "shot": snap.get("shot")}, untrusted=True)

    async def open_page(a: dict) -> ToolResult:
        snap = await browser.goto(check_url(a["url"]))
        return result(snap, f"Opened {snap['title'] or snap['url']}")

    async def read_page(a: dict) -> ToolResult:
        snap = await browser.snapshot()
        return result(snap, f"Read {snap['title'] or snap['url']}")

    async def click(a: dict) -> ToolResult:
        e = element(a["ref"])
        if needs_submit(e):
            raise ToolError(f"[{e['ref']}] “{e['label']}” submits or commits something. Use browser_submit, "
                            "which asks the user first.")
        snap = await browser.click(e["ref"], label=e["label"])
        return result(snap, f"Clicked “{e['label'] or e['ref']}”")

    async def type_text(a: dict) -> ToolResult:
        e = element(a["ref"])
        if e.get("password"):
            raise ToolError("The agent never types passwords. Ask the user to type it in the browser window.")
        if SENSITIVE.search(e.get("label") or ""):
            raise ToolError(f"“{e['label']}” asks for payment or ID details, which the agent never types. "
                            "Ask the user to fill it in themselves in the browser window.")
        if e["tag"] not in ("input", "textarea", "select") and not e.get("editable"):
            raise ToolError(f"[{e['ref']}] isn't a text field.")
        if e.get("submits"):
            raise ToolError(f"[{e['ref']}] is a button, not a field.")
        enter = bool(a.get("enter"))
        if enter and not e.get("search"):
            raise ToolError("Enter can only be pressed in a search box. To send a form, use browser_submit.")
        snap = await browser.fill(e["ref"], a["text"], enter, label=e["label"])
        return result(snap, f"{'Searched' if enter else 'Typed into'} “{e['label'] or e['ref']}”")

    async def find(a: dict) -> ToolResult:
        snap = state["snap"]
        if snap is None:
            raise ToolError("Open a page first with browser_open.")
        words = [w for w in a["text"].lower().split() if w]
        hits = [e for e in sorted(snap["elements"], key=lambda e: (e.get("priority", 1), e["ref"]))
                if all(w in (e.get("label") or "").lower() for w in words)][:20]
        if not hits:
            return ToolResult(f"No element matching “{a['text']}” on this page.", "Nothing found", [])
        return ToolResult(f"Elements matching “{a['text']}”:\n" + "\n".join(element_line(e) for e in hits),
                          f"Found {len(hits)} element(s)", None, untrusted=True)

    async def submit(a: dict) -> ToolResult:
        e = element(a["ref"])
        snap = await browser.click(e["ref"], label=e["label"])
        return result(snap, f"Pressed “{e['label'] or e['ref']}”")

    def label_of(ref) -> str:
        try:
            e = element(int(ref))
            return f"“{e['label'] or '(no label)'}” on {state['snap']['title'] or state['snap']['url']}"
        except (ToolError, TypeError, ValueError):
            return f"element [{ref}]"

    intents = ("task", "computer_action", "quick_answer")
    return [
        Tool("browser_open", "Open a web page in the agent's browser window and read it.",
             obj({"url": s("Web address, e.g. https://example.com")}, ["url"]),
             "draft", "browser", open_page, lambda a: f"Open {a.get('url', '')}", intents),
        Tool("browser_read", "Read the current page again (text and numbered elements).", obj({}),
             "read", "browser", read_page, lambda a: "Read the current page", intents),
        Tool("browser_find", "Find buttons, links or fields on the current page by their words (also ones "
             "not listed in the snapshot).", obj({"text": s("Words on the element, e.g. add to cart")}, ["text"]),
             "read", "browser", find, lambda a: f"Look for “{a.get('text', '')}” on the page", intents),
        Tool("browser_click", "Click a link, tab or button by its number. Never for submitting, sending or "
             "buying (use browser_submit).", obj({"ref": i("Element number from the page snapshot")}, ["ref"]),
             "draft", "browser", click, lambda a: f"Click {label_of(a.get('ref'))}", ("task", "computer_action")),
        Tool("browser_type", "Type text into a field (or choose a dropdown option) by its number. "
             "Set enter=true only in a search box to run the search.",
             obj({"ref": i("Field number"), "text": s("Text to type, or the option to pick"),
                  "enter": {"type": "boolean", "description": "Press Enter afterwards (search boxes only)"}},
                 ["ref", "text"]),
             "draft", "browser", type_text, lambda a: f"Type into {label_of(a.get('ref'))}",
             ("task", "computer_action")),
        Tool("browser_submit", "Press a button that submits, sends, books, pays or deletes. "
             "The user approves every time.", obj({"ref": i("Element number")}, ["ref"]),
             "danger", "browser", submit, lambda a: f"Press {label_of(a.get('ref'))}", ("task", "computer_action")),
    ]
