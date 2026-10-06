import numpy as np

from localagent.voice.stt import read_wav, resample, write_wav
from localagent.voice.tts import SayTTS, speakable


def test_wav_roundtrip_and_resample():
    t = np.linspace(0, 1, 48000, endpoint=False)
    stereo = np.stack([np.sin(2 * np.pi * 440 * t)] * 2, axis=1).astype(np.float32)
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((stereo * 30000).astype("<i2").tobytes())
    audio = read_wav(buf.getvalue())
    assert audio.dtype == np.float32 and len(audio) == 16000
    assert 0.8 < np.abs(audio).max() <= 1.0
    assert len(read_wav(write_wav(np.zeros(8000, dtype=np.float32)))) == 8000
    assert len(resample(np.ones(441), 44100, 16000)) == 160


def test_speakable_strips_markdown():
    text = "## Plan\n- **Buy** milk ☀️\n- See [link](http://x)\n```code```"
    out = speakable(text)
    assert "**" not in out and "#" not in out and "http" not in out and "☀" not in out
    assert "Buy milk" in out and "link" in out


def test_say_command_uses_file_and_voice():
    cmd = SayTTS("Samantha", 200).command("/tmp/x.txt")
    assert cmd == ["say", "-r", "200", "-v", "Samantha", "-f", "/tmp/x.txt"]


def _wav(seconds=1.0):
    return write_wav((0.1 * np.sin(np.linspace(0, 400, int(16000 * seconds)))).astype(np.float32))


def test_voice_endpoints(voice_client):
    c = voice_client
    st = c.get("/api/voice/status").json()
    assert st["stt"]["available"] and st["tts"]["voices"] == ["Samantha", "Daniel"]
    r = c.post("/api/voice/transcribe", content=_wav(1.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json()["text"] == "what's on my calendar today?"
    assert r.json()["seconds"] == 1.0 and c.stt.calls == [16000]
    assert c.post("/api/voice/transcribe", content=_wav(0.1)).json()["text"] == ""
    assert c.post("/api/voice/transcribe", content=b"not audio").status_code == 400
    assert c.post("/api/voice/transcribe", content=b"").status_code == 400
    assert c.post("/api/voice/speak", json={"text": "Hello **there**"}).json()["finished"]
    assert c.tts.spoken == ["Hello **there**"]
    assert c.post("/api/voice/stop").status_code == 200 and c.tts.stopped >= 1


def test_stt_unavailable_reports_clearly(client):
    st = client.get("/api/voice/status").json()
    import importlib.util
    if importlib.util.find_spec("mlx_whisper") is None:
        assert not st["stt"]["available"] and "voice add-on" in st["stt"]["reason"]
        r = client.post("/api/voice/transcribe", content=_wav(1.0))
        assert r.status_code == 503
