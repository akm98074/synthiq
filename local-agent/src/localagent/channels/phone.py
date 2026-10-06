"""Call your agent: a Twilio phone number whose calls are answered on this Mac.

Twilio needs to reach the Mac, so the phone webhook gets its own tiny listener on
127.0.0.1:`phone_port` with only these routes; a tunnel (cloudflared or Tailscale Funnel)
forwards your public URL to it. The main app is never exposed.

Every request must carry a valid `X-Twilio-Signature` (HMAC-SHA1 with your Twilio auth
token, kept in the Keychain), and only your own numbers are answered. Caller ID can be faked,
so every call must also give your PIN (typed or spoken, kept in the Keychain) before anything
else, three wrong tries end the call, and calls whose caller ID Twilio marks as failing
verification (STIR/SHAKEN) are refused. Speech recognition
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
PIN = "phone_pin"
MAX_WAIT = 90
MAX_PIN_TRIES = 3
WORD_DIGITS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "to": "2", "too": "2", "three": "3",
               "four": "4", "for": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "ate": "8",
               "nine": "9"}


def digits_of(text: str) -> str:
    """'1 2 3 4', '1234' or 'one two three four' -> '1234'."""
    out = []
    for w in text.lower().replace("-", " ").replace(",", " ").replace(".", " ").split():
        out.append(w if w.isdigit() else WORD_DIGITS.get(w, ""))
    return "".join(out)


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 8


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


def ask_pin(prompt: str) -> str:
    return (f'<Gather input="dtmf speech" action="pin" method="POST" finishOnKey="#" timeout="8" '
            f'speechTimeout="auto" language="en-US">{say(prompt)}</Gather>'
            f"{say('I did not get a PIN. Goodbye.')}<Hangup/>")


def phone_app(rt: "Runtime") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    jobs: dict[str, dict] = {}
    verified: dict[str, float] = {}     # CallSid -> when the PIN was given
    tries: dict[str, int] = {}

    def signed_in(form: dict) -> bool:
        now = time.time()
        for k in [k for k, t in verified.items() if now - t > 3600]:
            verified.pop(k, None)
        return form.get("CallSid", "") in verified

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
        if "failed" in form.get("StirVerstat", "").lower():
            rt.audit.append("phone_rejected", "phone", outcome="rejected",
                            detail=f"call from {form.get('From')}: caller ID failed verification ({form['StirVerstat']})")
            return twiml(say("Sorry, this number is private."), "<Hangup/>")
        if not valid_pin(rt.vault.get(PIN) or ""):
            rt.audit.append("phone_rejected", "phone", outcome="rejected", detail="no phone PIN set")
            return twiml(say("This phone line needs a PIN first. Set one in the app, under Settings, "
                             "Phone line. Goodbye."), "<Hangup/>")
        rt.audit.append("phone_call", "phone", outcome="ok", detail=f"call from {form.get('From')}")
        return twiml(ask_pin(f"Hi, it's {rt.settings.agent_name}. Please type or say your PIN, then press hash."))

    @app.post("/twilio/pin")
    async def on_pin(request: Request) -> Response:
        form = await check(request)
        if form is None:
            return Response("forbidden", status_code=403)
        if form.get("_stranger"):
            return twiml("<Hangup/>")
        sid = form.get("CallSid", "")
        given = digits_of(form.get("Digits") or form.get("SpeechResult") or "")
        pin = rt.vault.get(PIN) or ""
        if sid and valid_pin(pin) and hmac.compare_digest(given.encode(), pin.encode()):
            verified[sid] = time.time()
            tries.pop(sid, None)
            rt.audit.append("phone_pin_ok", "phone", outcome="ok", detail=f"call from {form.get('From')}")
            return twiml(gather("Thanks. What can I do for you?"))
        tries[sid] = tries.get(sid, 0) + 1
        rt.audit.append("phone_pin_wrong", "phone", outcome="rejected",
                        detail=f"wrong PIN from {form.get('From')} (try {tries[sid]})")
        if tries[sid] >= MAX_PIN_TRIES:
            tries.pop(sid, None)
            return twiml(say("That's not right. Goodbye."), "<Hangup/>")
        return twiml(ask_pin("That's not right. Please try again."))

    @app.post("/twilio/gather")
    async def on_speech(request: Request) -> Response:
        form = await check(request)
        if form is None:
            return Response("forbidden", status_code=403)
        if form.get("_stranger") or not signed_in(form):
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
        if form.get("_stranger") or not signed_in(form):
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
