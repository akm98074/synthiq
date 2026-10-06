"""Minimal async client for the Ollama HTTP API."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = await self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise OllamaError(f"Ollama {path} failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    async def _get(self, path: str) -> dict:
        try:
            resp = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise OllamaError(f"Ollama {path} failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    async def version(self) -> str:
        return (await self._get("/api/version")).get("version", "unknown")

    async def tags(self) -> list[dict]:
        return (await self._get("/api/tags")).get("models", [])

    async def ps(self) -> list[dict]:
        return (await self._get("/api/ps")).get("models", [])

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        data = await self._post("/api/embed", {"model": model, "input": inputs})
        return data.get("embeddings", [])

    async def chat_json(
        self,
        model: str,
        messages: list[dict],
        schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        """Single non-streaming chat call whose output is constrained to `schema`."""
        data = await self._post(
            "/api/chat",
            {
                "model": model,
                "messages": messages,
                "format": schema,
                "stream": False,
                "think": False,
                "options": {"temperature": temperature},
            },
        )
        content = strip_think(data.get("message", {}).get("content", ""))
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Model returned invalid JSON: {content[:200]}") from exc

    async def chat_text(self, model: str, messages: list[dict], temperature: float = 0.4) -> str:
        """One non-streaming chat turn returning plain text."""
        data = await self._post(
            "/api/chat",
            {"model": model, "messages": messages, "stream": False, "think": False,
             "options": {"temperature": temperature}},
        )
        return strip_think(data.get("message", {}).get("content", ""))

    async def chat_tools(
        self, model: str, messages: list[dict], tools: list[dict], temperature: float = 0.2
    ) -> dict:
        """One non-streaming chat turn with native tool calling. Returns the message dict."""
        data = await self._post(
            "/api/chat",
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "think": False,
                "options": {"temperature": temperature},
            },
        )
        return data.get("message", {})

    async def chat_stream(
        self, model: str, messages: list[dict], temperature: float = 0.6
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": {"temperature": temperature},
        }
        filt = ThinkFilter()
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise OllamaError(
                        f"Ollama chat failed ({resp.status_code}): {body[:300]!r}"
                    )
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise OllamaError(chunk["error"])
                    piece = chunk.get("message", {}).get("content", "")
                    out = filt.feed(piece)
                    if out:
                        yield out
                    if chunk.get("done"):
                        break
                rest = filt.flush() + filt.tail()
                if rest:
                    yield rest
        except httpx.HTTPError as exc:
            raise OllamaError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc

    async def unload(self, model: str) -> None:
        await self._post("/api/generate", {"model": model, "keep_alive": 0})

    async def pull(self, model: str) -> AsyncIterator[dict]:
        try:
            async with self._client.stream(
                "POST", "/api/pull", json={"model": model, "stream": True}, timeout=None
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise OllamaError(f"Pull failed ({resp.status_code}): {body[:300]!r}")
                async for line in resp.aiter_lines():
                    if line.strip():
                        event = json.loads(line)
                        if event.get("error"):
                            raise OllamaError(event["error"])
                        yield event
        except httpx.HTTPError as exc:
            raise OllamaError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc


def strip_think(text: str) -> str:
    """Remove <think>...</think> blocks some reasoning models emit.

    Qwen3 sometimes emits reasoning that ends with </think> but has no opening tag;
    in that case everything up to the last orphan </think> is reasoning.
    """
    if "</think>" in text and "<think>" not in text.split("</think>")[0]:
        text = text.rsplit("</think>", 1)[1]
    while "<think>" in text:
        start = text.index("<think>")
        end = text.find("</think>", start)
        if end == -1:
            text = text[:start]
            break
        text = text[:start] + text[end + len("</think>"):]
    return text.strip()


RESET = "\x00RESET\x00"   # emitted when already-streamed text turns out to be reasoning


class ThinkFilter:
    """Streaming filter that drops reasoning text.

    Handles <think>...</think> spans across chunk boundaries, and also an orphan
    </think> near the start (reasoning without an opening tag): the first
    HOLD_CHARS characters are buffered until it's clear which case applies.
    """

    HOLD_CHARS = 240

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self._head = ""        # buffered start of the stream
        self._head_done = False

    def feed(self, piece: str) -> str:
        if not self._head_done:
            self._head += piece
            if "</think>" in self._head:
                before, _, after = self._head.rpartition("</think>")
                if "<think>" not in before:
                    self._head_done = True
                    return self._feed(after.lstrip("\n"))
            if "<think>" in self._head or len(self._head) >= self.HOLD_CHARS:
                self._head_done = True
                return self._feed(self._head)
            return ""
        return self._feed(piece)

    def flush(self) -> str:
        """Call at end of stream: releases a short buffered head that had no reasoning."""
        if not self._head_done:
            self._head_done = True
            return self._feed(self._head)
        return ""

    def _feed(self, piece: str) -> str:
        self._buf += piece
        out: list[str] = []
        while self._buf:
            if self._inside:
                end = self._buf.find("</think>")
                if end == -1:
                    # keep a tail in case the closing tag is split
                    self._buf = self._buf[-8:]
                    return "".join(out)
                self._buf = self._buf[end + len("</think>"):].lstrip("\n")
                self._inside = False
            else:
                start = self._buf.find("<think>")
                close = self._buf.find("</think>")
                if close != -1 and (start == -1 or close < start):
                    # Orphan </think> after text was already released: that text was
                    # reasoning. Tell the consumer to discard what it showed so far.
                    self._buf = self._buf[close + len("</think>"):].lstrip("\n")
                    out = [RESET]
                    continue
                if start == -1:
                    # hold back a possible partial "<think" / "</think" prefix
                    safe = len(self._buf)
                    for i in range(1, min(8, len(self._buf)) + 1):
                        tail = self._buf[-i:]
                        if "<think>".startswith(tail) or "</think>".startswith(tail):
                            safe = len(self._buf) - i
                            break
                    out.append(self._buf[:safe])
                    self._buf = self._buf[safe:]
                    return "".join(out)
                out.append(self._buf[:start])
                self._buf = self._buf[start + len("<think>"):]
                self._inside = True
        return "".join(out)

    def tail(self) -> str:
        """Anything held back at the very end (a partial-tag lookalike)."""
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest


def model_present(name: str, installed: list[dict[str, Any]]) -> bool:
    """Ollama tags omit ':latest' in requests but include it in listings."""
    want = name if ":" in name else f"{name}:latest"
    return any(m.get("name") in (name, want) or m.get("model") in (name, want) for m in installed)
