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
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s
from .forms import SENSITIVE

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


class Browser(Protocol):
    async def goto(self, url: str) -> dict: ...
    async def snapshot(self) -> dict: ...
    async def click(self, ref: int) -> dict: ...
    async def fill(self, ref: int, text: str, enter: bool = False) -> dict: ...
    async def close(self) -> None: ...


class BrowserUnavailable(ToolError):
    pass


class PlaywrightBrowser:
    """One visible window on a dedicated persistent profile, opened on first use."""

    def __init__(self, profile_dir: Path, headless: bool = False, executable: str = ""):
        self.profile_dir, self.headless, self.executable = profile_dir, headless, executable
        self._pw = self._ctx = self._page = None
        self._lock = asyncio.Lock()

    @staticmethod
    def installed() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    async def _page_ready(self):
        if self._page is not None and not self._page.is_closed():
            return self._page
        if not self.installed():
            raise BrowserUnavailable("The browser add-on isn't installed. In Terminal run: "
                                     "pipx inject localaiagent playwright, then: localagent setup --browser")
        from playwright.async_api import Error as PWError, async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        attempts = ([{"executable_path": self.executable}] if self.executable
                    else [{"channel": "chrome"}, {}])
        last = None
        for extra in attempts:
            try:
                self._ctx = await self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir), headless=self.headless, viewport={"width": 1280, "height": 900},
                    **extra)
                break
            except PWError as exc:
                last = exc
        else:
            raise BrowserUnavailable("Couldn't start a browser. Install Google Chrome, or run: "
                                     f"localagent setup --browser ({str(last).splitlines()[0][:120]})")
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        return self._page

    async def _settle(self, page) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:  # noqa: BLE001 - busy pages never go idle; the snapshot is still useful
            pass

    async def snapshot(self) -> dict:
        page = await self._page_ready()
        return await page.evaluate(SNAPSHOT_JS, MAX_SCAN)

    async def goto(self, url: str) -> dict:
        async with self._lock:
            page = await self._page_ready()
            await page.goto(url, timeout=30000)
            await self._settle(page)
            return await page.evaluate(SNAPSHOT_JS, MAX_SCAN)

    async def click(self, ref: int) -> dict:
        async with self._lock:
            page = await self._page_ready()
            await page.locator(f'[data-la-ref="{int(ref)}"]').first.click(timeout=10000)
            await self._settle(page)
            return await page.evaluate(SNAPSHOT_JS, MAX_SCAN)

    async def fill(self, ref: int, text: str, enter: bool = False) -> dict:
        async with self._lock:
            page = await self._page_ready()
            loc = page.locator(f'[data-la-ref="{int(ref)}"]').first
            if await loc.evaluate("el => el.tagName.toLowerCase()") == "select":
                await loc.select_option(label=text, timeout=10000)
            else:
                await loc.fill(text, timeout=10000)
                if enter:
                    await loc.press("Enter")
                    await self._settle(page)
            return await page.evaluate(SNAPSHOT_JS, MAX_SCAN)

    async def close(self) -> None:
        if self._ctx is not None:
            await self._ctx.close()
        if self._pw is not None:
            await self._pw.stop()
        self._pw = self._ctx = self._page = None


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
        return ToolResult(render(snap), display, {"title": snap["title"], "url": snap["url"]}, untrusted=True)

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
        snap = await browser.click(e["ref"])
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
        snap = await browser.fill(e["ref"], a["text"], enter)
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
        snap = await browser.click(e["ref"])
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
