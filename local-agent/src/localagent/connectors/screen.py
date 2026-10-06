"""Opt-in screen context: what's on screen, as text, kept for a short while.

Every few minutes (and when asked) the agent takes a screenshot, reads the text in it
with Apple's on-device Vision OCR, and deletes the image straight away. Only the text,
the app name and the window title are kept, for `screen_retention_minutes` (default 2 h).

Nothing is captured when:
  - the feature is off (the default);
  - the frontmost app is on the blocklist (password managers, Messages… by default);
  - the screen is locked;
  - macOS hasn't granted Screen Recording to Terminal (the agent asks you to run
    `localagent screen-access` instead of capturing a blank picture).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from typing import Callable, Optional

from ..memory.store import Store
from ..tools.base import Tool, ToolError, ToolResult, i, obj, s
from .applescript import parse_records

SCHEMA = """
CREATE TABLE IF NOT EXISTS screen_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  app TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  digest TEXT NOT NULL
);
"""
LOCK_APPS = {"loginwindow", "screensaverengine"}
PERMISSION_HELP = ("macOS hasn't allowed screen reading. In Terminal run: localagent screen-access, then allow "
                   "Terminal under System Settings → Privacy & Security → Screen & System Audio Recording, "
                   "quit Terminal, reopen it and restart the agent.")
MAX_TEXT = 8000


def vision_ocr(path: str) -> str:
    """Text in an image, read with Apple's Vision framework (on-device)."""
    try:
        import Vision
        from Foundation import NSURL
    except ImportError as exc:
        raise ToolError("Screen reading needs the screen add-on. In Terminal run: "
                        "pipx inject localaiagent pyobjc-framework-Vision") from exc
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), {})
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise ToolError(f"Text recognition failed: {err}")
    lines = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if cand and len(cand):
            lines.append(str(cand[0].string()))
    return "\n".join(lines)


def screen_permission() -> Optional[bool]:
    """True/False from macOS, or None when it can't be checked (non-macOS, Quartz missing)."""
    try:
        import Quartz
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except (ImportError, AttributeError):
        return None


def request_screen_permission() -> Optional[bool]:
    try:
        import Quartz
        return bool(Quartz.CGRequestScreenCaptureAccess())
    except (ImportError, AttributeError):
        return None


async def screencapture_png() -> str:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="la-screen-")
    os.close(fd)
    proc = await asyncio.create_subprocess_exec("screencapture", "-x", "-t", "png", path,
                                                stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        os.unlink(path)
        raise ToolError(f"screencapture failed: {err.decode(errors='replace')[:200]}")
    return path


class ScreenContext:
    def __init__(self, store: Store, runner, blocklist: str, retention_minutes: int,
                 capture: Callable = screencapture_png, ocr: Callable[[str], str] = vision_ocr,
                 permission: Callable[[], Optional[bool]] = screen_permission, clock=time.time):
        self.store, self.runner = store, runner
        self.blocklist = {x.strip().lower() for x in blocklist.split(",") if x.strip()}
        self.retention = retention_minutes * 60
        self.capture, self.ocr, self.permission, self.clock = capture, ocr, permission, clock
        store.db.executescript(SCHEMA)
        store.db.commit()

    def purge(self) -> int:
        return self.store.execute("DELETE FROM screen_snapshots WHERE ts < ?",
                                  (self.clock() - self.retention,)).rowcount

    def forget_all(self) -> int:
        return self.store.execute("DELETE FROM screen_snapshots").rowcount

    async def front(self) -> tuple[str, str]:
        recs = parse_records(await self.runner.run("front_app", []))
        rec = recs[0] if recs else ["", ""]
        return rec[0], (rec[1] if len(rec) > 1 else "")

    async def snap(self, store: bool = True) -> dict:
        """Capture now. Returns {app, title, text, skipped?}."""
        self.purge()
        app, title = await self.front()
        if app.lower() in LOCK_APPS:
            return {"app": app, "title": "", "text": "", "skipped": "the screen is locked"}
        if app.lower() in self.blocklist:
            return {"app": app, "title": "", "text": "", "skipped": f"{app} is on the private-apps list"}
        if self.permission() is False:
            raise ToolError(PERMISSION_HELP)
        path = await self.capture()
        try:
            text = (await asyncio.to_thread(self.ocr, path)).strip()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        text = text[:MAX_TEXT]
        digest = hashlib.sha256(f"{app}\x1f{title}\x1f{text}".encode()).hexdigest()
        if store and text:
            last = self.store.query("SELECT digest FROM screen_snapshots ORDER BY id DESC LIMIT 1")
            if not last or last[0]["digest"] != digest:
                self.store.execute("INSERT INTO screen_snapshots(ts, app, title, text, digest) VALUES (?,?,?,?,?)",
                                   (self.clock(), app, title, text, digest))
        return {"app": app, "title": title, "text": text}

    def recent(self, query: str = "", minutes: int = 120, limit: int = 5) -> list[dict]:
        self.purge()
        since = self.clock() - minutes * 60
        rows = self.store.query("SELECT ts, app, title, text FROM screen_snapshots WHERE ts >= ? "
                                "ORDER BY ts DESC LIMIT 200", (since,))
        words = [w for w in query.lower().split() if len(w) > 2]
        out = []
        for r in rows:
            hay = f"{r['app']} {r['title']} {r['text']}".lower()
            if words and not all(w in hay for w in words):
                continue
            out.append({"at": time.strftime("%H:%M", time.localtime(r["ts"])), "app": r["app"],
                        "title": r["title"], "text": r["text"]})
            if len(out) >= limit:
                break
        return out

    def count(self) -> int:
        return self.store.query("SELECT COUNT(*) AS n FROM screen_snapshots")[0]["n"]


def screen_tools(ctx: ScreenContext) -> list[Tool]:
    async def now(a: dict) -> ToolResult:
        r = await ctx.snap()
        if r.get("skipped"):
            return ToolResult(f"Didn't look at the screen: {r['skipped']}.", "Screen not read", None)
        return ToolResult(f"On screen now: {r['app']} — “{r['title']}”\n\n{r['text'] or '(no text found)'}",
                          f"Read the screen ({r['app']})", {"app": r["app"], "title": r["title"]}, untrusted=True)

    async def recent(a: dict) -> ToolResult:
        items = ctx.recent(a.get("query", ""), a.get("minutes", 120), a.get("limit", 5))
        if not items:
            return ToolResult("Nothing matching in the recent screen history.", "No screen history found", [])
        body = "\n\n".join(f"[{x['at']}] {x['app']} — “{x['title']}”\n{x['text'][:1500]}" for x in items)
        return ToolResult("Recent screens (newest first):\n\n" + body, f"Found {len(items)} recent screen(s)",
                          [{"at": x["at"], "app": x["app"], "title": x["title"]} for x in items], untrusted=True)

    intents = ("task", "computer_action", "quick_answer")
    return [
        Tool("screen_now", "Read the text on the user's screen right now (what they're looking at).", obj({}),
             "read", "screen", now, lambda a: "Read your screen", intents),
        Tool("screen_recent", "Search what was on the user's screen recently (text only, last few hours).",
             obj({"query": s("Words to look for (optional)"), "minutes": i("How far back, in minutes (default 120)"),
                  "limit": i("Max results (default 5)")}),
             "read", "screen", recent, lambda a: "Search your recent screens", intents),
    ]
