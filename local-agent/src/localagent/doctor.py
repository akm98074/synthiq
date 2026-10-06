"""Health checks shared by `localagent doctor` and the UI."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from .config import Settings
from .llm.models import ram
from .llm.ollama import OllamaClient, OllamaError, model_present


async def run_checks(s: Settings, base: Path) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, warn: bool = False) -> None:
        checks.append({"name": name, "status": "ok" if ok else ("warn" if warn else "fail"),
                       "detail": detail})

    machine = platform.machine()
    is_mac_arm = sys.platform == "darwin" and machine == "arm64"
    add("platform", True if is_mac_arm else False,
        f"{platform.system()} {platform.release()} ({machine})"
        + ("" if is_mac_arm else " - Calendar, Contacts, Messages, Apple apps and screen context need "
           "macOS; everything else works here"),
        warn=True)
    add("python", sys.version_info >= (3, 11), sys.version.split()[0])

    mem = ram()
    add("memory", mem["total_gb"] >= 15,
        f"{mem['total_gb']} GB total, {mem['available_gb']} GB available"
        + ("" if mem["total_gb"] >= 15 else " - 16 GB+ recommended"), warn=True)

    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        add("data directory", True, str(base))
    except OSError as exc:
        add("data directory", False, f"{base}: {exc}")

    from .security import disk_encryption

    enc, enc_detail = disk_encryption()
    add("disk encryption", bool(enc), enc_detail + ("" if enc else " - turn on FileVault / BitLocker / LUKS so "
                                                    "your agent's data is protected if the computer is lost"),
        warn=True)

    if sys.platform == "darwin":
        from . import macapp

        add("permissions identity", macapp.installed(),
            "LocalAIAgent.app (permissions are granted to the app)" if macapp.installed()
            else "Terminal/Python - permissions you grant also apply to everything run there; "
                 "run: localagent app install", warn=True)

    if sys.platform == "darwin":
        from .connectors.eventkit import EventKitCalendar

        detail = EventKitCalendar().status_detail()
        tips = {
            "not installed": " - optional; run: pipx inject localaiagent pyobjc-framework-EventKit",
            "not asked yet": " - optional; run: localagent calendar-access",
            "access denied": " - Privacy & Security > Calendars > Terminal > Full Access",
        }
        add("calendar (EventKit)", detail == "ok",
            ("full access" if detail == "ok" else detail + tips.get(detail, ""))
            + ("" if detail == "ok" else " (AppleScript is used meanwhile; repeating events still listed)"),
            warn=True)

    if sys.platform == "darwin" and s.enable_messages:
        from .connectors.messages import IMessages, ContactNames
        from .tools.base import ToolError

        try:
            IMessages(Path(s.imessage_db).expanduser(), ContactNames(Path("/nonexistent"))).threads(1)
            add("messages (Full Disk Access)", True, "can read iMessage history")
        except ToolError as exc:
            add("messages (Full Disk Access)", False,
                str(exc) if "Full Disk Access" in str(exc) else f"{exc}", warn=True)

    if sys.platform == "darwin" and s.screen_context_enabled:
        from .connectors.screen import screen_permission

        state = screen_permission()
        add("screen context", bool(state),
            "allowed" if state else ("screen add-on missing: pipx inject localaiagent pyobjc-framework-Vision "
                                     "pyobjc-framework-Quartz" if state is None else "not allowed; run: localagent screen-access"),
            warn=True)

    if sys.platform.startswith("linux"):
        import shutil

        add("skill sandbox", bool(shutil.which("bwrap")),
            "bubblewrap found" if shutil.which("bwrap")
            else "custom skills with scripts need bubblewrap: sudo apt install bubblewrap", warn=True)

    if sys.platform != "darwin":
        from .notify import available
        from .voice.stt import FasterWhisper

        add("notifications", available(), "desktop notifications available" if available()
            else "no notifier found (Linux: install libnotify-bin for notify-send)", warn=True)
        ok, reason = FasterWhisper.status()
        add("voice", ok, "faster-whisper installed" if ok else reason, warn=True)

    if s.enable_browser:
        from .connectors.browser import PlaywrightBrowser, chrome_version, find_chrome

        exe = find_chrome(s.browser_executable)
        if not PlaywrightBrowser.installed():
            add("browser", False, "add-on missing: pipx inject localaiagent playwright", warn=True)
        elif exe is None:
            add("browser", False, "Google Chrome not found; install it from google.com/chrome", warn=True)
        else:
            add("browser", True, f"{chrome_version(exe)} ({exe}); test it with: localagent setup --no-pull --browser")

    client = OllamaClient(s.ollama_url, timeout=5)
    try:
        version = await client.version()
        add("ollama", True, f"v{version} at {s.ollama_url}")
        installed = await client.tags()
        for role, name in (("chat model", s.chat_model), ("fast model", s.fast_model),
                           ("embedding model", s.embed_model)):
            present = model_present(name, installed)
            add(role, present, name if present else f"{name} missing - run: ollama pull {name}")
    except OllamaError:
        add("ollama", False,
            f"not reachable at {s.ollama_url} - install with `brew install ollama`, "
            "then start it with `ollama serve` (or open the Ollama app)")
    finally:
        await client.aclose()
    return checks
