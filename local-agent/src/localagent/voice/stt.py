"""Speech to text, on-device.

The browser sends 16 kHz mono 16-bit WAV (no ffmpeg needed). Transcription uses
mlx-whisper on Apple Silicon; the model downloads from Hugging Face on first use
and then works offline.
"""
from __future__ import annotations

import asyncio
import io
import time
import wave

import numpy as np

TARGET_RATE = 16000


class AudioError(ValueError):
    pass


def read_wav(data: bytes) -> np.ndarray:
    """Decode PCM WAV bytes into float32 mono at 16 kHz."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"Not a valid WAV file: {exc}") from exc
    if width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise AudioError(f"Unsupported sample width {width}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return resample(audio, rate, TARGET_RATE)


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(audio) == 0:
        return audio.astype(np.float32)
    n = int(round(len(audio) * dst / src))
    x_old = np.linspace(0, 1, num=len(audio), endpoint=False)
    x_new = np.linspace(0, 1, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def write_wav(audio: np.ndarray, rate: int = TARGET_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class MLXWhisper:
    name = "mlx-whisper"

    def __init__(self, model: str):
        self.model = model

    @staticmethod
    def status() -> tuple[bool, str]:
        try:
            import mlx_whisper  # noqa: F401
        except Exception:  # noqa: BLE001 - ImportError, or mlx failing off Apple Silicon
            return False, ("Voice input needs the voice add-on (Apple Silicon Macs). Re-run the "
                           "installer, or: pipx install --force 'localaiagent[voice]'")
        return True, ""

    async def transcribe(self, audio: np.ndarray) -> dict:
        ok, reason = self.status()
        if not ok:
            raise RuntimeError(reason)
        import mlx_whisper

        start = time.perf_counter()
        result = await asyncio.to_thread(
            mlx_whisper.transcribe, audio, path_or_hf_repo=self.model, language=None, fp16=True
        )
        return {"text": str(result.get("text", "")).strip(), "language": result.get("language"),
                "ms": round((time.perf_counter() - start) * 1000)}
