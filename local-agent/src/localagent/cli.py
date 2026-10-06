"""`localagent` command-line interface."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import httpx
import typer

from . import __version__
from .config import data_dir, load_settings, save_settings

app = typer.Typer(help="LocalAIAgent - a personal AI agent that runs on your Mac.",
                  no_args_is_help=True, add_completion=False)
eval_app = typer.Typer(help="Evaluation harnesses (Phase-0 gates).", no_args_is_help=True)
app.add_typer(eval_app, name="eval")

ICONS = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}


def _pid_file() -> Path:
    return data_dir() / "server.pid"


def _log_file() -> Path:
    return data_dir() / "server.log"


def _url() -> str:
    s = load_settings()
    return f"http://{s.host}:{s.port}"


def _running_pid() -> int | None:
    path = _pid_file()
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        path.unlink(missing_ok=True)
        return None


def _healthy(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def setup(
    pull: bool = typer.Option(True, help="Pull the configured models with Ollama."),
    agent_name: Optional[str] = typer.Option(None, help="What to call your agent."),
    user_name: Optional[str] = typer.Option(None, help="Your name."),
    chat_model: Optional[str] = typer.Option(None, help="Ollama tag for the main chat model."),
    fast_model: Optional[str] = typer.Option(None, help="Ollama tag for the fast/judge model."),
    embed_model: Optional[str] = typer.Option(None, help="Ollama tag for the embedding model."),
    voice: bool = typer.Option(False, "--voice", help="Also download the speech-to-text model (~1.6 GB)."),
    browser: bool = typer.Option(False, "--browser", help="Set up the browser for web tasks."),
) -> None:
    """Write the config and download the local models."""
    s = load_settings()
    overrides = {k: v for k, v in dict(agent_name=agent_name, user_name=user_name,
                                       chat_model=chat_model, fast_model=fast_model,
                                       embed_model=embed_model).items() if v}
    s.update(overrides)
    path = save_settings(s)
    typer.echo(f"Config: {path}")

    from .llm.ollama import OllamaClient, OllamaError

    async def _pull() -> bool:
        client = OllamaClient(s.ollama_url)
        try:
            typer.echo(f"Ollama v{await client.version()} at {s.ollama_url}")
            for name in dict.fromkeys([s.embed_model, s.fast_model, s.chat_model]):
                typer.echo(f"Pulling {name} ...")
                last = ""
                async for ev in client.pull(name):
                    status = ev.get("status", "")
                    total, done = ev.get("total"), ev.get("completed")
                    line = f"  {status}" + (f" {done * 100 // total}%" if total and done else "")
                    if line != last:
                        typer.echo(f"\r{line:<60}", nl=False)
                        last = line
                typer.echo(f"\r  {name}: ready{' ' * 50}")
            return True
        except OllamaError as exc:
            typer.secho(f"\n{exc}", fg="red")
            typer.echo("Install Ollama with `brew install ollama`, start it with `ollama serve` "
                       "(or open the Ollama app), then run `localagent setup` again.")
            return False
        finally:
            await client.aclose()

    if pull and not asyncio.run(_pull()):
        raise typer.Exit(1)
    if voice:
        _setup_voice(s.stt_model)
        _setup_voice(s.wake_model, "wake-word model (~75 MB)")
    if browser:
        _setup_browser()
    typer.secho("Setup complete. Run `localagent start`.", fg="green")


def _setup_browser() -> None:
    """Start the agent's Chrome once, the same way the agent does, and report exactly what happened."""
    from .connectors.browser import BrowserUnavailable, PlaywrightBrowser, chrome_version, find_chrome

    s = load_settings()
    if not PlaywrightBrowser.installed():
        typer.secho("The browser add-on isn't installed. Run: pipx inject localaiagent playwright", fg="yellow")
        raise typer.Exit(1)
    exe = find_chrome(s.browser_executable)
    if exe is None:
        typer.secho("Google Chrome wasn't found in /Applications or ~/Applications. Install it from "
                    "https://www.google.com/chrome and run this again.", fg="red")
        raise typer.Exit(1)
    typer.echo(f"Starting {chrome_version(exe)} ({exe}) with the agent's own profile ...")
    browser = PlaywrightBrowser(data_dir() / "browser-profile", s.browser_headless, s.browser_executable,
                                show_actions=False)

    async def check() -> str:
        try:
            # A local test page: checks Chrome itself, independent of the network.
            snap = await browser.goto("data:text/html,<title>LocalAIAgent browser check</title><p>OK</p>")
            return snap["title"]
        finally:
            await browser.close()

    try:
        title = asyncio.run(check())
    except BrowserUnavailable as exc:
        typer.secho(f"Browser check failed: {exc}", fg="red")
        raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001 - show any other failure verbatim
        typer.secho(f"Browser check failed: {exc.__class__.__name__}: {str(exc).splitlines()[0][:300]}", fg="red")
        raise typer.Exit(1)
    typer.secho(f"Browser works: {chrome_version(exe)} opened “{title}”.", fg="green")


