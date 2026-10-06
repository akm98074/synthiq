"""Gmail, directly: sign in with Google (OAuth, your own client ID), then search, read,
draft and send through the Gmail API. No Apple Mail needed.

Sign-in is the standard "installed app" flow: the browser goes to Google's consent page and
Google redirects back to this Mac's own address (127.0.0.1), with PKCE. The refresh token is
kept in the Keychain (see vault.py); access tokens live only in memory.
"""
from __future__ import annotations

import base64
import hashlib
import html
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s
from ..vault import Vault

SCOPES = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.compose"
CLIENT_SECRET = "gmail_client_secret"
REFRESH = "gmail_refresh_token"


@dataclass
class GoogleEndpoints:
    auth: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token: str = "https://oauth2.googleapis.com/token"
    api: str = "https://gmail.googleapis.com/gmail/v1/users/me"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class GmailAuth:
    """The sign-in flow. One pending flow at a time (state → verifier, redirect)."""

    def __init__(self, vault: Vault, endpoints: GoogleEndpoints, client_id: str):
        self.vault, self.ep, self.client_id = vault, endpoints, client_id
        self.pending: dict[str, tuple[str, str, float]] = {}

    def auth_url(self, redirect: str) -> str:
        if not self.client_id or not self.vault.has(CLIENT_SECRET):
            raise ToolError("Add your Google OAuth client ID and secret first (Settings → Gmail).")
        verifier, challenge = pkce()
        state = secrets.token_urlsafe(16)
        self.pending = {state: (verifier, redirect, time.time())}
        return self.ep.auth + "?" + urlencode({
            "client_id": self.client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
            "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline",
            "prompt": "consent", "state": state})

    async def finish(self, code: str, state: str) -> str:
        """Exchange the code; store the refresh token. Returns the Gmail address."""
        entry = self.pending.pop(state, None)
        if entry is None or time.time() - entry[2] > 600:
            raise ToolError("This sign-in link expired or wasn't started here. Press Connect Gmail again.")
        verifier, redirect, _ = entry
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(self.ep.token, data={
                "code": code, "client_id": self.client_id, "client_secret": self.vault.get(CLIENT_SECRET),
                "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
        if r.status_code != 200:
            raise ToolError(f"Google refused the sign-in: {_google_error(r)}")
        tok = r.json()
        if not tok.get("refresh_token"):
            raise ToolError("Google didn't return a refresh token. Remove LocalAIAgent's access at "
                            "myaccount.google.com/permissions and connect again.")
        self.vault.set(REFRESH, tok["refresh_token"])
        client = GmailClient(self.vault, self.ep, self.client_id)
        client._access, client._expires = tok["access_token"], time.time() + int(tok.get("expires_in", 3600)) - 60
        profile = await client.get("/profile")
        return profile.get("emailAddress", "")


def _google_error(r: httpx.Response) -> str:
    try:
        j = r.json()
        err = j.get("error")
        if isinstance(err, dict):
            return err.get("message") or str(err)
        return f"{err}: {j.get('error_description', '')}".strip(": ")
    except ValueError:
        return f"HTTP {r.status_code}"


class GmailClient:
    def __init__(self, vault: Vault, endpoints: GoogleEndpoints, client_id: str):
        self.vault, self.ep, self.client_id = vault, endpoints, client_id
        self._access, self._expires = None, 0.0

    def connected(self) -> bool:
        return self.vault.has(REFRESH)

    async def _token(self, force: bool = False) -> str:
        if self._access and not force and time.time() < self._expires:
            return self._access
        refresh = self.vault.get(REFRESH)
        if not refresh:
            raise ToolError("Gmail isn't connected. Settings → Gmail → Connect Gmail.")
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(self.ep.token, data={
                "client_id": self.client_id, "client_secret": self.vault.get(CLIENT_SECRET) or "",
                "refresh_token": refresh, "grant_type": "refresh_token"})
        if r.status_code != 200:
            if "invalid_grant" in r.text:
                self.vault.delete(REFRESH)
                raise ToolError("Google says the Gmail sign-in was revoked or expired. "
                                "Connect Gmail again in Settings.")
            raise ToolError(f"Couldn't refresh the Gmail sign-in: {_google_error(r)}")
        tok = r.json()
        self._access, self._expires = tok["access_token"], time.time() + int(tok.get("expires_in", 3600)) - 60
        return self._access

    async def _call(self, method: str, path: str, **kw) -> dict:
        for attempt in (0, 1):
            token = await self._token(force=attempt == 1)
            try:
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.request(method, self.ep.api + path, headers={"Authorization": f"Bearer {token}"}, **kw)
            except httpx.HTTPError as exc:
                raise ToolError(f"Couldn't reach Gmail ({exc.__class__.__name__}).") from exc
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code >= 400:
                raise ToolError(f"Gmail error: {_google_error(r)}")
            return r.json() if r.content else {}
        raise ToolError("Gmail rejected the sign-in. Connect Gmail again in Settings.")

    async def get(self, path: str, **params) -> dict:
        return await self._call("GET", path, params=params or None)

    async def post(self, path: str, body: dict) -> dict:
        return await self._call("POST", path, json=body)

    # ── high-level ────────────────────────────────────────────────────────
    async def search(self, query: str, limit: int = 10) -> list[dict]:
        listing = await self.get("/messages", q=query, maxResults=limit)
        out = []
        for ref in listing.get("messages", [])[:limit]:
            m = await self.get(f"/messages/{ref['id']}", format="metadata",
                               metadataHeaders=["From", "To", "Subject", "Date"])
            out.append(summary(m))
        return out

    async def read(self, msg_id: str) -> dict:
        m = await self.get(f"/messages/{msg_id}", format="full")
        return {**summary(m), "body": body_text(m.get("payload", {}))[:20000]}

    async def me(self) -> str:
        return (await self.get("/profile")).get("emailAddress", "")

    async def followups(self, min_days: int, max_days: int, limit: int) -> list[dict]:
        me = (await self.me()).lower()
        q = (f"in:inbox -from:me newer_than:{max_days}d older_than:{min_days}d "
             "-category:promotions -category:social -category:updates -category:forums")
        listing = await self.get("/threads", q=q, maxResults=limit * 2)
        out = []
        for t in listing.get("threads", []):
            th = await self.get(f"/threads/{t['id']}", format="metadata", metadataHeaders=["From", "Subject", "Date"])
            msgs = th.get("messages", [])
            if not msgs:
                continue
            last = summary(msgs[-1])
            if me and me in last["from"].lower():
                continue                       # you replied last
            out.append(last)
            if len(out) >= limit:
                break
        return out

    async def compose(self, to: str, subject: str, body: str, reply_to: str | None, send: bool) -> dict:
        msg = EmailMessage()
        msg["To"], msg["Subject"] = to, subject
        thread_id = None
        if reply_to:
            orig = await self.get(f"/messages/{reply_to}", format="metadata",
                                  metadataHeaders=["Message-ID", "Subject", "References"])
            h = headers(orig)
            if h.get("message-id"):
                msg["In-Reply-To"] = h["message-id"]
                msg["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
            thread_id = orig.get("threadId")
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"raw": raw, **({"threadId": thread_id} if thread_id else {})}
        if send:
            return await self.post("/messages/send", payload)
        return await self.post("/drafts", {"message": payload})


def headers(m: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}


def summary(m: dict) -> dict:
    h = headers(m)
    try:
        when = parsedate_to_datetime(h["date"]).astimezone().replace(tzinfo=None)
    except (KeyError, TypeError, ValueError):
        ms = int(m.get("internalDate", 0) or 0)
        when = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().replace(tzinfo=None)
    return {"id": m.get("id", ""), "thread": m.get("threadId", ""), "subject": h.get("subject", "(no subject)"),
            "from": h.get("from", ""), "received": when.isoformat(timespec="minutes"),
            "days_ago": max(0, (datetime.now() - when).days), "read": "UNREAD" not in m.get("labelIds", []),
            "snippet": html.unescape(m.get("snippet", ""))[:200]}


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def body_text(payload: dict) -> str:
    """The plain-text body (or the HTML body as text) of a Gmail message payload."""
    plain, htm = [], []

    def walk(p: dict) -> None:
        mime = p.get("mimeType", "")
        data = p.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data))
        elif data and mime == "text/html":
            htm.append(_b64(data))
        for part in p.get("parts", []) or []:
            walk(part)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", "\n".join(htm), flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _check_to(value) -> str:
    items = value if isinstance(value, list) else str(value).replace(";", ",").split(",")
    out = [x.strip() for x in items if x and "@" in parseaddr(x.strip())[1]]
    if not out:
        raise ToolError("Give at least one email address (look it up with contacts_find first).")
    return ", ".join(out)


