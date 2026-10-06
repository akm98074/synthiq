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
