"""HTTP API and static UI, bound to localhost only."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .agent.chat import handle_turn
from .config import Settings, data_dir, load_settings
from .decide.questions import STANDARD
from .doctor import run_checks
from .llm import models as model_mgr
from .llm.ollama import OllamaError
from .runtime import Runtime

log = logging.getLogger("localagent")

UI_DIR = Path(str(resources.files("localagent").joinpath("ui")))


class ChatIn(BaseModel):
    text: str


class CorrectionIn(BaseModel):
    question: str
    label: str


class MemoryIn(BaseModel):
    text: str
    kind: str = "fact"


class MemoryPatch(BaseModel):
    text: str | None = None
    kind: str | None = None


class ModelIn(BaseModel):
    model: str


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _warm_up(rt: Runtime) -> None:
    """Embed seed examples and any un-embedded memories so the first message is fast."""
    try:
        await rt.prototype.ensure_embeddings()
        await rt.reembed_memories()
    except Exception as exc:  # noqa: BLE001 - Ollama may simply not be running yet
        log.info("Warm-up skipped: %s", exc)


def create_app(settings: Settings | None = None, base: Path | None = None) -> FastAPI:
    base = base or data_dir()
    settings = settings or load_settings(base)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rt = Runtime(settings, base)
        warm = asyncio.create_task(_warm_up(app.state.rt))
        yield
        warm.cancel()
        await app.state.rt.aclose()

    app = FastAPI(title="LocalAIAgent", version=__version__, lifespan=lifespan)

    def rt(app_: FastAPI = app) -> Runtime:
        return app_.state.rt

    # ── UI ────────────────────────────────────────────────────────────────
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    # ── meta ──────────────────────────────────────────────────────────────
    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/doctor")
    async def doctor() -> list[dict]:
        return await run_checks(rt().settings, rt().base)

    @app.get("/api/questions")
    async def questions() -> list[dict]:
        return [{"name": q.name, "kind": q.kind, "prompt": q.prompt, "options": q.options}
                for q in STANDARD]

    # ── chat ──────────────────────────────────────────────────────────────
    @app.post("/api/chat")
    async def chat(body: ChatIn) -> StreamingResponse:
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "Empty message")

        async def stream():
            try:
                async for event in handle_turn(rt(), text):
                    yield sse(event)
            except Exception as exc:  # noqa: BLE001 - surface to the UI
                log.exception("chat turn failed")
                yield sse({"type": "error", "message": f"{exc.__class__.__name__}: {exc}"})
                yield sse({"type": "done", "message_id": None, "model": None})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/messages")
    async def messages(limit: int = 100) -> list[dict]:
        store = rt().store
        out = store.recent_messages(limit)
        for m in out:
            if m["role"] == "user" and m["decision_id"]:
                m["decision"] = store.get_decision(m["decision_id"])
        return out

    @app.delete("/api/messages")
    async def clear_messages() -> dict:
        rt().store.clear_messages()
        return {"ok": True}

    # ── decisions ─────────────────────────────────────────────────────────
    @app.post("/api/decide")
    async def decide(body: ChatIn) -> dict:
        try:
            d = await rt().router.decide(body.text, log_it=False)
        except OllamaError as exc:
            raise HTTPException(503, str(exc)) from exc
        return d.to_dict()

    @app.get("/api/decisions")
    async def decisions(limit: int = 100) -> list[dict]:
        return rt().store.list_decisions(limit)

    @app.post("/api/decisions/{decision_id}/correct")
    async def correct(decision_id: int, body: CorrectionIn) -> dict:
        try:
            await rt().router.correct(decision_id, body.question, body.label)
        except KeyError as exc:
            raise HTTPException(404, "Decision not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OllamaError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"ok": True, "user_examples": rt().store.count_examples("user")}

    # ── memory ────────────────────────────────────────────────────────────
    @app.get("/api/memories")
    async def memories() -> list[dict]:
        return [m.to_dict() for m in rt().store.list_memories()]

    @app.post("/api/memories")
    async def add_memory(body: MemoryIn) -> dict:
        r = rt()
        try:
            vec = (await r.embed([body.text]))[0]
        except OllamaError:
            vec = None  # stored now, embedded later by reembed_memories
        mem_id = r.store.add_memory(body.text.strip(), body.kind, vec,
                                    r.settings.embed_model if vec else None)
        r.write_identity()
        return r.store.get_memory(mem_id).to_dict()

    @app.patch("/api/memories/{memory_id}")
    async def edit_memory(memory_id: int, body: MemoryPatch) -> dict:
        r = rt()
        vec = None
        if body.text:
            try:
                vec = (await r.embed([body.text]))[0]
            except OllamaError:
                vec = None
        ok = r.store.update_memory(memory_id, text=body.text, kind=body.kind, embedding=vec,
                                   embed_model=r.settings.embed_model if vec else None)
        if not ok:
            raise HTTPException(404, "Memory not found")
        r.write_identity()
        return r.store.get_memory(memory_id).to_dict()

    @app.delete("/api/memories/{memory_id}")
    async def forget(memory_id: int) -> dict:
        r = rt()
        if not r.store.delete_memory(memory_id):
            raise HTTPException(404, "Memory not found")
        r.write_identity()
        return {"ok": True}

    @app.get("/api/identity", response_class=PlainTextResponse)
    async def get_identity() -> str:
        return rt().write_identity()

    # ── models ────────────────────────────────────────────────────────────
    @app.get("/api/models")
    async def models() -> dict:
        return await model_mgr.status(rt().ollama, rt().settings)

    @app.post("/api/models/unload")
    async def unload(body: ModelIn) -> dict:
        try:
            await rt().ollama.unload(body.model)
        except OllamaError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"ok": True}

    @app.post("/api/models/pull")
    async def pull(body: ModelIn) -> StreamingResponse:
        async def stream():
            try:
                async for ev in rt().ollama.pull(body.model):
                    yield sse(ev)
                yield sse({"status": "done"})
            except OllamaError as exc:
                yield sse({"status": "error", "error": str(exc)})
        return StreamingResponse(stream(), media_type="text/event-stream")

    # ── settings ──────────────────────────────────────────────────────────
    @app.get("/api/settings")
    async def get_settings() -> dict:
        return rt().settings.to_dict()

    @app.put("/api/settings")
    async def put_settings(values: dict) -> dict:
        try:
            s = await rt().apply_settings(values)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return s.to_dict()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="LocalAIAgent server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    import uvicorn

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
