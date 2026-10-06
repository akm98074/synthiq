import numpy as np
import pytest

from localagent.voice.stt import write_wav
from localagent.voice.wake import match, phon, wake_phrases

P = wake_phrases("Ari")


@pytest.mark.parametrize("text,woke,rest", [
    ("Hey Ari", True, ""),
    ("hey ari, what is on my calendar today?", True, "what is on my calendar today"),
    ("Hi Ari.", True, ""),
    ("Hey Harry what time is it", True, "what time is it"),        # a common mishearing
    ("um hey ari", True, ""),
    ("Ari, lights off", True, "lights off"),
    ("okay ari open safari", True, "open safari"),
    ("Hey Siri", False, ""),
    ("Are you there", False, ""),
    ("I said hey to Mary", False, ""),
    ("the weather is nice", False, ""),
    ("Arrive at 5", False, ""),
    ("hey everyone", False, ""),
])
def test_match(text, woke, rest):
    got = match(text, P)
    assert got[0] is woke and got[2] == rest


def test_custom_phrases_and_names():
    assert match("hey jarvis", wake_phrases("Ari", "hey jarvis"))[0]
    assert match("Hey Max, play music", wake_phrases("Max"))[2] == "play music"
    assert phon("Harry") == phon("Ari") == "ari"


def tone(seconds):
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    return write_wav(0.3 * np.sin(2 * np.pi * 220 * t))


def test_wake_endpoint(voice_client):
    c = voice_client
    r = c.post("/api/voice/wake", content=tone(1.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 409                                      # off by default
    assert c.get("/api/voice/status").json()["wake"] == {"enabled": False, "phrase": "Hey Ari"}
    c.put("/api/settings", json={"wake_word_enabled": True})
    c.stt.text = "Hey Ari, what's on my calendar today?"
    r = c.post("/api/voice/wake", content=tone(1.5), headers={"Content-Type": "audio/wav"}).json()
    assert r["wake"] and r["command"] == "what's on my calendar today"
    c.stt.text = "pass the salt please"
    assert c.post("/api/voice/wake", content=tone(1.0), headers={"Content-Type": "audio/wav"}).json() == \
        {"wake": False, "heard": "", "command": "", "ms": 5}
    n = len(c.stt.calls)
    assert not c.post("/api/voice/wake", content=tone(0.1), headers={"Content-Type": "audio/wav"}).json()["wake"]
    assert len(c.stt.calls) == n                                      # too short: not even transcribed
