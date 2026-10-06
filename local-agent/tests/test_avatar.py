import io
import shutil
import wave

import pytest

from localagent.voice.tts import SayTTS


def test_audio_endpoint(voice_client):
    c = voice_client
    assert c.get("/api/voice/status").json()["avatar"] is False
    r = c.post("/api/voice/audio", json={"text": "Hello **there**"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getframerate() == 22050 and w.getnframes() > 20000
    c.put("/api/settings", json={"avatar_enabled": True})
    assert c.get("/api/voice/status").json()["avatar"] is True


def test_say_command_for_wav(monkeypatch, tmp_path):
    calls = []

    class Proc:
        returncode = 0

        async def communicate(self):
            out = calls[-1][calls[-1].index("-o") + 1]
            open(out, "wb").write(b"RIFFfake")
            return b"", b""

    async def fake_exec(*cmd, **kw):
        calls.append(list(cmd))
        return Proc()

    import asyncio

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/say")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    tts = SayTTS(voice="Samantha", rate=200)
    data = asyncio.run(tts.synthesize("Hi there"))
    assert data == b"RIFFfake"
    cmd = calls[0]
    assert cmd[:3] == ["say", "-r", "200"] and ["-v", "Samantha"] == cmd[3:5]
    assert "--file-format=WAVE" in cmd and "--data-format=LEI16@22050" in cmd and cmd[-2] == "-f"
