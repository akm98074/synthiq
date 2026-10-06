"""A small macOS app bundle, ~/Applications/LocalAIAgent.app, that runs the agent.

Why: macOS grants privacy permissions (Full Disk Access, Automation, Calendars, Accessibility,
Screen Recording) to the *app* that runs a program. Started from Terminal, those grants go to
Terminal (and so to everything else you run there). Started from this bundle, they go to
"LocalAIAgent" with its own identity, and System Settings shows them under that name.

The bundle is an AppleScript applet built on this Mac by Apple's `osacompile` (macOS refuses to
launch a bundle whose main program is a shell script: LaunchServices error -10669), then ad-hoc
signed (`codesign -s -`); there is no Apple Developer ID. macOS may ask for the permissions again
after an upgrade, because the signature changes. `localagent app install` launches it once to
check; if macOS won't run it, the agent simply runs from Terminal.
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
    """The app's main program: `applet` for an osacompile-built app, else the plain launcher."""
    macos = app_path(home) / "Contents" / "MacOS"
    return macos / "applet" if (macos / "applet").exists() else macos / NAME


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
    """Plain shell launcher. Only used where osacompile doesn't exist (Linux tests): macOS
    LaunchServices refuses bundles whose main executable is a script (error -10669)."""
    q = python.replace('"', '\\"')
    return f"""#!/bin/sh
# LocalAIAgent launcher: runs the agent so that macOS attributes its permissions to this app.
exec "{q}" -m localagent.launcher "$@"
"""


def _as(text: str) -> str:
    """An AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def applet_source(python: str, log: Path, home_env: str | None = None) -> str:
    """AppleScript for the app: start the agent in the background (owned by this app, so macOS
    asks for permissions as LocalAIAgent) and quit. An applet gets no command-line arguments,
    so the agent is always started without opening a browser; `localagent start` opens it."""
    env = f"LOCALAGENT_HOME={_q(home_env)} " if home_env else ""
    cmd = f"{env}{_q(python)} -m localagent.launcher --no-open >> {_q(str(log))} 2>&1 &"
    return f"do shell script {_as(cmd)}\n"


def _q(text: str) -> str:
    """POSIX single-quoting."""
    return "'" + text.replace("'", "'\\''") + "'"


def _plutil(plist: Path, key: str, kind: str, value: str) -> None:
    subprocess.run(["plutil", "-replace", key, f"-{kind}", value, str(plist)], check=True,
                   capture_output=True, text=True)


def _build_applet(app: Path, python: str, log: Path, compiler: str, version: str) -> None:
    import os
    import tempfile

    if app.exists():
        shutil.rmtree(app)
    app.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False, encoding="utf-8") as f:
        f.write(applet_source(python, log, os.environ.get("LOCALAGENT_HOME")))
        src = f.name
    try:
        r = subprocess.run([compiler, "-o", str(app), src], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"osacompile failed: {(r.stderr or r.stdout).strip()[:300]}")
    finally:
        Path(src).unlink(missing_ok=True)
    plist = app / "Contents" / "Info.plist"
    _plutil(plist, "CFBundleIdentifier", "string", BUNDLE_ID)
    _plutil(plist, "CFBundleName", "string", NAME)
    _plutil(plist, "CFBundleDisplayName", "string", NAME)
    _plutil(plist, "CFBundleShortVersionString", "string", version)
    _plutil(plist, "LSUIElement", "bool", "YES")
    for key, text in USAGE.items():
        _plutil(plist, key, "string", text)


def _write_plain(app: Path, python: str, version: str) -> None:
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_text(info_plist(version), encoding="utf-8")
    exe = contents / "MacOS" / NAME
    exe.write_text(launcher_script(python), encoding="utf-8")
    exe.chmod(0o755)


def install(python: str | None = None, home: Path | None = None, sign: bool = True,
            compiler: str | None = None, log: Path | None = None) -> tuple[Path, str]:
    """Create or refresh the bundle. Returns (path, signing note). On macOS the app is an
    AppleScript applet compiled by Apple's osacompile (a real Mach-O stub LaunchServices accepts)."""
    from . import __version__
    from .config import data_dir

    app = app_path(home)
    python = python or sys.executable
    compiler = compiler or shutil.which("osacompile")
    if compiler:
        _build_applet(app, python, log or data_dir() / "server.log", compiler, __version__)
    elif sys.platform == "darwin":
        raise RuntimeError("osacompile isn't available, so the app can't be built; the agent runs from Terminal.")
    else:
        _write_plain(app, python, __version__)          # tests / non-Mac only
    note = "not signed (codesign not available)"
    if sign and shutil.which("codesign"):
        r = subprocess.run(["codesign", "--force", "-s", "-", str(app)], capture_output=True, text=True)
        note = "ad-hoc signed" if r.returncode == 0 else f"signing failed: {r.stderr.strip()[:200]}"
    return app, note


SELFTEST_REQUEST = "app-selftest-request"
SELFTEST_OK = "app-selftest-ok"
LAUNCH_FAILED = "app-launch-failed"


def selftest(base: Path, home: Path | None = None, timeout: float = 15.0) -> tuple[bool, str]:
    """Ask macOS to launch the app once; the launcher sees the request file, answers and exits
    without starting the agent. Returns (ok, detail)."""
    import time

    req, ok = base / SELFTEST_REQUEST, base / SELFTEST_OK
    ok.unlink(missing_ok=True)
    req.write_text(str(time.time()), encoding="utf-8")
    r = subprocess.run(["open", "-g", "-a", str(app_path(home))], capture_output=True, text=True)
    if r.returncode != 0:
        req.unlink(missing_ok=True)
        return False, (r.stderr or r.stdout).strip()[:300] or f"open exited {r.returncode}"
    end = time.time() + timeout
    while time.time() < end:
        if ok.exists():
            ok.unlink(missing_ok=True)
            return True, "launched"
        time.sleep(0.25)
    req.unlink(missing_ok=True)
    return False, "the app opened but didn't run the agent"


def installed(home: Path | None = None) -> bool:
    return (app_path(home) / "Contents" / "Info.plist").exists()


def usable(base: Path, home: Path | None = None) -> bool:
    """Installed, and macOS hasn't refused to launch it."""
    return installed(home) and not (base / LAUNCH_FAILED).exists()
