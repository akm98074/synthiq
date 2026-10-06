"""Run the bundled AppleScripts with `osascript`.

Arguments are passed as argv (never interpolated into the script text), so
user or model text can't inject AppleScript. The first call to each app
triggers macOS's Automation permission prompt ("Terminal wants to control
Calendar"); osascript waits for the answer, hence the generous timeout.
"""
from __future__ import annotations

import asyncio
import re
import sys
from importlib import resources

from ..tools.base import ToolError

RS = "\x1e"  # record separator
US = "\x1f"  # unit (field) separator

APP_NAMES = {
    "calendar": "Calendar", "reminders": "Reminders", "notes": "Notes",
    "mail": "Mail", "contacts": "Contacts", "messages": "Messages", "open": "the app",
    "apps": "System Events", "app": "the app", "ui": "System Events", "front": "System Events",
    "shortcuts": "Shortcuts",
}


def script_text(name: str) -> str:
    return resources.files("localagent.connectors.scripts").joinpath(f"{name}.applescript").read_text()


def parse_records(out: str) -> list[list[str]]:
    return [rec.split(US) for rec in out.split(RS) if rec.strip()]


def explain_error(stderr: str, app: str) -> str:
    code = re.search(r"\((-?\d+)\)\s*$", stderr.strip())
    num = code.group(1) if code else ""
    if num in ("-1719", "-25211") or "assistive access" in stderr:
        return ("macOS needs Accessibility permission to read or press buttons in other apps. Open System "
                "Settings → Privacy & Security → Accessibility, turn on your Terminal app, then quit Terminal, "
                "reopen it and restart the agent.")
    if num == "-1743" or "Not authorized" in stderr:
        return (f"macOS blocked access to {app}. Open System Settings → Privacy & Security → "
                f"Automation, allow your Terminal app to control {app}, then try again.")
    if num == "-1728" or "Can’t get" in stderr or "Can't get" in stderr:
        return f"{app} couldn't find that item: {stderr.strip()[:200]}"
    if num == "-600":
        return f"{app} isn't running and couldn't be started."
    return f"{app} error: {stderr.strip()[:300]}"


class AppleScriptRunner:
    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    @staticmethod
    def available() -> bool:
        return sys.platform == "darwin"

    async def run(self, name: str, args: list[str]) -> str:
        app = APP_NAMES.get(name.split("_")[0], "the app")
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-", *[str(a) for a in args],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ToolError("osascript is not available (this connector needs macOS).") from exc
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(script_text(name).encode()), self.timeout
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise ToolError(
                f"{app} took too long to answer. If macOS showed a permission prompt, "
                "allow it and try again."
            ) from exc
        if proc.returncode != 0:
            raise ToolError(explain_error(err.decode(errors="replace"), app))
        return out.decode(errors="replace").rstrip("\n")
