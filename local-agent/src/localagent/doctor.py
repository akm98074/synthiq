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
        + ("" if is_mac_arm else " - Step 1 is tuned for Apple Silicon; other platforms are untested"),
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
