"""A small macOS app bundle, ~/Applications/LocalAIAgent.app, that runs the agent.

Why: macOS grants privacy permissions (Full Disk Access, Automation, Calendars, Accessibility,
Screen Recording) to the *app* that runs a program. Started from Terminal, those grants go to
Terminal (and so to everything else you run there). Started from this bundle, they go to
"LocalAIAgent" with its own identity, and System Settings shows them under that name.

The bundle is ad-hoc signed on this Mac (`codesign -s -`); there is no Apple Developer ID.
macOS may ask for the permissions again after an upgrade, because the signature changes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

BUNDLE_ID = "ai.localagent.app"
NAME = "LocalAIAgent"

USAGE = {
    "NSAppleEventsUsageDescription": "LocalAIAgent uses Calendar, Reminders, Notes, Mail, Contacts and Messages "
                                     "only when you ask it to, or for the nudges you switched on.",
    "NSCalendarsFullAccessUsageDescription": "To show your agenda and add events you ask for.",
    "NSCalendarsUsageDescription": "To show your agenda and add events you ask for.",
    "NSRemindersFullAccessUsageDescription": "To list and add reminders you ask for.",
    "NSRemindersUsageDescription": "To list and add reminders you ask for.",
    "NSContactsUsageDescription": "To find the people you mention.",
    "NSMicrophoneUsageDescription": "For voice commands, only while you use them.",
}


def app_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Applications" / f"{NAME}.app"


def executable(home: Path | None = None) -> Path:
    return app_path(home) / "Contents" / "MacOS" / NAME


def info_plist(version: str) -> str:
    usage = "".join(f"\n  <key>{k}</key><string>{escape(v)}</string>" for k, v in USAGE.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundleName</key><string>{NAME}</string>
  <key>CFBundleDisplayName</key><string>{NAME}</string>
  <key>CFBundleExecutable</key><string>{NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{escape(version)}</string>
  <key>CFBundleVersion</key><string>{escape(version)}</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>{usage}
</dict>
</plist>
"""


def launcher_script(python: str) -> str:
    q = python.replace('"', '\\"')
    return f"""#!/bin/sh
# LocalAIAgent launcher: runs the agent so that macOS attributes its permissions to this app.
exec "{q}" -m localagent.launcher "$@"
"""


def install(python: str | None = None, home: Path | None = None, sign: bool = True) -> tuple[Path, str]:
    """Create or refresh the bundle. Returns (path, signing note)."""
    from . import __version__

    app = app_path(home)
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_text(info_plist(__version__))
    exe = executable(home)
    exe.write_text(launcher_script(python or sys.executable))
    exe.chmod(0o755)
    note = "not signed (codesign not available)"
    if sign and shutil.which("codesign"):
        r = subprocess.run(["codesign", "--force", "--deep", "-s", "-", "--identifier", BUNDLE_ID, str(app)],
                           capture_output=True, text=True)
        note = "ad-hoc signed" if r.returncode == 0 else f"signing failed: {r.stderr.strip()[:200]}"
    return app, note


def installed(home: Path | None = None) -> bool:
    return executable(home).exists()
