from typer.testing import CliRunner

from localagent.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == "0.15.0"


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


def test_autostart_plist(tmp_path, monkeypatch, home):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: None)  # no launchctl here
    from localagent.cli import plist_path, plist_xml
    r = runner.invoke(app, ["autostart", "on"])
    assert r.exit_code == 0, r.stdout
    p = plist_path()
    assert p.exists() and "localagent.server" in p.read_text()
    import plistlib
    data = plistlib.loads(p.read_bytes())
    assert data["Label"] == "com.localaiagent.agent" and data["RunAtLoad"] is True
    assert "LOCALAGENT_HOME" in data.get("EnvironmentVariables", {})
    assert "autostart is on" in runner.invoke(app, ["autostart", "status"]).stdout.lower()
    runner.invoke(app, ["autostart", "off"])
    assert not p.exists()
    assert runner.invoke(app, ["autostart", "maybe"]).exit_code == 2
    assert "<string>/x/python</string>" in plist_xml("/x/python", tmp_path / "log")


def test_autostart_other_platforms(tmp_path, monkeypatch, home):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    from localagent.cli import autostart_path

    for platform, check in (("linux", "Exec="), ("win32", "-m localagent.server")):
        monkeypatch.setattr("sys.platform", platform)
        assert runner.invoke(app, ["autostart", "on"]).exit_code == 0
        p = autostart_path()
        assert p.exists() and check in p.read_text()
        assert "autostart is on" in runner.invoke(app, ["autostart", "status"]).stdout.lower()
        runner.invoke(app, ["autostart", "off"])
        assert not p.exists()


def test_running_pid_uses_psutil(home):
    import os

    from localagent.cli import _pid_file, _running_pid

    _pid_file().write_text(str(os.getpid()))
    assert _running_pid() == os.getpid()
    _pid_file().write_text("99999999")
    assert _running_pid() is None and not _pid_file().exists()
