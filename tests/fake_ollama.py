"""A deterministic stand-in for the Ollama HTTP API, for tests and demos.

Embeddings are hashed bag-of-words vectors, so similar sentences really are
close and the prototype classifier behaves sensibly. Chat replies are canned.

Run standalone:  python tests/fake_ollama.py --port 11434
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import socket
import threading
import time

import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

DIM = 384
INSTALLED = ["qwen3:4b", "qwen3:1.7b", "all-minilm:latest"]
STOP = {"the", "a", "an", "to", "my", "me", "i", "is", "of", "for", "and", "on", "in", "at", "it", "this", "that", "you"}


def embed_text(text: str) -> list[float]:
    vec = np.zeros(DIM, dtype=np.float32)
    tokens = [t for t in re.findall(r"[a-z']+", text.lower()) if t not in STOP]
    for tok in tokens:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
        vec[(h // DIM) % DIM] += 0.5
    if not tokens:
        vec[0] = 1.0
    return (vec / np.linalg.norm(vec)).tolist()


def judge(text: str, schema: dict) -> dict:
    t = text.lower()
    if any(w in t for w in ("remind", "calendar", "schedule")):
        intent = "schedule"
    elif "know about me" in t or "remember my" in t or t.startswith("what's my"):
        intent = "memory_query"
    elif t.startswith(("i'm", "i am", "my ", "remember", "i prefer", "i like")):
        intent = "memory_write"
    elif any(w in t for w in ("open", "delete", "send", "book", "trash", "move", "downloads")):
        intent = "computer_action"
    elif any(w in t for w in ("write", "draft", "plan", "make")):
        intent = "task"
    elif "?" in t:
        intent = "quick_answer"
    else:
        intent = "chit_chat"
    out = {}
    for name, spec in schema.get("properties", {}).items():
        enum = spec.get("enum", [])
        if name == "intent":
            out[name] = intent
        elif name == "needs_memory_write":
            out[name] = "yes" if intent == "memory_write" else "no"
        elif enum:
            out[name] = enum[min(1, len(enum) - 1)]
    return out


def pick_tool(text: str, tool_names: set[str]):
    """Very small rule-based stand-in for a tool-calling model."""
    t = text.lower()
    words = text.split()
    rules = [
        ("trash", "files_trash", lambda: {"paths": [w for w in words if "." in w][-1:]}),
        ("move", "files_move", lambda: {"paths": [w for w in words if "." in w][:1], "destination": "Downloads/Archive"}),
        ("pdf", "documents_create_pdf", lambda: {"title": "Packing list", "content": "# Packing\n- socks\n- “passport”"}),
        ("spreadsheet", "documents_create_spreadsheet", lambda: {"title": "Budget", "csv": "item,cost\nrent,1200\nfood,300.5"}),
        ("send", "mail_send", lambda: {"to": "sam@example.com", "subject": "Hi", "body": "Hello"}),
        ("draft", "mail_draft", lambda: {"to": "sam@example.com", "subject": "Hi", "body": "Hello"}),
        ("remind", "reminders_create", lambda: {"title": "call mom", "due": "2030-01-01T18:00"}),
        ("calendar", "calendar_list_events", lambda: {"start": "2030-01-01", "end": "2030-01-02"}),
        ("downloads", "files_list", lambda: {"folder": "Downloads"}),
    ]
    for kw, name, args in rules:
        if kw in t and name in tool_names:
            return name, args()
    return None


def create_fake_app() -> FastAPI:
    app = FastAPI()
    app.state.loaded = set()
    app.state.calls = []

    @app.get("/api/version")
    async def version():
        return {"version": "0.0.0-fake"}

    @app.get("/api/tags")
    async def tags():
        return {"models": [{"name": n, "model": n, "size": 1_000_000_000} for n in INSTALLED]}

    @app.get("/api/ps")
    async def ps():
        return {"models": [{"name": n, "size": 2_000_000_000, "size_vram": 2_000_000_000}
                           for n in sorted(app.state.loaded)]}

    @app.post("/api/embed")
    async def embed(req: Request):
        body = await req.json()
        inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
        app.state.calls.append(("embed", len(inputs)))
        return {"model": body["model"], "embeddings": [embed_text(t) for t in inputs]}

    @app.post("/api/generate")
    async def generate(req: Request):
        body = await req.json()
        if body.get("keep_alive") == 0:
            name = body["model"] if ":" in body["model"] else body["model"] + ":latest"
            app.state.loaded.discard(name)
            app.state.loaded.discard(body["model"])
        return {"done": True}

    @app.post("/api/pull")
    async def pull(req: Request):
        body = await req.json()

        async def gen():
            for i in (0, 50, 100):
                yield json.dumps({"status": "downloading", "total": 100, "completed": i}) + "\n"
            yield json.dumps({"status": "success"}) + "\n"
            if body["model"] not in INSTALLED:
                INSTALLED.append(body["model"])
        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.post("/api/chat")
    async def chat(req: Request):
        body = await req.json()
        model = body["model"]
        app.state.loaded.add(model)
        app.state.calls.append(("chat", model))
        last = body["messages"][-1]["content"]
        schema = body.get("format")
        if body.get("tools"):
            names = {tl["function"]["name"] for tl in body["tools"]}
            app.state.calls.append(("tools", sorted(names)))
            last_msg = body["messages"][-1]
            if last_msg["role"] == "tool":
                content = "Done: " + last_msg["content"].splitlines()[0]
                return {"model": model, "message": {"role": "assistant", "content": content}, "done": True}
            picked = pick_tool(last_msg["content"], names)
            if picked is None:
                return {"model": model, "message": {"role": "assistant", "content": "No tool needed."}, "done": True}
            name, args = picked
            return {"model": model, "done": True, "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}]}}
        if isinstance(schema, dict):
            props = schema.get("properties", {})
            if "facts" in props:
                msg = last.rsplit("Message:", 1)[-1].strip()
                facts = [{"text": msg, "kind": "preference" if "prefer" in msg.lower() else "fact"}] \
                    if msg.lower().startswith(("i'm", "i am", "my ", "remember", "i prefer", "i like")) else []
                content = json.dumps({"facts": facts})
            else:
                user = last.rsplit("## Latest user message", 1)[-1].split("Reply with JSON")[0].strip()
                content = json.dumps(judge(user, schema))
            return {"model": model, "message": {"role": "assistant", "content": content}, "done": True}

        system = body["messages"][0]["content"] if body["messages"][0]["role"] == "system" else ""
        recalled = [l[2:] for l in system.splitlines() if l.startswith("- (")]
        reply = f"Fake reply from {model}."
        if recalled:
            reply += " I remember: " + "; ".join(recalled)

        async def gen():
            pieces = ["<think>hidden", " reasoning</think>"] + [w + " " for w in reply.split()]
            for p in pieces:
                yield json.dumps({"message": {"role": "assistant", "content": p}, "done": False}) + "\n"
                await asyncio.sleep(0)
            yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
        if body.get("stream", True):
            return StreamingResponse(gen(), media_type="application/x-ndjson")
        return {"model": model, "message": {"role": "assistant", "content": reply}, "done": True}

    return app


class FakeOllama:
    """Runs the fake server in a background thread on a free port."""

    def __init__(self) -> None:
        self.app = create_fake_app()
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    def __enter__(self) -> "FakeOllama":
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    uvicorn.run(create_fake_app(), host="127.0.0.1", port=args.port)
