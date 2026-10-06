from typer.testing import CliRunner

from localagent.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == "0.16.1"


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


def test_mac_app_bundle(tmp_path):
    import plistlib

    from localagent import macapp

    path, note = macapp.install(python="/opt/py/bin/python3", home=tmp_path, sign=False)
    info = plistlib.loads((path / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "ai.localagent.app" and info["CFBundleExecutable"] == "LocalAIAgent"
    assert "NSAppleEventsUsageDescription" in info and info["LSUIElement"] is True
    exe = macapp.executable(tmp_path)
    assert exe.read_text().startswith("#!/bin/sh") and '"/opt/py/bin/python3" -m localagent.launcher' in exe.read_text()
    assert macapp.installed(tmp_path) and note.startswith("not signed")


def test_autostart_plist_uses_app_when_present(tmp_path):
    import plistlib

    from localagent.cli import plist_xml

    xml = plist_xml("/py", tmp_path / "log", None, ["/Users/me/Applications/LocalAIAgent.app/Contents/MacOS/LocalAIAgent", "--no-open"])
    assert plistlib.loads(xml.encode())["ProgramArguments"][1] == "--no-open"
