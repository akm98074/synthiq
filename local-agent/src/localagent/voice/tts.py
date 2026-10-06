"""Text to speech with the built-in macOS `say` command (on-device, no download)."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile


def speakable(text: str, limit: int = 1500) -> str:
    """Strip markdown and symbols that sound bad when read aloud."""
    t = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"[*_~>|]+", "", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"\s+\n", "\n", t).strip()
    return t[:limit]


class SayTTS:
    name = "macOS say"

    def __init__(self, voice: str = "", rate: int = 190):
        self.voice = voice
        self.rate = rate
        self._proc: asyncio.subprocess.Process | None = None
        self._voices: list[str] | None = None

    @staticmethod
    def available() -> bool:
        return shutil.which("say") is not None

    async def voices(self) -> list[str]:
        if self._voices is None:
            if not self.available():
                self._voices = []
            else:
                proc = await asyncio.create_subprocess_exec(
                    "say", "-v", "?", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                out, _ = await proc.communicate()
                names = []
                for line in out.decode(errors="replace").splitlines():
                    m = re.match(r"^(.+?)\s{2,}([a-z]{2}[_-][A-Z]{2})", line)
                    if m and m.group(2).startswith("en"):
                        names.append(m.group(1).strip())
                self._voices = names
        return self._voices

    def command(self, path: str) -> list[str]:
        # Text is passed via a file (-f) so nothing in it can be read as an option.
        cmd = ["say", "-r", str(self.rate)]
        if self.voice:
            cmd += ["-v", self.voice]
        return cmd + ["-f", path]

    async def speak(self, text: str) -> bool:
        """Speak and wait until finished (or stopped). Returns False if interrupted."""
        await self.stop()
        text = speakable(text)
        if not text or not self.available():
            return False
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.command(f.name), stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            code = await self._proc.wait()
        finally:
            self._proc = None
            os.unlink(f.name)
        return code == 0

    async def synthesize(self, text: str) -> bytes:
        """The spoken reply as WAV bytes (for playback in the browser, e.g. the avatar)."""
        text = speakable(text)
        if not text or not self.available():
            return b""
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
        out = f.name[:-4] + ".wav"
        cmd = ["say", "-r", str(self.rate)] + (["-v", self.voice] if self.voice else []) + [
            "-o", out, "--file-format=WAVE", "--data-format=LEI16@22050", "-f", f.name]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"say failed: {err.decode(errors='replace')[:200]}")
            with open(out, "rb") as w:
                return w.read()
        finally:
            for p in (f.name, out):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    async def stop(self) -> bool:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except asyncio.TimeoutError:
                proc.kill()
            return True
        return False

    @property
    def speaking(self) -> bool:
        return self._proc is not None and self._proc.returncode is None


class Pyttsx3TTS:
    """Speech output on Windows (SAPI voices) and Linux (eSpeak) via pyttsx3."""
    name = "pyttsx3"

    def __init__(self, voice: str = "", rate: int = 190):
        self.voice, self.rate = voice, rate
        self._engine = None
        self._speaking = False

    @staticmethod
    def available() -> bool:
        try:
            import pyttsx3  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def _make(self):
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", self.rate)
        if self.voice:
            for v in engine.getProperty("voices"):
                if v.name == self.voice:
                    engine.setProperty("voice", v.id)
        return engine

    async def voices(self) -> list[str]:
        if not self.available():
            return []
        return await asyncio.to_thread(lambda: [v.name for v in self._make().getProperty("voices")])

    async def speak(self, text: str) -> bool:
        text = speakable(text)
        if not text or not self.available():
            return False

        def run() -> None:
            self._engine = self._make()
            self._engine.say(text)
            self._engine.runAndWait()

        self._speaking = True
        try:
            await asyncio.to_thread(run)
        finally:
            self._speaking, self._engine = False, None
        return True

    async def synthesize(self, text: str) -> bytes:
        text = speakable(text)
        if not text or not self.available():
            return b""
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        def run() -> None:
            engine = self._make()
            engine.save_to_file(text, path)
            engine.runAndWait()

        try:
            await asyncio.to_thread(run)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.unlink(path)

    async def stop(self) -> bool:
        if self._engine is not None:
            self._engine.stop()
            return True
        return False

    @property
    def speaking(self) -> bool:
        return self._speaking


def make_tts(voice: str, rate: int):
    """macOS `say` when present, otherwise pyttsx3 (Windows SAPI / Linux eSpeak)."""
    return SayTTS(voice, rate) if SayTTS.available() else Pyttsx3TTS(voice, rate)
