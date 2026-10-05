"""HTTP API and static UI, bound to localhost only."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .agent.chat import handle_turn, resume_after_decision
from .policy.engine import ApprovalError
from .tools.base import ToolError
from .tools.registry import TEST_CALLS
from .voice.stt import AudioError, read_wav
from .config import Settings, data_dir, load_settings
from .decide.questions import BY_NAME
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


class SnoozeIn(BaseModel):
    hours: float = 1.0


class SpeakIn(BaseModel):
    text: str


class DecisionIn(BaseModel):
    approve: bool
    scope: str = "once"


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _warm_up(rt: Runtime) -> None:
    """Embed seed examples and any un-embedded memories so the first message is fast."""
    try:
        await rt.prototype.ensure_embeddings()
        await rt.reembed_memories()
    except Exception as exc:  # noqa: BLE001 - Ollama may simply not be running yet
        log.info("Warm-up skipped: %s", exc)


def create_app(settings: Settings | None = None, base: Path | None = None, runner=None,
               stt=None, tts=None, scheduler: bool = True) -> FastAPI:
    base = base or data_dir()
    settings = settings or load_settings(base)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rt = Runtime(settings, base, runner=runner, stt=stt, tts=tts)
        tasks = [asyncio.create_task(_warm_up(app.state.rt))]
        if scheduler:
            tasks.append(asyncio.create_task(app.state.rt.scheduler.loop()))
        yield
        for t in tasks:
            t.cancel()
        await app.state.rt.tts.stop()
        await app.state.rt.aclose()

    app = FastAPI(title="LocalAIAgent", version=__version__, lifespan=lifespan)

    def rt(app_: FastAPI = app) -> Runtime:
        return app_.state.rt

    # ── UI ────────────────────────────────────────────────────────────────
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    @app.middleware("http")
    async def no_stale_ui(request, call_next):
        # Make browsers revalidate UI files, so an upgrade never pairs a new page
        # with an old cached script.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/ui/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        html = (UI_DIR / "index.html").read_text()
        for asset in ("/ui/app.js", "/ui/voice.js", "/ui/app.css"):
            html = html.replace(f'"{asset}"', f'"{asset}?v={__version__}"')
        return HTMLResponse(html)

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
                for q in BY_NAME.values()]

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

    # ── connectors and tools ──────────────────────────────────────────────
    @app.get("/api/connectors")
    async def connectors() -> list[dict]:
        return rt().connectors()

    @app.post("/api/connectors/{connector_id}/test")
    async def test_connector(connector_id: str) -> dict:
        r = rt()
        call = TEST_CALLS.get(connector_id)
        if call is None:
            raise HTTPException(404, "Nothing to test for this connector")
        name, args = call
        tool = r.tools.get(name)
        if tool is None:
            raise HTTPException(400, "Connector is disabled or unavailable on this computer")
        try:
            result = await tool.run(args)
        except ToolError as exc:
            r.audit.append("connector_test", name, tool.tier, args, "error", str(exc))
            return {"ok": False, "message": str(exc)}
        r.audit.append("connector_test", name, tool.tier, args, "ok", result.display)
        return {"ok": True, "message": result.display}

    @app.get("/api/tools")
    async def tools() -> list[dict]:
        return [{"name": t.name, "connector": t.connector, "tier": t.tier,
                 "description": t.description, "intents": list(t.intents)} for t in rt().tools.values()]

    # ── approvals, grants, audit ──────────────────────────────────────────
    @app.get("/api/approvals")
    async def approvals(status: str | None = None, limit: int = 100) -> list[dict]:
        return rt().policy.list(status, limit)

    @app.post("/api/approvals/{approval_id}/decide")
    async def decide_approval(approval_id: int, body: DecisionIn) -> StreamingResponse:
        r = rt()
        try:
            ap = r.policy.decide(approval_id, body.approve, body.scope)
        except KeyError as exc:
            raise HTTPException(404, "Approval not found") from exc
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc
        r.audit.append("approval_" + ap["status"], ap["tool"], ap["tier"], ap["args"],
                       ap["status"], f"scope={ap['scope']}" if ap["scope"] else None,
                       ap["id"], ap["task_id"])

        async def stream():
            yield sse({"type": "approval_decided", "approval": {k: v for k, v in ap.items() if k != "state"}})
            try:
                async for event in resume_after_decision(r, ap, body.approve):
                    yield sse(event)
            except Exception as exc:  # noqa: BLE001
                log.exception("resume failed")
                yield sse({"type": "error", "message": f"{exc.__class__.__name__}: {exc}"})
                yield sse({"type": "done", "message_id": None, "model": None})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/grants")
    async def grants() -> list[dict]:
        return rt().policy.active_grants()

    @app.delete("/api/grants/{grant_id}")
    async def revoke_grant(grant_id: int) -> dict:
        r = rt()
        if not r.policy.revoke(grant_id):
            raise HTTPException(404, "Grant not found")
        r.audit.append("grant_revoked", detail=f"grant {grant_id}")
        return {"ok": True}

    @app.get("/api/audit")
    async def audit(limit: int = 200) -> list[dict]:
        return rt().audit.list(limit)

    @app.get("/api/audit/verify")
    async def audit_verify() -> dict:
        return rt().audit.verify()

    # ── proactivity: nudges and jobs ──────────────────────────────────────
    @app.get("/api/nudges")
    async def nudges(include_done: bool = False, limit: int = 100) -> dict:
        n = rt().nudges
        return {"items": n.list(include_done, limit), "new": n.count_new()}

    @app.post("/api/nudges/{nudge_id}/dismiss")
    async def dismiss_nudge(nudge_id: int) -> dict:
        if not rt().nudges.dismiss(nudge_id):
            raise HTTPException(404, "Nudge not found")
        return {"ok": True}

    @app.post("/api/nudges/{nudge_id}/snooze")
    async def snooze_nudge(nudge_id: int, body: SnoozeIn) -> dict:
        if not rt().nudges.snooze(nudge_id, body.hours):
            raise HTTPException(404, "Nudge not found")
        return {"ok": True}

    @app.get("/api/jobs")
    async def jobs() -> dict:
        r = rt()
        return {"enabled": r.scheduler.enabled, "jobs": r.scheduler.jobs()}

    @app.post("/api/jobs/{name}/run")
    async def run_job(name: str) -> dict:
        try:
            result = await rt().scheduler.run(name, manual=True)
        except KeyError as exc:
            raise HTTPException(404, "Unknown job") from exc
        except OllamaError as exc:
            raise HTTPException(503, str(exc)) from exc
        return result

    # ── voice ─────────────────────────────────────────────────────────────
    @app.get("/api/voice/status")
    async def voice_status() -> dict:
        r = rt()
        stt_ok, reason = r.stt.status()
        return {
            "enabled": r.settings.voice_enabled,
            "stt": {"available": stt_ok, "reason": reason, "engine": r.stt.name,
                    "model": getattr(r.stt, "model", None)},
            "tts": {"available": r.tts.available(), "engine": r.tts.name,
                    "voices": await r.tts.voices(), "speaking": r.tts.speaking},
            "speak_replies": r.settings.speak_replies,
        }

    @app.post("/api/voice/transcribe")
    async def transcribe(request: Request) -> dict:
        r = rt()
        data = await request.body()
        if not data:
            raise HTTPException(400, "No audio received")
        try:
            audio = read_wav(data)
        except AudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        seconds = round(len(audio) / 16000, 2)
        if seconds < 0.3:
            return {"text": "", "seconds": seconds, "ms": 0}
        try:
            result = await r.stt.transcribe(audio)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {**result, "seconds": seconds}

    @app.post("/api/voice/speak")
    async def speak(body: SpeakIn) -> dict:
        r = rt()
        if not r.tts.available():
            raise HTTPException(503, "Speech output needs macOS (the 'say' command).")
        finished = await r.tts.speak(body.text)
        return {"ok": True, "finished": finished}

    @app.post("/api/voice/stop")
    async def stop_speaking() -> dict:
        return {"stopped": await rt().tts.stop()}

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
