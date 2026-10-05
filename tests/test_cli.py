from typer.testing import CliRunner

from localagent.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == "0.1.1"


def test_setup_doctor_eval(settings, home):
    r = runner.invoke(app, ["setup", "--agent-name", "Juno"])
    assert r.exit_code == 0, r.stdout
    assert "Setup complete" in r.stdout
    r = runner.invoke(app, ["doctor"])
    assert "ollama" in r.stdout
    r = runner.invoke(app, ["eval", "decision", "--backend", "prototype"])
    assert r.exit_code == 0, r.stdout
    assert "intent" in r.stdout and "Phase-0 gate" in r.stdout


def test_setup_without_ollama(home):
    from localagent.config import Settings, save_settings
    save_settings(Settings(ollama_url="http://127.0.0.1:9"), home)
    r = runner.invoke(app, ["setup"])
    assert r.exit_code == 1 and "brew install ollama" in r.stdout
