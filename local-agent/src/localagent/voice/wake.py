"""Wake word: "Hey Ari" (the agent's name), matched on a short on-device transcription.

The browser keeps the microphone open, cuts each short burst of speech (0.35–6 s), and
sends it here. A tiny Whisper model transcribes it, and this module decides whether it
starts with the wake phrase. Fuzzy matching absorbs small mishearings ("hey harry",
"hi ari"); anything said after the phrase is returned as the command, so "Hey Ari,
what's on today?" works in one breath.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

GREETINGS = ("hey", "hi", "hello", "ok", "okay", "yo")
THRESHOLD = 0.75


def normalize(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def wake_phrases(agent_name: str, extra: str = "") -> list[str]:
    name = " ".join(normalize(agent_name)) or "agent"
    phrases = [f"{g} {name}" for g in GREETINGS] + [name]
    phrases += [" ".join(normalize(p)) for p in extra.split(",") if p.strip()]
    return list(dict.fromkeys(p for p in phrases if p))


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def phon(word: str) -> str:
    """Rough sound-alike form: 'Harry' and 'Ari' sound the same to a speech model."""
    w = re.sub(r"(.)\1+", r"\1", word.lower())
    w = w[1:] if w.startswith("h") and len(w) > 2 else w
    w = re.sub(r"(ie|ee|ey|y)$", "i", w)
    return w


def match(text: str, phrases: list[str]) -> tuple[bool, str, str]:
    """(woke, matched phrase, the rest of the utterance).

    The phrase must open the utterance (one filler word allowed: "um, hey Ari"). The greeting
    may be loose ("hi"/"hey"), but the name must sound like the agent's name, so "Hey Siri"
    or "are you there" don't wake it.
    """
    spans = [m.span() for m in re.finditer(r"[a-z0-9']+", text.lower())]
    words = normalize(text)
    if len(spans) != len(words):           # exotic characters: fall back to whitespace words
        spans = [m.span() for m in re.finditer(r"\S+", text)][:len(words)]

    def rest_after(end: int) -> str:
        return text[spans[end - 1][1]:].strip(" ,.!?;:") if 0 < end <= len(spans) else ""
    for phrase in phrases:
        parts = phrase.split()
        greet = parts[:-1] if parts[0] in GREETINGS and len(parts) > 1 else []
        name = parts[len(greet):]
        for start in (0, 1):
            window = words[start:start + len(parts)]
            if len(window) < len(parts):
                continue
            if greet and _sim(" ".join(window[:len(greet)]), " ".join(greet)) < 0.6:
                continue
            got = " ".join(phon(w) for w in window[len(greet):])
            want = " ".join(phon(w) for w in name)
            need = THRESHOLD if greet else 0.9      # a bare name must be a near-exact match
            if _sim(got, want) < need:
                continue
            end = start + len(parts)
            rest = rest_after(end)
            return True, phrase, rest
    # Whisper sometimes runs the phrase together or spells it out ("Heyari", "Hey R.I."):
    # compare the first one to three words glued together, with a stricter bar.
    for phrase in phrases:
        parts = phrase.split()
        if len(parts) < 2:
            continue
        want = "".join(parts[:-1]) + phon(parts[-1])
        for start in (0, 1):
            for n in (1, 2, 3):
                window = words[start:start + n]
                if len(window) < n:
                    break
                glued = "".join(window[:-1]) + phon(window[-1]) if n > 1 else phon(window[0])
                if _sim(glued, want) >= 0.9:
                    end = start + n
                    rest = rest_after(end)
                    return True, phrase, rest
    return False, "", ""