def _setup_voice(model: str, what: str = "speech model (first time only, ~1.6 GB)") -> None:
    from .voice.stt import MLXWhisper

    stt = MLXWhisper(model)
    ok, reason = stt.status()
    if not ok:
        typer.secho(reason, fg="yellow")
        return
    typer.echo(f"Downloading {what}: {model} ...")
    import numpy as np

    try:
        asyncio.run(stt.transcribe(np.zeros(16000, dtype=np.float32)))
    except Exception as exc:  # noqa: BLE001 - surface any download/runtime problem
        typer.secho(f"Speech model setup failed: {exc}", fg="red")
        raise typer.Exit(1)
    typer.secho(f"Ready: {model}", fg="green")


@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in this terminal."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the UI in a browser."),
) -> None:
    """Start the agent and open its UI."""
    url = _url()
    if foreground:
        if open_browser:
            webbrowser.open(url)
        from .server import main
        sys.argv = [sys.argv[0]]
        main()
        return

    pid = _running_pid()
    if _healthy(url):
        typer.echo(f"Already running at {url}" + (f" (pid {pid})" if pid else " (started at login)"))
    else:
        log = open(_log_file(), "a")
        proc = subprocess.Popen(
            [sys.executable, "-m", "localagent.server"],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, env=os.environ.copy(),
        )
        _pid_file().write_text(str(proc.pid))
        for _ in range(100):
            if _healthy(url):
                break
            if proc.poll() is not None:
                typer.secho(f"Server exited early; see {_log_file()}", fg="red")
                raise typer.Exit(1)
            time.sleep(0.2)
        else:
            typer.secho(f"Server did not become healthy; see {_log_file()}", fg="red")
            raise typer.Exit(1)
        typer.secho(f"Started (pid {proc.pid}) at {url}", fg="green")
    if open_browser:
        webbrowser.open(url)


@app.command()
def stop() -> None:
    """Stop the background agent."""
    pid = _running_pid()
    if not pid:
        if plist_path().exists() and _healthy(_url()):
            typer.echo("The agent was started at login. Use `localagent autostart off` to stop it.")
        else:
            typer.echo("Not running.")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            break
    _pid_file().unlink(missing_ok=True)
    typer.echo("Stopped.")


@app.command()
def status() -> None:
    """Show whether the agent is running."""
    pid = _running_pid()
    url = _url()
    if _healthy(url):
        typer.echo(f"Running at {url}" + (f" (pid {pid})" if pid else " (started at login)"))
    else:
        typer.echo("Not running.")
    typer.echo(f"Autostart: {'on' if plist_path().exists() else 'off'}")
    typer.echo(f"Data: {data_dir()}")


@app.command()
def doctor() -> None:
    """Check Ollama, models, memory and the data directory."""
    from .doctor import run_checks

    checks = asyncio.run(run_checks(load_settings(), data_dir()))
    for c in checks:
        typer.echo(f"{ICONS[c['status']]} {c['name']:<16} {c['detail']}")
    if any(c["status"] == "fail" for c in checks):
        raise typer.Exit(1)


def _eventkit():
    from .connectors.eventkit import EventKitCalendar

    return EventKitCalendar()


@app.command("calendar-access")
def calendar_access() -> None:
    """Ask macOS for full calendar access (run this in Terminal)."""
    ek = _eventkit()
    if not ek.installed():
        typer.secho("The calendar add-on isn't installed. Run:", fg="yellow")
        typer.echo("    pipx inject localaiagent pyobjc-framework-EventKit")
        typer.echo("Until then, repeating events are still listed (expanded via AppleScript).")
        raise typer.Exit(1)
    status = ek.status_detail()
    if status == "ok":
        typer.secho("Full calendar access is already granted. Restart the agent if it still says AppleScript.",
                    fg="green")
        return
    if status == "not asked yet":
        typer.echo("macOS will now ask: \"Terminal would like full access to your calendars\". Click Allow.")
        asyncio.run(ek.request_access())
        status = ek.status_detail()
    if status == "ok":
        typer.secho("Granted. Now run: localagent stop, then localagent start", fg="green")
        return
    typer.secho(f"Calendar access: {status}.", fg="yellow")
    typer.echo("Open System Settings > Privacy & Security > Calendars, set Terminal to Full Access,")
    typer.echo("then run: localagent stop, then localagent start")
    typer.echo("If Terminal isn't listed there, macOS didn't offer the prompt to this tool; that's fine:")
    typer.echo("the agent still lists repeating events through AppleScript.")
    raise typer.Exit(1)


