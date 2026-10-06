"""A stand-in for the Messages API's streaming endpoint, for tests."""
from __future__ import annotations

import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def create_app(state: dict) -> FastAPI:
    app = FastAPI()
    state.update(requests=[], reply=["The answer ", "is 42."], status=200, stop="end_turn")

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        state["requests"].append({"body": body, "headers": dict(request.headers)})
        if request.headers.get("x-api-key") != "sk-ant-test":
            return JSONResponse({"type": "error", "error": {"type": "authentication_error",
                                                           "message": "invalid x-api-key"}}, status_code=401)
        if state["status"] != 200:
            return JSONResponse({"type": "error", "error": {"type": "overloaded_error", "message": "busy"}},
                                status_code=state["status"])

        def gen():
            yield sse("message_start", {"type": "message_start", "message": {
                "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "content": [],
                "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}})
            yield sse("content_block_start", {"type": "content_block_start", "index": 0,
                                              "content_block": {"type": "text", "text": ""}})
            for piece in state["reply"]:
                yield sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                  "delta": {"type": "text_delta", "text": piece}})
            yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": state["stop"],
                                                                           "stop_sequence": None},
                                        "usage": {"output_tokens": 5}})
            yield sse("message_stop", {"type": "message_stop"})

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


class FakeAnthropic:
    def __init__(self):
        self.state: dict = {}
        self.app = create_app(self.state)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)