def gmail_tools(client: GmailClient) -> list[Tool]:
    def lines(msgs: list[dict]) -> str:
        return "\n".join(f"- [id {m['id']}] {m['received'].replace('T', ' ')} from {m['from']}: {m['subject']}"
                         + ("" if m["read"] else " (unread)") + f"\n  {m['snippet']}" for m in msgs)

    async def search(a: dict) -> ToolResult:
        msgs = await client.search(a.get("query") or "in:inbox", a.get("limit", 10))
        if not msgs:
            return ToolResult("No matching Gmail messages.", "No matching Gmail", [])
        return ToolResult("Gmail messages (newest first):\n" + lines(msgs), f"Found {len(msgs)} Gmail message(s)",
                          msgs, untrusted=True)

    async def read(a: dict) -> ToolResult:
        m = await client.read(str(a["id"]))
        return ToolResult(f"From: {m['from']}\nDate: {m['received'].replace('T', ' ')}\nSubject: {m['subject']}\n\n"
                          f"{m['body']}", f"Read: {m['subject']}", {"subject": m["subject"], "from": m["from"]},
                          untrusted=True)

    async def followups(a: dict) -> ToolResult:
        msgs = await client.followups(a.get("min_days", 1), a.get("max_days", 7), a.get("limit", 15))
        if not msgs:
            return ToolResult("No Gmail threads waiting on your reply.", "Nothing waiting on a reply", [])
        return ToolResult("Gmail threads you haven't replied to:\n" + lines(msgs),
                          f"{len(msgs)} Gmail thread(s) without a reply", msgs, untrusted=True)

    async def compose(a: dict, send: bool) -> ToolResult:
        to = _check_to(a["to"])
        await client.compose(to, a["subject"], a["body"], a.get("reply_to"), send)
        if send:
            return ToolResult(f"Sent '{a['subject']}' to {to} from Gmail.", f"Sent from Gmail to {to}", {"to": to})
        return ToolResult(f"Saved a Gmail draft '{a['subject']}' to {to}; it's in Gmail's Drafts for the user to "
                          "review and send.", f"Gmail draft saved: {a['subject']}", {"to": to})

    params = obj({"to": s("Recipient email address(es), comma-separated"), "subject": s("Subject line"),
                  "body": s("Plain-text body"),
                  "reply_to": s("Optional: id of the Gmail message this replies to (keeps the thread)")},
                 ["to", "subject", "body"])
    intents = ("task", "computer_action", "quick_answer", "schedule")
    return [
        Tool("gmail_search", "Search Gmail with Gmail's search syntax (e.g. 'from:sam is:unread', "
             "'subject:invoice newer_than:7d').",
             obj({"query": s("Gmail search, default: in:inbox"), "limit": i("Max messages (default 10)")}),
             "read", "gmail", search, lambda a: f"Search Gmail: {a.get('query') or 'inbox'}", intents),
        Tool("gmail_read", "Read one Gmail message in full by its id (from gmail_search).",
             obj({"id": s("Message id from gmail_search")}, ["id"]),
             "read", "gmail", read, lambda a: "Read a Gmail message", intents),
        Tool("gmail_followups", "List Gmail threads the user hasn't replied to (default 1-7 days old).",
             obj({"min_days": i("At least this many days old (default 1)"),
                  "max_days": i("At most this many days old (default 7)"), "limit": i("Max (default 15)")}),
             "read", "gmail", followups, lambda a: "Check Gmail for emails waiting on your reply", intents),
        Tool("gmail_draft", "Save a draft in Gmail for the user to review and send.", params, "draft", "gmail",
             lambda a: compose(a, False), lambda a: f"Gmail draft to {a.get('to', '')}: “{a.get('subject', '')}”",
             ("task", "computer_action")),
        Tool("gmail_send", "Send an email from Gmail now. Prefer gmail_draft unless the user clearly asked to send.",
             params, "write", "gmail", lambda a: compose(a, True),
             lambda a: f"Send from Gmail to {a.get('to', '')}: “{a.get('subject', '')}”", ("computer_action",)),
    ]