LAUNCH_LABEL = "com.localaiagent.agent"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def plist_xml(python: str, log_file: Path, home: str | None = None) -> str:
    env = (f"""
  <key>EnvironmentVariables</key>
  <dict><key>LOCALAGENT_HOME</key><string>{home}</string></dict>""" if home else "")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array><string>{python}</string><string>-m</string><string>localagent.server</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>{log_file}</string>
  <key>StandardErrorPath</key><string>{log_file}</string>{env}
</dict>
</plist>
"""


@app.command()
def autostart(action: str = typer.Argument("status", help="on | off | status")) -> None:
    """Start the agent automatically when you log in (optional)."""
    path = plist_path()
    uid = os.getuid()
    launchctl = shutil.which("launchctl")
    if action == "on":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plist_xml(sys.executable, _log_file(), os.environ.get("LOCALAGENT_HOME")))
        if launchctl:
            if _running_pid():
                stop()
            subprocess.run([launchctl, "bootout", f"gui/{uid}", str(path)], capture_output=True)
            subprocess.run([launchctl, "bootstrap", f"gui/{uid}", str(path)], capture_output=True)
        typer.secho(f"Autostart on ({path}). The agent now starts when you log in.", fg="green")
        typer.echo("Note: macOS treats the auto-started agent as a different app from Terminal, so\n"
                   "Calendar/Contacts/Mail may ask for permission again (or need switching on under\n"
                   "System Settings > Privacy & Security > Automation). Run `localagent autostart off`\n"
                   "to go back to starting it from Terminal.")
    elif action == "off":
        if launchctl and path.exists():
            subprocess.run([launchctl, "bootout", f"gui/{uid}", str(path)], capture_output=True)
        path.unlink(missing_ok=True)
        typer.echo("Autostart off. Start the agent with `localagent start`.")
    elif action == "status":
        typer.echo(f"Autostart is {'on' if path.exists() else 'off'}.")
    else:
        typer.secho("Use: localagent autostart on|off|status", fg="red")
        raise typer.Exit(2)


@eval_app.command("decision")
def eval_decision(
    file: Optional[Path] = typer.Option(None, help="JSONL with text + labels; default: shipped set."),
    backend: Optional[str] = typer.Option(None, help="hybrid | prototype | slm | systemone"),
    output: Optional[Path] = typer.Option(None, help="Write the JSON report here."),
) -> None:
    """Measure decision accuracy, calibration (ECE) and latency."""
    from .evals.decision import load_rows, run
    from .runtime import Runtime

    rows = load_rows(file)

    def progress(i: int, n: int) -> None:
        typer.echo(f"\r  {i}/{n}", nl=False)

    async def _run() -> dict:
        rt = Runtime(load_settings())
        try:
            typer.echo("Embedding seed examples (first run only) ...")
            await rt.prototype.ensure_embeddings()
            typer.echo(f"Evaluating {len(rows)} rows ...")
            return await run(rt.router, rows, backend=backend, progress=progress)
        finally:
            await rt.aclose()

    from .llm.ollama import OllamaError
    try:
        report = asyncio.run(_run())
    except OllamaError as exc:
        typer.secho(f"\n{exc}", fg="red")
        raise typer.Exit(1)
    typer.echo("")
    typer.echo(f"Backend: {report['backend']}   rows: {report['rows']}   "
               f"escalation rate: {report['escalation_rate']:.0%}")
    typer.echo(f"Latency: p50 {report['latency_ms']['p50']} ms   p95 {report['latency_ms']['p95']} ms")
    typer.echo(f"{'question':<20}{'n':>5}{'acc':>8}{'F1':>8}{'ECE':>8}")
    for q in report["questions"]:
        typer.echo(f"{q['question']:<20}{q['n']:>5}{q['accuracy']:>8.3f}{q['macro_f1']:>8.3f}{q['ece']:>8.3f}")
        for c in q["top_confusions"][:3]:
            typer.echo(f"    {c['true']} → {c['pred']}: {c['count']}")
    if report["gate"]:
        g = report["gate"]
        verdict = "PASS" if g["passed"] else "NOT YET"
        typer.secho(f"Phase-0 gate (intent acc ≥ {g['accuracy_target']:.0%}, ECE ≤ {g['ece_target']}): "
                    f"{verdict}", fg="green" if g["passed"] else "yellow")
    out = output or data_dir() / f"eval-decision-{int(time.time())}.json"
    out.write_text(json.dumps(report, indent=2))
    typer.echo(f"Report: {out}")


if __name__ == "__main__":
    app()


skill_app = typer.Typer(help="Create and list custom skills.", no_args_is_help=True)
app.add_typer(skill_app, name="skill")


@skill_app.command("new")
def skill_new(name: str = typer.Argument(..., help="Lower-case name with dashes, e.g. word-count")) -> None:
    """Create a skill folder with an example SKILL.md and script."""
    from .skills import scaffold

    try:
        folder = scaffold(data_dir() / "skills", name)
    except (ValueError, FileExistsError) as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(1)
    typer.echo(f"Created {folder}")
    typer.echo("Edit SKILL.md and main.py, then open the Connectors tab (it reloads skills).")


@skill_app.command("list")
def skill_list() -> None:
    """List installed skills and any problems with them."""
    from .skills import load_skills, sandbox_available

    skills = load_skills(data_dir() / "skills")
    if not skills:
        typer.echo(f"No skills yet. Create one with: localagent skill new my-skill  ({data_dir() / 'skills'})")
        return
    for sk in skills:
        state = "problem: " + "; ".join(sk.problems) if sk.problems else (
            f"{sk.tier}{', network' if sk.network else ''}{', runs ' + sk.run if sk.run else ', instructions only'}")
        typer.echo(f"{sk.name:<20} {state}")
    if not sandbox_available():
        typer.secho("Note: sandbox-exec isn't available here, so script skills won't run.", fg="yellow")


@app.command("screen-access")
def screen_access() -> None:
    """Ask macOS for Screen Recording permission (needed for screen context)."""
    from .connectors.screen import request_screen_permission, screen_permission

    if sys.platform != "darwin":
        typer.echo("Screen context needs macOS.")
        raise typer.Exit(1)
    state = screen_permission()
    if state is None:
        typer.secho("The screen add-on isn't installed. Run: "
                    "pipx inject localaiagent pyobjc-framework-Vision pyobjc-framework-Quartz", fg="yellow")
        raise typer.Exit(1)
    if not state:
        typer.echo("Asking macOS for permission to read the screen ...")
        state = bool(request_screen_permission())
    if state:
        typer.secho("Screen reading is allowed. Turn on Screen context in the app's Connectors tab.", fg="green")
        return
    typer.secho("Not allowed yet. Open System Settings → Privacy & Security → Screen & System Audio Recording, "
                "turn on Terminal, quit Terminal (Cmd+Q), reopen it, then run: localagent stop, localagent start",
                fg="yellow")
    raise typer.Exit(1)


channel_app = typer.Typer(help="Talk to the agent from your phone (iMessage).", no_args_is_help=True)
app.add_typer(channel_app, name="channel")


@channel_app.command("test")
def channel_test() -> None:
    """Send a test iMessage from the agent to your phone (the agent must be running)."""
    try:
        r = httpx.post(f"{_url()}/api/channels/imessage/test", timeout=60)
    except httpx.HTTPError:
        typer.secho("The agent isn't running. Start it with: localagent start", fg="red")
        raise typer.Exit(1)
    data = r.json()
    msg = data.get("message") or data.get("detail") or r.text
    ok = r.status_code == 200 and data.get("ok")
    typer.secho(msg, fg="green" if ok else "red")
    if not ok:
        raise typer.Exit(1)


@app.command("gmail-login")
def gmail_login() -> None:
    """Connect Gmail: save your Google OAuth client, then sign in with Google in the browser."""
    import getpass

    try:
        status = httpx.get(f"{_url()}/api/gmail", timeout=5).json()
    except httpx.HTTPError:
        typer.secho("The agent isn't running. Start it with: localagent start", fg="red")
        raise typer.Exit(1)
    client_id = typer.prompt("Google OAuth client ID", default=status.get("client_id") or "").strip()
    secret = getpass.getpass("Client secret (Enter to keep the saved one): ").strip()
    body = {"client_id": client_id, **({"client_secret": secret} if secret else {})}
    r = httpx.put(f"{_url()}/api/gmail/client", json=body, timeout=10)
    if r.status_code != 200:
        typer.secho(r.json().get("detail", r.text), fg="red")
        raise typer.Exit(1)
    typer.echo("Opening Google's sign-in page in your browser ...")
    webbrowser.open(f"{_url()}/api/gmail/login")
    for _ in range(150):
        time.sleep(2)
        st = httpx.get(f"{_url()}/api/gmail", timeout=5).json()
        if st.get("connected"):
            typer.secho(f"Gmail connected as {st.get('account')}.", fg="green")
            return
    typer.secho("Didn't see the sign-in finish. Try again, or use Settings → Gmail in the app.", fg="yellow")
    raise typer.Exit(1)
