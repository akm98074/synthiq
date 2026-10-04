"""`localagent` command-line interface."""
from __future__ import annotations

import asyncio
import json
import os
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
    typer.secho("Setup complete. Run `localagent start`.", fg="green")


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
    if pid and _healthy(url):
        typer.echo(f"Already running (pid {pid}) at {url}")
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
    if pid and _healthy(url):
        typer.echo(f"Running (pid {pid}) at {url}")
    else:
        typer.echo("Not running.")
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
