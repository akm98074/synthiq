import os

import pytest

from typer.testing import CliRunner

from localagent.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == "0.17.2"


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


def test_mac_app_bundle(tmp_path, home):
    """On a Mac (CI runner included) the real osacompile/plutil build the applet; elsewhere the plain
    test-only writer is used. Either way the bundle carries our identity and usage strings."""
    import plistlib
    import shutil

    from localagent import macapp

    path, note = macapp.install(python="/opt/py/bin/python3", home=tmp_path, sign=False,
                                log=tmp_path / "server.log")
    info = plistlib.loads((path / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "ai.localagent.app" and info["LSUIElement"] is True
    assert "NSAppleEventsUsageDescription" in info and info["CFBundleName"] == "LocalAIAgent"
    exe = macapp.executable(tmp_path)
    if shutil.which("osacompile"):
        # A real Mach-O applet (what LaunchServices accepts), not a script.
        assert info["CFBundleExecutable"] == "applet" and exe.name == "applet"
        assert exe.read_bytes()[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
    else:
        assert info["CFBundleExecutable"] == "LocalAIAgent"
        assert '"/opt/py/bin/python3" -m localagent.launcher' in exe.read_text()
    assert macapp.installed(tmp_path) and note.startswith("not signed")


def test_autostart_plist_uses_app_when_present(tmp_path):
    import plistlib

    from localagent.cli import plist_xml

    xml = plist_xml("/py", tmp_path / "log", None, ["/Users/me/Applications/LocalAIAgent.app/Contents/MacOS/LocalAIAgent", "--no-open"])
    assert plistlib.loads(xml.encode())["ProgramArguments"][1] == "--no-open"


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell stand-ins for osacompile/plutil")
def test_mac_app_is_an_osacompile_applet(tmp_path, monkeypatch, home):
    """On a Mac the app is built by Apple's osacompile (a Mach-O applet LaunchServices accepts), not a
    shell script (LaunchServices error -10669). Stand-ins record what would run."""
    from localagent import macapp

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls.log"
    (bin_ / "osacompile").write_text(
        "#!/bin/sh\n"
        f'echo "osacompile $@" >> "{calls}"\n'
        'app="$2"; mkdir -p "$app/Contents/MacOS"; cp "$3" "$app/source.applescript"\n'
        'printf "<plist/>" > "$app/Contents/Info.plist"; : > "$app/Contents/MacOS/applet"\n')
    (bin_ / "plutil").write_text(f'#!/bin/sh\necho "plutil $@" >> "{calls}"\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "Application Support" / "server.log"
    path, note = macapp.install(python="/Users/me/.local/pipx/venvs/localaiagent/bin/python", home=tmp_path,
                                sign=False, log=log)
    src = (path / "source.applescript").read_text()
    assert src.startswith('do shell script "') and "-m localagent.launcher --no-open" in src
    assert f"'{log}'" in src and src.rstrip().endswith('&"')          # paths with spaces stay quoted
    log_text = calls.read_text()
    assert "plutil -replace CFBundleIdentifier -string ai.localagent.app" in log_text
    assert "plutil -replace LSUIElement -bool YES" in log_text and "NSAppleEventsUsageDescription" in log_text
    assert macapp.executable(tmp_path).name == "applet" and macapp.installed(tmp_path)


def test_start_falls_back_to_terminal_when_macos_refuses_the_app(monkeypatch, home):
    import subprocess as sp

    from localagent import cli, macapp

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "_healthy", lambda url: False)
    monkeypatch.setattr(macapp, "installed", lambda home=None: True)
    started = []
    monkeypatch.setattr(cli, "_start_background", lambda url: started.append(url))
    err = "_LSOpenURLsWithCompletionHandler() failed for the application LocalAIAgent.app with error -10669."
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a[0], 1, "", err))
    r = runner.invoke(app, ["start", "--no-open"])
    assert r.exit_code == 0, r.stdout
    assert started and "starting from Terminal instead" in r.stdout and "-10669" in r.stdout
    assert (home / macapp.LAUNCH_FAILED).exists() and not macapp.usable(home)
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: calls.append(a) or sp.CompletedProcess(a[0], 0))
    runner.invoke(app, ["start", "--no-open"])
    assert not calls and len(started) == 2                             # remembered: no retry until reinstall


def test_app_install_removes_an_app_macos_wont_launch(monkeypatch, tmp_path, home):
    from localagent import cli, macapp

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "_healthy", lambda url: False)
    bundle = tmp_path / "LocalAIAgent.app"
    bundle.mkdir()
    monkeypatch.setattr(macapp, "install", lambda **k: (bundle, "ad-hoc signed"))
    monkeypatch.setattr(macapp, "selftest", lambda base: (False, "error -10669"))
    r = runner.invoke(app, ["app", "install"])
    assert r.exit_code == 0 and "wouldn't launch" in r.stdout and not bundle.exists()
    bundle.mkdir()
    (home / macapp.LAUNCH_FAILED).write_text("old")
    monkeypatch.setattr(macapp, "selftest", lambda base: (True, "launched"))
    r = runner.invoke(app, ["app", "install"])
    assert "self-test passed" in r.stdout and not (home / macapp.LAUNCH_FAILED).exists()


def test_launcher_answers_selftest_without_starting(home, monkeypatch):
    from localagent import launcher, macapp

    (home / macapp.SELFTEST_REQUEST).write_text("1")
    monkeypatch.setattr("localagent.cli._healthy", lambda url: (_ for _ in ()).throw(AssertionError("no start")))
    launcher.main()
    assert (home / macapp.SELFTEST_OK).exists() and not (home / macapp.SELFTEST_REQUEST).exists()


def test_signin_link_carries_a_one_time_code_never_the_secret(monkeypatch, tmp_path):
    import httpx as _httpx

    from localagent import cli, security

    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    secret = security.api_token(tmp_path)
    seen = {}

    def fake_api(method, path, **kw):
        seen["call"] = (method, path)
        return _httpx.Response(200, json={"code": "ONE-TIME", "ttl": 60})

    monkeypatch.setattr(cli, "_api", fake_api)
    url = cli._signin_url("/api/gmail/login")
    assert seen["call"] == ("POST", "/api/signin-code")
    assert "c=ONE-TIME" in url and secret not in url and url.endswith("next=/api/gmail/login")

    def down(*a, **kw):
        raise _httpx.ConnectError("not running")

    monkeypatch.setattr(cli, "_api", down)
    url = cli._signin_url(wait=0)                    # agent not up: a plain link, still no secret
    assert secret not in url and "/auth" not in url
