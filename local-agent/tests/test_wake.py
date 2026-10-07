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
    ("Heyari.", True, ""),                                         # Whisper ran it together
    ("Hey R.I., lights on", True, "lights on"),                     # or spelled it out
    ("Hey, Arie!", True, ""),
    ("Hey are you there?", False, ""),
    ("Hey, how are you?", False, ""),
    ("Hey Ori", False, ""),
    # Whisper's sound labels and spoken filler (0.17.0 missed these: heard, but never woke)
    ("[BLANK_AUDIO] Hey Ari", True, ""),
    ("(upbeat music) Hey Ari, what time is it?", True, "what time is it"),
    ("♪ Hey Ari ♪", True, ""),
    ("Okay, so hey Ari, what time is it?", True, "what time is it"),
    ("Hey, uh, Ari, lights off", True, "lights off"),
    ("Hey there Ari", True, ""),
    ("Hey Ari… what time is it", True, "what time is it"),
    ("so I told Ari about it", False, ""),
    ("[MUSIC]", False, ""),
    ("Hey, how are you?", False, ""),
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
        {"wake": False, "heard": "pass the salt please", "command": "", "ms": 5}   # shown briefly, never stored
    n = len(c.stt.calls)
    assert not c.post("/api/voice/wake", content=tone(0.1), headers={"Content-Type": "audio/wav"}).json()["wake"]
    assert len(c.stt.calls) == n                                      # too short: not even transcribed


def test_a_broken_wake_model_falls_back_to_the_main_one(voice_client):
    """A missing or broken tiny wake model used to fail every burst silently: the wake word just never woke."""
    from test_trust import rt_of

    c = voice_client
    c.put("/api/settings", json={"wake_word_enabled": True})
    rt = rt_of(c)

    class Broken:
        model = "missing"

        async def transcribe(self, audio):
            raise OSError("model files not found")

    rt.wake_stt = Broken()
    c.stt.text = "Hey Ari"
    r = c.post("/api/voice/wake", content=tone(1.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json()["wake"]
    assert rt.wake_stt is rt.stt                                      # remembered: no second failure per burst


def test_wake_errors_say_why(voice_client):
    c = voice_client
    r = c.post("/api/voice/wake", content=tone(1.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 409 and "Trust" in r.json()["detail"]
    c.put("/api/settings", json={"wake_word_enabled": True})

    async def boom(audio):
        raise ValueError("bad weights")

    c.stt.transcribe = boom
    r = c.post("/api/voice/wake", content=tone(1.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 503 and "localagent setup --voice" in r.json()["detail"]


def test_trust_switch_turns_voice_on_for_the_wake_word(voice_client):
    c = voice_client
    c.put("/api/settings", json={"voice_enabled": False})
    r = c.post("/api/trust/capability/wake", json={"enabled": True})
    assert r.status_code == 200
    st = c.get("/api/voice/status").json()
    assert st["enabled"] and st["wake"]["enabled"]


def test_wake_endpoint_with_whisper_sound_labels(voice_client):
    c = voice_client
    c.put("/api/settings", json={"wake_word_enabled": True})
    c.stt.text = "[BLANK_AUDIO] Hey Ari, what's on my calendar today?"
    r = c.post("/api/voice/wake", content=tone(1.5), headers={"Content-Type": "audio/wav"}).json()
    assert r["wake"] and r["command"] == "what's on my calendar today"
