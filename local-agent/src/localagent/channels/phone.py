"""Call your agent: a Twilio phone number whose calls are answered on this Mac.

Twilio needs to reach the Mac, so the phone webhook gets its own tiny listener on
127.0.0.1:`phone_port` with only these routes; a tunnel (cloudflared or Tailscale Funnel)
forwards your public URL to it. The main app is never exposed.

Every request must carry a valid `X-Twilio-Signature` (HMAC-SHA1 with your Twilio auth
token, kept in the Keychain), and only your own numbers are answered. Speech recognition
is Twilio's (cloud): what you say on a call goes through Twilio. By phone the agent can
look things up and prepare drafts, but never send, change or delete anything.

Local models can take longer than Twilio's 15 s webhook limit, so a question is answered
in the background while the caller hears "one moment" and Twilio polls /twilio/result.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request
from fastapi.responses import Response

from ..connectors.messages import norm_handle
from ..voice.tts import speakable

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)
TOKEN = "twilio_auth_token"
MAX_WAIT = 90


def signature(token: str, url: str, params: dict) -> str:
    """Twilio's request signature: base64(HMAC-SHA1(token, url + key1 + value1 + … sorted by key))."""
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def twiml(*parts: str) -> Response:
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>",
                    media_type="application/xml")


def say(text: str) -> str:
    return f'<Say voice="Polly.Joanna">{escape(text)}</Say>'


def gather(prompt: str) -> str:
    return (f'<Gather input="speech" action="gather" method="POST" speechTimeout="auto" language="en-US">'
            f"{say(prompt)}</Gather>{say('I did not hear anything. Goodbye.')}<Hangup/>")


def phone_app(rt: "Runtime") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    jobs: dict[str, dict] = {}

    async def check(request: Request) -> dict | None:
        """Form params if the request is genuinely from Twilio for an owner's call, else None."""
        form = dict(parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True))
        token = rt.vault.get(TOKEN)
        base = rt.settings.phone_public_url.rstrip("/")
        url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        given = request.headers.get("X-Twilio-Signature", "")
        if not (rt.settings.phone_enabled and token and base
                and hmac.compare_digest(signature(token, url, form), given)):
            rt.audit.append("phone_rejected", "phone", outcome="rejected", detail="bad or missing Twilio signature")
            return None
        owners = {norm_handle(n) for n in rt.settings.phone_owner_numbers.split(",") if n.strip()}
        if norm_handle(form.get("From", "")) not in owners:
            rt.audit.append("phone_rejected", "phone", outcome="rejected",
                            detail=f"call from {form.get('From', 'unknown')} (not an owner)")
            form["_stranger"] = "1"
        return form

    @app.post("/twilio/voice")
    async def voice(request: Request) -> Response:
        form = await check(request)
        if form is None:
            return Response("forbidden", status_code=403)
        if form.get("_stranger"):
            return twiml(say("Sorry, this number is private."), "<Hangup/>")
        rt.audit.append("phone_call", "phone", outcome="ok", detail=f"call from {form.get('From')}")
        return twiml(gather(f"Hi, it's {rt.settings.agent_name}. What can I do for you?"))

    @app.post("/twilio/gather")
    async def on_speech(request: Request) -> Response:
        form = await check(request)
        if form is None:
            return Response("forbidden", status_code=403)
        if form.get("_stranger"):
            return twiml("<Hangup/>")
        text = form.get("SpeechResult", "").strip()
        if not text:
            return twiml(gather("Sorry, I didn't catch that. Could you say it again?"))
        if text.lower().strip(" .!") in ("goodbye", "bye", "that's all", "nothing", "no thanks", "no"):
            return twiml(say("Bye!"), "<Hangup/>")
        job = secrets.token_urlsafe(8)
        jobs[job] = {"started": time.time(), "text": None}
        asyncio.create_task(answer(job, text))
        return twiml(say("One moment."), f'<Redirect method="POST">result?id={job}</Redirect>')

    async def answer(job: str, text: str) -> None:
        from ..agent.chat import handle_turn

        parts: list[str] = []
        try:
            async for ev in handle_turn(rt, text, channel="phone"):
                if ev["type"] == "token":
                    parts.append(ev["text"])
                elif ev["type"] == "reset":
                    parts.clear()
        except Exception:  # noqa: BLE001 - the caller still gets an answer
            log.exception("phone turn failed")
        reply = speakable("".join(parts).strip(), limit=900) or "Sorry, I couldn't work that out."
        jobs[job]["text"] = reply

    @app.post("/twilio/result")
    async def result(request: Request, id: str = "") -> Response:
        form = await check(request)
        if form is None:
            return Response("forbidden", status_code=403)
        if form.get("_stranger"):
            return twiml("<Hangup/>")
        job = jobs.get(id)
        if job is None:
            return twiml(gather("Sorry, I lost that. What can I do for you?"))
        if job["text"] is None:
            if time.time() - job["started"] > MAX_WAIT:
                jobs.pop(id, None)
                return twiml(gather("That is taking too long; I'll keep it in the app. Anything else?"))
            return twiml('<Pause length="2"/>', f'<Redirect method="POST">result?id={id}</Redirect>')
        jobs.pop(id, None)
        for k in [k for k, v in jobs.items() if time.time() - v["started"] > 600]:
            jobs.pop(k, None)
        return twiml(say(job["text"]), gather("Anything else?"))

    return app
