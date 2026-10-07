"""HTTP API and static UI, bound to localhost only."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, security, trust
from .agent.chat import handle_turn, resume_after_decision
from .policy.engine import ApprovalError
from .tools.base import ToolError
from .tools.registry import TEST_CALLS
from .voice.stt import AudioError, read_wav
from .config import SENSITIVE_SETTINGS, Settings, data_dir, load_settings, sensitive_changes
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


def _page(title: str, text: str) -> str:
    import html as _h

    return (f"<!doctype html><meta charset='utf-8'><title>{_h.escape(title)}</title>"
            "<body style='font:16px -apple-system,sans-serif;max-width:560px;margin:80px auto;padding:0 16px'>"
            f"<h2>{_h.escape(title)}</h2><p>{_h.escape(text)}</p></body>")


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
               stt=None, tts=None, scheduler: bool = True, eventkit=None, browser=None,
               web_fetch=None, wake_stt=None, vault=None, google=None, cloud_base_url=None,
               auth: bool = True) -> FastAPI:
    base = base or data_dir()
    settings = settings or load_settings(base)
    token = security.api_token(base)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rt = Runtime(settings, base, runner=runner, stt=stt, tts=tts, eventkit=eventkit,
                               browser=browser, web_fetch=web_fetch, wake_stt=wake_stt,
                               vault=vault, google=google, cloud_base_url=cloud_base_url)
        tasks = [asyncio.create_task(_warm_up(app.state.rt))]
        if scheduler:
            tasks.append(asyncio.create_task(app.state.rt.scheduler.loop()))
            app.state.rt._a2a_lifecycle = True
            try:
                await app.state.rt.start_a2a()
            except Exception:  # noqa: BLE001 - e.g. the port is taken; the rest of the app still runs
                log.exception("agent-to-agent listener didn't start")
            try:
                await app.state.rt.start_phone()
            except Exception:  # noqa: BLE001
                log.exception("phone listener didn't start")
            if app.state.rt.mac_available:
                tasks.append(asyncio.create_task(app.state.rt.imessage_channel.loop()))
        yield
        for t in tasks:
            t.cancel()
        await app.state.rt.tts.stop()
        await app.state.rt.aclose()

    app = FastAPI(title="LocalAIAgent", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.api_token = token
    app.state.port = settings.port

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # See security.py: Host allowlist (DNS rebinding), per-install secret, same-origin writes.
        if auth:
            h = request.headers
            denied = security.check(request.method, request.url.path, h.get("host"), h.get("origin"),
                                    request.cookies.get(security.cookie_name(settings.port)), h.get("authorization"),
                                    settings.port, token, extra_host=settings.host)
            if denied:
                status, reason = denied
                if status == 401 and request.url.path == "/":
                    return HTMLResponse(_page("Open LocalAIAgent from its app or Terminal",
                                              "For your privacy the agent only opens for you. Use the "
                                              "LocalAIAgent app, or run in Terminal:  localagent open"), 401)
                return PlainTextResponse(reason, status)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path == "/" or request.url.path.startswith("/ui/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        return response

    @app.get("/auth", include_in_schema=False)
    async def sign_in(t: str = "", next: str = "/") -> Response:
        if not security.same_secret(t, token):
            return HTMLResponse(_page("Link expired", "Open the app again with: localagent open"), 403)
        dest = next if next.startswith("/") and not next.startswith("//") else "/"
        resp = RedirectResponse(dest, 303)
        resp.set_cookie(security.cookie_name(settings.port), token, httponly=True, samesite="strict", path="/")
        return resp

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
        html = (UI_DIR / "index.html").read_text(encoding="utf-8")
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

    # ── trusted agents ────────────────────────────────────────────────────
    @app.get("/api/peers")
    async def peers_status() -> dict:
        from .connectors.peers import SCOPES

        r = rt()
        return {"enabled": r.settings.a2a_enabled, "listening": r._a2a is not None,
                "me": {**r.peers.card(), "fingerprint": r.peers.fingerprint},
                "peers": r.peers.list(), "waiting": r.peers.waiting(), "scopes": SCOPES}

    @app.post("/api/peers/invite")
    async def peers_invite() -> dict:
        r = rt()
        if not r.settings.a2a_enabled:
            raise HTTPException(409, "Turn on Trusted agents first.")
        return {"code": r.peers.invite(), "addr": r.peers.address()}

    @app.post("/api/peers/accept")
    async def peers_accept(body: dict) -> dict:
        r = rt()
        if not r.settings.a2a_enabled:
            raise HTTPException(409, "Turn on Trusted agents first.")
        try:
            peer = await r.peers.accept(str(body.get("code", "")))
        except ToolError as exc:
            raise HTTPException(400, str(exc)) from exc
        r.build_tools()
        return peer

    @app.put("/api/peers/{peer_id}")
    async def peers_scopes(peer_id: int, body: dict) -> dict:
        r = rt()
        if r.peers.get(peer_id) is None:
            raise HTTPException(404, "Not found")
        return r.peers.set_scopes(peer_id, list(body.get("scopes", [])))

    @app.post("/api/peers/{peer_id}/verify")
    async def peers_verify(peer_id: int) -> dict:
        peer = rt().peers.verify(peer_id)
        if peer is None:
            raise HTTPException(404, "Not found")
        return peer

    @app.delete("/api/peers/{peer_id}")
    async def peers_remove(peer_id: int) -> dict:
        r = rt()
        ok = r.peers.remove(peer_id)
        r.audit.append("peer_removed", "peers", outcome="ok" if ok else "missing", detail=str(peer_id))
        return {"ok": ok}

    @app.post("/api/peers/inbox/{inbox_id}/reply")
    async def peers_reply(inbox_id: int, body: dict) -> dict:
        r = rt()
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(400, "Write a reply first.")
        try:
            return await r.peers.reply(inbox_id, text)
        except ToolError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ── phone line ────────────────────────────────────────────────────────
    @app.get("/api/phone")
    async def phone_status() -> dict:
        from .channels.phone import TOKEN

        r = rt()
        s_ = r.settings
        from .channels.phone import PIN

        return {"enabled": s_.phone_enabled, "has_token": r.vault.has(TOKEN), "has_pin": r.vault.has(PIN),
                "listening": getattr(r, "_phone", None) is not None, "port": s_.phone_port,
                "webhook": (s_.phone_public_url.rstrip("/") + "/twilio/voice") if s_.phone_public_url else "",
                "owners": [n.strip() for n in s_.phone_owner_numbers.split(",") if n.strip()]}

    @app.put("/api/phone/token")
    async def phone_token(body: dict) -> dict:
        from .channels.phone import TOKEN

        r = rt()
        token = str(body.get("token", "")).strip()
        if token and (len(token) != 32 or not all(ch in "0123456789abcdef" for ch in token.lower())):
            raise HTTPException(400, "A Twilio auth token is 32 letters and digits (Twilio console → Account info).")
        if token:
            r.vault.set(TOKEN, token)
        else:
            r.vault.delete(TOKEN)
        r.audit.append("phone_token_" + ("set" if token else "removed"), "phone", outcome="ok")
        return await phone_status()

    @app.put("/api/phone/pin")
    async def phone_pin(body: dict) -> dict:
        from .channels.phone import PIN, valid_pin

        r = rt()
        pin = str(body.get("pin", "")).strip()
        if not valid_pin(pin):
            raise HTTPException(400, "The PIN must be 4 to 8 digits.")
        r.vault.set(PIN, pin)
        r.audit.append("phone_pin_set", "phone", outcome="ok")
        return await phone_status()

    # ── cloud key ─────────────────────────────────────────────────────────
    @app.get("/api/cloud")
    async def cloud_status() -> dict:
        from .agent.cloud import KEY

        r = rt()
        try:
            import anthropic  # noqa: F401
            installed = True
        except ImportError:
            installed = False
        return {"enabled": r.settings.cloud_enabled, "has_key": r.vault.has(KEY), "model": r.settings.cloud_model,
                "installed": installed, "vault": r.vault.backend}

    @app.put("/api/cloud/key")
    async def cloud_key(body: dict) -> dict:
        from .agent.cloud import KEY

        r = rt()
        key = str(body.get("key", "")).strip()
        if not key:
            r.vault.delete(KEY)
        elif not key.startswith("sk-ant-"):
            raise HTTPException(400, "That doesn't look like an Anthropic API key (it starts with sk-ant-).")
        else:
            r.vault.set(KEY, key)
        r.audit.append("cloud_key_" + ("set" if key else "removed"), "cloud", outcome="ok")
        return await cloud_status()

    # ── Gmail sign-in ─────────────────────────────────────────────────────
    @app.get("/api/gmail")
    async def gmail_status() -> dict:
        from .connectors.gmail import CLIENT_SECRET

        r = rt()
        return {"connected": r.gmail.connected(), "account": r.settings.gmail_account,
                "client_id": r.settings.gmail_client_id, "has_secret": r.vault.has(CLIENT_SECRET),
                "vault": r.vault.backend}

    @app.put("/api/gmail/client")
    async def gmail_client(body: dict) -> dict:
        from .connectors.gmail import CLIENT_SECRET

        r = rt()
        client_id = str(body.get("client_id", "")).strip()
        if not client_id.endswith(".apps.googleusercontent.com"):
            raise HTTPException(400, "That doesn't look like a Google OAuth client ID "
                                     "(it ends with .apps.googleusercontent.com).")
        if body.get("client_secret"):
            r.vault.set(CLIENT_SECRET, str(body["client_secret"]).strip())
        await r.apply_settings({"gmail_client_id": client_id})
        return await gmail_status()

    @app.get("/api/gmail/login")
    async def gmail_login(request: Request):
        r = rt()
        redirect = str(request.base_url).rstrip("/") + "/api/gmail/callback"
        try:
            url = r.gmail_auth.auth_url(redirect)
        except ToolError as exc:
            return HTMLResponse(_page("Gmail", str(exc)), status_code=400)
        return RedirectResponse(url)

    @app.get("/api/gmail/callback")
    async def gmail_callback(code: str = "", state: str = "", error: str = ""):
        r = rt()
        if error:
            return HTMLResponse(_page("Gmail not connected", f"Google said: {error}. You can close this tab."))
        try:
            account = await r.gmail_auth.finish(code, state)
        except ToolError as exc:
            return HTMLResponse(_page("Gmail not connected", str(exc)), status_code=400)
        await r.apply_settings({"gmail_account": account})
        r.audit.append("gmail_connected", "gmail", outcome="ok", detail=account)
        return HTMLResponse(_page("Gmail connected", f"Connected as {account}. You can close this tab and go back "
                                                     "to the agent."))

    @app.post("/api/gmail/disconnect")
    async def gmail_disconnect() -> dict:
        from .connectors.gmail import REFRESH

        r = rt()
        r.vault.delete(REFRESH)
        await r.apply_settings({"gmail_account": ""})
        r.audit.append("gmail_disconnected", "gmail", outcome="ok")
        return await gmail_status()

    @app.get("/api/channels")
    async def channels() -> dict:
        r = rt()
        ch = r.imessage_channel
        s = r.settings
        return {"imessage": {"enabled": s.enable_imessage_channel, "mode": s.imessage_channel_mode,
                             "owners": [h.strip() for h in s.imessage_owner_handles.split(",") if h.strip()],
                             "status": ch.status if s.enable_imessage_channel else "off",
                             "error": ch.last_error, "available": r.mac_available}}

    @app.post("/api/channels/imessage/test")
    async def channel_test() -> dict:
        r = rt()
        owners = [h.strip() for h in r.settings.imessage_owner_handles.split(",") if h.strip()]
        if not owners:
            raise HTTPException(400, "Add your phone number or Apple ID email first.")
        try:
            await r.imessage_channel.forward_test(owners[0])
        except ToolError as exc:
            return {"ok": False, "message": str(exc)}
        r.audit.append("channel_test", "imessage", outcome="ok", detail=f"to {owners[0]}")
        return {"ok": True, "message": f"Sent a test message to {owners[0]}."}

    @app.get("/api/screen")
    async def screen_status() -> dict:
        r = rt()
        return {"enabled": r.settings.screen_context_enabled, "kept": r.screen.count(),
                "permission": r.screen.permission() if r.mac_available else None,
                "retention_minutes": r.settings.screen_retention_minutes}

    @app.delete("/api/screen")
    async def screen_forget() -> dict:
        r = rt()
        n = r.screen.forget_all()
        r.audit.append("screen_forgotten", outcome="ok", detail=f"{n} snapshot(s)")
        return {"deleted": n}

    @app.get("/api/skills")
    async def skills() -> dict:
        from .skills import sandbox_available, skill_status

        return {"folder": str(rt().skills_dir), "sandbox": sandbox_available(),
                "skills": skill_status(rt().skills_dir)}

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
            "avatar": r.settings.avatar_enabled,
            "wake": {"enabled": r.settings.wake_word_enabled,
                     "phrase": f"Hey {r.settings.agent_name}"},
        }

    @app.post("/api/voice/wake")
    async def wake(request: Request) -> dict:
        """Is this short burst of speech the wake phrase? Audio is never stored."""
        from .voice.wake import match, wake_phrases

        r = rt()
        if r.settings.paused:
            raise HTTPException(409, "The agent is paused, so the wake word is off. Resume it in Trust.")
        if not (r.settings.wake_word_enabled and r.settings.voice_enabled):
            raise HTTPException(409, "The wake word is off. Turn it on in Trust → Capabilities.")
        try:
            audio = read_wav(await request.body())
        except AudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        seconds = len(audio) / 16000
        if not 0.3 <= seconds <= 8:
            return {"wake": False, "heard": "", "command": ""}
        try:
            result = await r.wake_stt.transcribe(audio)
        except Exception as exc:  # noqa: BLE001 - a missing or broken wake model must not silently kill the wake word
            if r.wake_stt is r.stt:
                raise HTTPException(503, f"Speech recognition failed: {exc}. Try: localagent setup --voice") from exc
            log.warning("wake model %s failed (%s); using the main speech model instead", r.settings.wake_model, exc)
            r.wake_stt = r.stt
            try:
                result = await r.stt.transcribe(audio)
            except Exception as exc2:  # noqa: BLE001
                raise HTTPException(503, f"Speech recognition failed: {exc2}. Try: localagent setup --voice") from exc2
        woke, phrase, rest = match(result["text"], wake_phrases(r.settings.agent_name, r.settings.wake_phrases))
        # `heard` is shown briefly on this screen so you can see what it understood; it is never stored.
        return {"wake": woke, "heard": result["text"].strip(), "command": rest, "ms": result.get("ms")}

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
            raise HTTPException(503, "Speech output isn't available: on Windows/Linux run: pipx inject localaiagent pyttsx3")
        finished = await r.tts.speak(body.text)
        return {"ok": True, "finished": finished}

    @app.post("/api/voice/audio")
    async def voice_audio(body: SpeakIn) -> Response:
        """The reply as WAV, for playback in the browser (the avatar lip-syncs to it)."""
        r = rt()
        if not r.tts.available():
            raise HTTPException(503, "Speech output isn't available: on Windows/Linux run: pipx inject localaiagent pyttsx3")
        try:
            audio = await r.tts.synthesize(body.text)
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
        if not audio:
            raise HTTPException(400, "Nothing to say.")
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.post("/api/voice/stop")
    async def stop_speaking() -> dict:
        return {"stopped": await rt().tts.stop()}

    # ── settings ──────────────────────────────────────────────────────────
    @app.get("/api/settings")
    async def get_settings() -> dict:
        return rt().settings.to_dict()

    async def change_settings(values: dict, request: Request) -> dict:
        """Apply settings like PUT /api/settings: security-sensitive changes need X-Confirm, every
        change is audited, sensitive ones also raise a security nudge."""
        r = rt()
        risky = sensitive_changes(r.settings, values)
        confirmed = {k.strip() for k in request.headers.get("x-confirm", "").split(",") if k.strip()}
        missing = [k for k in risky if k not in confirmed]
        if missing:
            # 428: the UI shows what each change risks and resends with X-Confirm once you agree.
            raise HTTPException(428, {"message": "Please confirm these security-sensitive changes.",
                                      "confirm": [{"key": k, "risk": SENSITIVE_SETTINGS[k],
                                                   "from": risky[k][0], "to": risky[k][1]} for k in missing]})
        before = r.settings.to_dict()
        try:
            s = await r.apply_settings(values)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        after = s.to_dict()
        changed = {k: (before[k], after[k]) for k in after if before.get(k) != after[k]}
        for k, (old, new) in changed.items():
            r.audit.append("settings_changed", k, outcome="sensitive" if k in risky else "ok",
                           detail=f"{old!r} → {new!r}"[:500])
        if risky:
            await r.nudges.deliver("security", f"security:{time.time()}", "A security setting changed",
                                   "; ".join(f"{k}: {v[0]!r} → {v[1]!r}" for k, v in risky.items())[:300], 2)
        return after

    @app.put("/api/settings")
    async def put_settings(values: dict, request: Request) -> dict:
        return await change_settings(values, request)

    # ── trust & transparency center ───────────────────────────────────────
    def window(since: str, until: str) -> tuple[float, float]:
        def parse(v: str, default: float, end: bool = False) -> float:
            if not v:
                return default
            try:
                return float(v)
            except ValueError:
                pass
            try:
                d = datetime.fromisoformat(v)
            except ValueError as exc:
                raise HTTPException(400, f"Not a date: {v}") from exc
            if end and len(v) <= 10:
                d = d.replace(hour=23, minute=59, second=59)
            return d.timestamp()

        now = time.time()
        a, b = parse(since, now - 7 * 86400), parse(until, now, end=True)
        if a > b:
            raise HTTPException(400, "The start is after the end.")
        return a, b

    @app.get("/api/trust")
    async def trust_overview() -> dict:
        return trust.overview(rt())

    @app.post("/api/trust/capability/{cap_id}")
    async def trust_capability(cap_id: str, body: dict, request: Request) -> dict:
        r = rt()
        cap = trust.CAP_BY_ID.get(cap_id)
        if cap is None:
            raise HTTPException(404, "Unknown capability")
        enabled = bool(body.get("enabled"))
        forgotten = trust.forget(r, cap_id) if (body.get("forget") and not enabled) else []
        change = {cap["setting"]: enabled}
        if cap_id == "wake" and enabled and not r.settings.voice_enabled:
            change["voice_enabled"] = True       # the wake word needs voice on; otherwise the switch does nothing
        await change_settings(change, request)
        if forgotten:
            r.audit.append("trust_forget", cap_id, outcome="ok", detail="; ".join(forgotten))
        return {"forgotten": forgotten, **trust.overview(r)}

    @app.post("/api/trust/ask")
    async def trust_ask_endpoint(body: dict) -> dict:
        from .trust_ask import ask

        return await ask(rt(), str(body.get("question", "")))

    @app.post("/api/trust/pause")
    async def trust_pause(body: dict, request: Request) -> dict:
        await change_settings({"paused": bool(body.get("paused"))}, request)
        return trust.overview(rt())

    @app.put("/api/trust/autonomy")
    async def trust_autonomy(body: dict, request: Request) -> dict:
        await change_settings({"autonomy": str(body.get("autonomy", ""))}, request)
        return trust.overview(rt())

    @app.get("/api/trust/egress")
    async def trust_egress(since: str = "", until: str = "") -> list[dict]:
        a, b = window(since, until)
        return trust.egress_ledger(rt(), a, b)[::-1]

    async def off_loop(fn, *args, limit: float = 90.0):
        """Run heavy trust work in a thread: the rest of the app keeps answering meanwhile."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), limit)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "That took too long. Try a shorter date range.") from exc

    @app.get("/api/trust/checks")
    async def trust_checks(since: str = "", until: str = "") -> dict:
        a, b = window(since, until)
        started = time.perf_counter()
        report = await off_loop(trust.checks, rt(), a, b)
        report["seconds"] = round(time.perf_counter() - started, 2)
        return report

    @app.get("/api/trust/export")
    async def trust_export(since: str = "", until: str = "", raw: bool = False, confirm_raw: str = "") -> Response:
        if raw and confirm_raw != "yes":
            raise HTTPException(400, "A raw export contains your personal data; confirm it first.")
        a, b = window(since, until)
        data, manifest = await off_loop(lambda: trust.export(rt(), a, b, raw=raw))
        name = (f"localagent-activity-{manifest['window']['since_local'][:10]}_"
                f"{manifest['window']['until_local'][:10]}{'-RAW' if raw else ''}.zip")
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})

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
