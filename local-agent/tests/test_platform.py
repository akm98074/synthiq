"""Windows/Linux pieces (7g): notifications, voice fallbacks, Chrome discovery, Linux sandbox args,
doctor notes. Platform branches are exercised by monkeypatching sys.platform."""
import asyncio
import sys
from pathlib import Path

from localagent import notify
from localagent.config import Settings
from localagent.connectors import browser
from localagent.doctor import run_checks
from localagent.skills import Skill, bwrap_command
from localagent.voice import stt, tts


def test_notify_command_never_puts_text_in_the_command(monkeypatch):
    evil = '"; Remove-Item -Recurse C:\\ ; $(rm -rf ~)'
    monkeypatch.setattr(notify.sys, "platform", "win32")
    monkeypatch.setattr(notify.shutil, "which", lambda n: "C:/ps.exe" if n == "powershell" else None)
    cmd, env = notify.command("Ari", evil)
    assert cmd[0] == "C:/ps.exe" and cmd[-1] == notify.WINDOWS_TOAST
    assert all(evil not in part for part in cmd)
    assert env["LA_TITLE"] == "Ari" and env["LA_BODY"] == evil

    monkeypatch.setattr(notify.sys, "platform", "linux")
    monkeypatch.setattr(notify.shutil, "which", lambda n: "/usr/bin/notify-send" if n == "notify-send" else None)
    cmd, _ = notify.command("Ari", "-u critical " + "x" * 500)
    assert cmd[:3] == ["/usr/bin/notify-send", "--app-name=LocalAIAgent", "--"]   # "--": text is never a flag
    assert len(cmd[-1]) == 300
    monkeypatch.setattr(notify.shutil, "which", lambda n: None)
    assert notify.command("a", "b") is None and not notify.available()
    asyncio.run(notify.notify("a", "", "b"))                                    # no notifier: silently skipped


def test_faster_whisper_size_mapping():
    size = lambda m: stt.FasterWhisper(m).size()  # noqa: E731
    assert size("mlx-community/whisper-tiny.en-mlx") == "tiny.en"
    assert size("mlx-community/whisper-base-mlx") == "base.en"
    assert size("small") == "small"
    assert size("mlx-community/whisper-large-v3-turbo") == "small"          # too slow on CPU


def test_make_stt_and_tts_pick_by_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert isinstance(stt.make_stt("m"), stt.MLXWhisper)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert isinstance(stt.make_stt("m"), stt.FasterWhisper)
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(stt.make_stt("m"), stt.FasterWhisper)
    monkeypatch.setattr(tts.SayTTS, "available", staticmethod(lambda: False))
    assert isinstance(tts.make_tts("", 190), tts.Pyttsx3TTS)
    monkeypatch.setattr(tts.SayTTS, "available", staticmethod(lambda: True))
    assert isinstance(tts.make_tts("", 190), tts.SayTTS)


def test_find_chrome_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(browser.sys, "platform", "win32")
    local = tmp_path / "local"
    exe = local / browser.WINDOWS_PATHS[0]
    exe.parent.mkdir(parents=True, exist_ok=True)
    for k in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        monkeypatch.setenv(k, str(tmp_path / "empty"))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert browser.find_chrome() is None
    exe.write_text("")
    assert browser.find_chrome() == exe


def test_bwrap_command_hides_private_folders(tmp_path):
    home = tmp_path / "home"
    for p in (".ssh", ".local/share/keyrings", ".local/share/LocalAIAgent"):
        (home / p).mkdir(parents=True)
    folder = home / ".local/share/LocalAIAgent/skills/wc"
    (folder / "work").mkdir(parents=True)
    sk = Skill(name="wc", folder=folder, description="", body="", run="python3 main.py")
    args = bwrap_command(sk, home, ["python3", "main.py"])
    pairs = list(zip(args, args[1:]))
    assert args[0] == "bwrap" and ("--ro-bind", "/") in pairs and ("--tmpfs", "/tmp") in pairs
    for p in (".ssh", ".local/share/keyrings", ".local/share/LocalAIAgent"):
        assert ("--tmpfs", str((home / p).resolve())) in pairs
    # the skill folder is put back read-only after its parent was hidden, and only work/ is writable
    assert args.index(str(folder.resolve())) > args.index(str((home / ".local/share/LocalAIAgent").resolve()))
    assert ("--bind", str((folder / "work").resolve())) in pairs
    assert "--unshare-net" in args and args[-3:] == ["--", "python3", "main.py"]
    # the session bus (and so the Secret Service with the agent's keys) is out of reach
    assert "--unshare-ipc" in args
    if Path("/run/user").is_dir():
        assert ("--tmpfs", "/run/user") in pairs
    sk.network = True
    assert "--unshare-net" not in bwrap_command(sk, home, ["python3", "main.py"])


def test_doctor_explains_what_needs_macos(monkeypatch, tmp_path):
    import localagent.doctor as doctor

    monkeypatch.setattr(doctor.sys, "platform", "linux")
    checks = {c["name"]: c for c in asyncio.run(run_checks(Settings(ollama_url="http://127.0.0.1:9"), tmp_path))}
    assert "need macOS" in checks["platform"]["detail"]
    assert {"skill sandbox", "notifications", "voice"} <= set(checks)
    assert "calendar (EventKit)" not in checks
