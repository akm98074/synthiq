"""A small stand-in for Google's OAuth token endpoint and the Gmail API, for tests."""
from __future__ import annotations

import base64
import hashlib
import socket
import threading
import time
from email import message_from_bytes

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def msg(mid, thread, frm, subject, snippet, days_ago, unread=False, body=None, html=False, msgid=None):
    date = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(time.time() - days_ago * 86400 - 3600))
    mime = "text/html" if html else "text/plain"
    return {"id": mid, "threadId": thread, "snippet": snippet, "labelIds": ["INBOX"] + (["UNREAD"] if unread else []),
            "payload": {"mimeType": "multipart/alternative",
                        "headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subject},
                                    {"name": "Date", "value": date}, {"name": "To", "value": "me@gmail.com"},
                                    {"name": "Message-ID", "value": msgid or f"<{mid}@mail.gmail.com>"}],
                        "parts": [{"mimeType": mime, "body": {"data": b64(body or snippet)}}]}}


def create_app(state: dict) -> FastAPI:
    app = FastAPI()
    state.update(codes={}, access="at-1", refresh="rt-1", revoked=False, fail_next=0, drafts=[], sent=[], queries=[])
    state["messages"] = {m["id"]: m for m in [
        msg("m1", "t1", "Priya <priya@acme.com>", "Can you review the deck?", "Need comments by Thursday", 2,
            body="Hi,\n\nCan you review the deck by Thursday?\n\nPriya"),
        msg("m2", "t2", "News <news@substack.com>", "Weekly digest", "Top stories", 1, unread=True,
            body="<p>Top <b>stories</b> &amp; more</p><script>x()</script>", html=True),
        msg("m3", "t3", "Sam <sam@example.com>", "Lunch?", "Free tomorrow?", 3),
        msg("m4", "t3", "Me <me@gmail.com>", "Re: Lunch?", "Sure!", 2),
    ]}

    def auth(authorization: str | None):
        if state["fail_next"]:
            state["fail_next"] -= 1
            raise HTTPException(401, {"message": "expired"})
        if authorization != f"Bearer {state['access']}":
            raise HTTPException(401, {"message": "bad token"})

    @app.get("/auth")
    async def consent(request: Request):
        """Pretend the user clicked Allow on Google's consent screen."""
        from fastapi.responses import RedirectResponse

        q = request.query_params
        state["codes"]["auto"] = q["code_challenge"]
        return RedirectResponse(f"{q['redirect_uri']}?code=auto&state={q['state']}")

    @app.post("/token")
    async def token(request: Request):
        from urllib.parse import parse_qs

        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        grant_type, code, code_verifier = form.get("grant_type"), form.get("code"), form.get("code_verifier")
        refresh_token, client_secret = form.get("refresh_token"), form.get("client_secret", "")
        if client_secret != "shh":
            raise HTTPException(401, {"error": "invalid_client"})
        if grant_type == "authorization_code":
            challenge = state["codes"].pop(code, None)
            digest = base64.urlsafe_b64encode(hashlib.sha256((code_verifier or "").encode()).digest()).rstrip(b"=")
            if challenge is None or digest.decode() != challenge:
                raise HTTPException(400, {"error": "invalid_grant"})
            return {"access_token": state["access"], "refresh_token": state["refresh"], "expires_in": 3600}
        if grant_type == "refresh_token":
            if state["revoked"] or refresh_token != state["refresh"]:
                raise HTTPException(400, {"error": "invalid_grant", "error_description": "Token has been revoked."})
            state["access"] = f"at-{int(state['access'][3:]) + 1}"
            return {"access_token": state["access"], "expires_in": 3600}
        raise HTTPException(400, {"error": "unsupported_grant_type"})

    @app.get("/gmail/v1/users/me/profile")
    async def profile(authorization: str = Header(None)):
        auth(authorization)
        return {"emailAddress": "me@gmail.com"}

    @app.get("/gmail/v1/users/me/messages")
    async def list_messages(request: Request, q: str = "", maxResults: int = 10, authorization: str = Header(None)):
        auth(authorization)
        state["queries"].append(q)
        ids = [m for m in state["messages"].values() if "me@gmail.com" not in m["payload"]["headers"][0]["value"]]
        return {"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in ids][:maxResults]}

    @app.get("/gmail/v1/users/me/messages/{mid}")
    async def get_message(mid: str, authorization: str = Header(None)):
        auth(authorization)
        return state["messages"][mid]

    @app.get("/gmail/v1/users/me/threads")
    async def list_threads(q: str = "", maxResults: int = 10, authorization: str = Header(None)):
        auth(authorization)
        state["queries"].append(q)
        return {"threads": [{"id": t} for t in ("t1", "t2", "t3")]}

    @app.get("/gmail/v1/users/me/threads/{tid}")
    async def get_thread(tid: str, authorization: str = Header(None)):
        auth(authorization)
        return {"id": tid, "messages": [m for m in state["messages"].values() if m["threadId"] == tid]}

    @app.post("/gmail/v1/users/me/drafts")
    async def draft(body: dict, authorization: str = Header(None)):
        auth(authorization)
        state["drafts"].append(body["message"])
        return {"id": "d1", "message": {"id": "m9"}}

    @app.post("/gmail/v1/users/me/messages/send")
    async def send(body: dict, authorization: str = Header(None)):
        auth(authorization)
        state["sent"].append(body)
        return {"id": "m10", "threadId": body.get("threadId", "t9")}

    return app


def parse_raw(raw: str):
    return message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


class FakeGoogle:
    def __init__(self):
        self.state: dict = {}
        self.app = create_app(self.state)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    def endpoints(self):
        from localagent.connectors.gmail import GoogleEndpoints

        return GoogleEndpoints(auth=self.url + "/auth", token=self.url + "/token",
                               api=self.url + "/gmail/v1/users/me")

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)
