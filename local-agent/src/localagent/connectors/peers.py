"""Trusted agents: your agent talks to a friend's agent, end-to-end encrypted.

Pairing is by invite code (no server in between): one agent creates a one-time invite with
its public key and address; the other accepts it and introduces itself back. From then on
each message is a NaCl `Box` (X25519 + XSalsa20-Poly1305) between the two agents' keys,
so only the paired agent can read it and only it could have written it. Each message also
carries a timestamp and a random id; old or repeated ones are dropped.

What a friend's agent can get without you:
  freebusy   busy times in a date range (no titles), if you allowed it for that friend
  message    "leave a message": delivered to you as a nudge
Anything else ("can he do dinner Friday?") waits for your answer.

Transport: a separate small listener (`a2a_port`, default 8766), on only when you turn the
feature on. It only accepts encrypted messages from paired agents (and hellos with a valid
one-time invite). The app itself stays on 127.0.0.1.
"""
from __future__ import annotations

import base64
import json
import logging
import secrets
import socket
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from ..tools.base import Tool, ToolError, ToolResult, obj, parse_when, s

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)

PRIVATE = "peer_private_key"
MAX_SKEW = 300
RATE_PER_MIN = 30
INVITE_TTL = 86400            # an intercepted code is only useful for a day
EMOJI = "🍎🍌🍇🍉🍒🍋🥕🌽🍄🌵🌻🌙⭐🔥💧⚡🎈🎁🎵🎲🚲🚀⛵🏠🔑🔔📚✏️🧭⚓🐢🐙🦊🐼🐝🦋🐳"
SCHEMA = """
CREATE TABLE IF NOT EXISTS peers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
  key TEXT NOT NULL UNIQUE, addr TEXT NOT NULL, scopes TEXT NOT NULL DEFAULT '["message"]',
  created_at REAL NOT NULL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS peer_invites (token TEXT PRIMARY KEY, created_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS peer_nonces (nonce TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS peer_inbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, peer_id INTEGER NOT NULL, ts REAL NOT NULL, ask_id TEXT NOT NULL,
  text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'waiting', reply TEXT
);
"""
SCOPES = {"freebusy": "See when you're busy (times only)", "message": "Leave you messages"}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def lan_address() -> str:
    """This Mac's address on the local network (no packets are sent)."""
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s_.connect(("10.255.255.255", 1))
        return s_.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s_.close()


class Peers:
    def __init__(self, rt: "Runtime"):
        from nacl.public import PrivateKey

        self.rt = rt
        rt.store.db.executescript(SCHEMA)
        cols = {r["name"] for r in rt.store.db.execute("PRAGMA table_info(peers)")}
        if "verified" not in cols:
            # Pairings from before 0.16 must be confirmed with the safety code once.
            rt.store.db.execute("ALTER TABLE peers ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
        rt.store.db.commit()
        raw = rt.vault.get(PRIVATE)
        if not raw:
            raw = b64(bytes(PrivateKey.generate()))
            rt.vault.set(PRIVATE, raw)
        self.key = PrivateKey(unb64(raw))
        self.recent: dict[int, list[float]] = {}

    # ── identity and pairing ──────────────────────────────────────────────
    @property
    def public(self) -> str:
        return b64(bytes(self.key.public_key))

    @property
    def fingerprint(self) -> str:
        import hashlib

        h = hashlib.sha256(bytes(self.key.public_key)).hexdigest()[:16]
        return " ".join(h[i:i + 4] for i in range(0, 16, 4))

    def safety_code(self, other_key: str) -> str:
        """Four emoji both people see for their pairing. Compare them (in person or on a call): if they
        match, nobody swapped in another agent's key by intercepting the invite."""
        import hashlib

        a, b = sorted([self.public, other_key])
        h = hashlib.sha256(f"{a}|{b}".encode()).digest()
        emoji = list(EMOJI.replace("\ufe0f", ""))
        return " ".join(emoji[x % len(emoji)] for x in h[:4])

    def verify(self, pid: int) -> dict | None:
        self.rt.store.execute("UPDATE peers SET verified=1 WHERE id=?", (pid,))
        peer = self.get(pid)
        if peer:
            self.rt.audit.append("peer_verified", "peers", outcome="ok", detail=f"{peer['name']} safety code confirmed")
        return peer

    def address(self) -> str:
        s_ = self.rt.settings
        return s_.a2a_public_addr or f"http://{lan_address()}:{s_.a2a_port}"

    def card(self) -> dict:
        s_ = self.rt.settings
        return {"name": s_.agent_name, "owner": s_.user_name, "key": self.public, "addr": self.address()}

    def invite(self) -> str:
        token = secrets.token_urlsafe(12)
        self.rt.store.execute("INSERT INTO peer_invites(token, created_at) VALUES (?,?)", (token, time.time()))
        return "la1-" + b64(json.dumps({**self.card(), "token": token}).encode())

    @staticmethod
    def decode_invite(code: str) -> dict:
        code = code.strip()
        if not code.startswith("la1-"):
            raise ToolError("That isn't an agent invite code (it starts with la1-).")
        try:
            data = json.loads(unb64(code[4:]))
            assert all(k in data for k in ("name", "key", "addr", "token"))
            assert len(unb64(data["key"])) == 32
        except Exception as exc:  # noqa: BLE001
            raise ToolError("That invite code is damaged; ask for a new one.") from exc
        return data

    def add_peer(self, card: dict, scopes: list[str] | None = None) -> dict:
        existing = self.by_key(card["key"])
        if existing:
            self.rt.store.execute("UPDATE peers SET name=?, owner=?, addr=? WHERE id=?",
                                  (card["name"], card.get("owner", ""), card["addr"], existing["id"]))
            return self.get(existing["id"])
        cur = self.rt.store.execute(
            "INSERT INTO peers(name, owner, key, addr, scopes, created_at) VALUES (?,?,?,?,?,?)",
            (card["name"], card.get("owner", ""), card["key"], card["addr"], json.dumps(scopes or ["message"]),
             time.time()))
        return self.get(int(cur.lastrowid))

    async def accept(self, code: str) -> dict:
        data = self.decode_invite(code)
        if data["key"] == self.public:
            raise ToolError("That's this agent's own invite.")
        existed = self.by_key(data["key"]) is not None
        peer = self.add_peer(data)
        try:
            await self.send(peer, {"type": "hello", "token": data["token"], "card": self.card()})
        except ToolError:
            if not existed:            # never undo a pairing that was already working
                self.remove(peer["id"])
            raise
        self.rt.audit.append("peer_paired", "peers", outcome="ok", detail=f"{peer['name']} ({peer['addr']})")
        return peer

    # ── storage ───────────────────────────────────────────────────────────
    def _row(self, r) -> dict:
        d = dict(r)
        d["scopes"] = json.loads(d["scopes"])
        d["verified"] = bool(d.get("verified"))
        d["safety_code"] = self.safety_code(d["key"])
        return d

    def list(self) -> list[dict]:
        return [self._row(r) for r in self.rt.store.query("SELECT * FROM peers ORDER BY name")]

    def get(self, pid: int) -> dict | None:
        rows = self.rt.store.query("SELECT * FROM peers WHERE id=?", (pid,))
        return self._row(rows[0]) if rows else None

    def by_key(self, key: str) -> dict | None:
        rows = self.rt.store.query("SELECT * FROM peers WHERE key=?", (key,))
        return self._row(rows[0]) if rows else None

    def find(self, name: str) -> dict:
        name = (name or "").strip().lower()
        peers = self.list()
        for p in peers:
            if name in (p["name"].lower(), p["owner"].lower()) or (name and name in p["owner"].lower()):
                return p
        if len(peers) == 1 and not name:
            return peers[0]
        known = ", ".join(f"{p['owner'] or p['name']}'s agent" for p in peers) or "none yet"
        raise ToolError(f"No trusted agent called '{name}'. Paired: {known}.")

    def set_scopes(self, pid: int, scopes: list[str]) -> dict:
        scopes = [x for x in scopes if x in SCOPES]
        self.rt.store.execute("UPDATE peers SET scopes=? WHERE id=?", (json.dumps(scopes), pid))
        return self.get(pid)

    def remove(self, pid: int) -> bool:
        return self.rt.store.execute("DELETE FROM peers WHERE id=?", (pid,)).rowcount > 0

    # ── crypto envelope ───────────────────────────────────────────────────
    def seal(self, peer_key: str, payload: dict) -> dict:
        from nacl.public import Box, PublicKey

        body = {**payload, "ts": time.time(), "nonce": secrets.token_hex(12)}
        box = Box(self.key, PublicKey(unb64(peer_key)))
        return {"from": self.public, "box": b64(bytes(box.encrypt(json.dumps(body).encode())))}

    def open(self, envelope: dict, sender_key: str) -> dict:
        from nacl.exceptions import CryptoError
        from nacl.public import Box, PublicKey

        try:
            plain = Box(self.key, PublicKey(unb64(sender_key))).decrypt(unb64(envelope["box"]))
            body = json.loads(plain)
        except (CryptoError, KeyError, ValueError, TypeError) as exc:
            raise PermissionError("message failed authentication") from exc
        now = time.time()
        if abs(now - float(body.get("ts", 0))) > MAX_SKEW:
            raise PermissionError("message too old (or clocks differ by more than 5 minutes)")
        self.rt.store.execute("DELETE FROM peer_nonces WHERE ts < ?", (now - 2 * MAX_SKEW,))
        try:
            self.rt.store.execute("INSERT INTO peer_nonces(nonce, ts) VALUES (?,?)", (str(body["nonce"]), now))
        except Exception as exc:  # noqa: BLE001 - unique constraint: a replay
            raise PermissionError("replayed message") from exc
        return body

    async def send(self, peer: dict, payload: dict) -> dict:
        env = self.seal(peer["key"], payload)
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
                r = await c.post(peer["addr"].rstrip("/") + "/a2a/v1/inbox", json=env)
        except httpx.HTTPError as exc:
            raise ToolError(f"Couldn't reach {peer['owner'] or peer['name']}'s agent at {peer['addr']} "
                            f"({exc.__class__.__name__}). Is their Mac awake with the agent running?") from exc
        if r.status_code != 200:
            raise ToolError(f"{peer['name']} refused the message: {r.text[:200]}")
        reply = r.json()
        return self.open(reply, peer["key"]) if reply.get("box") else {}

    # ── inbound ───────────────────────────────────────────────────────────
    async def handle(self, envelope: dict) -> dict:
        """Process one inbound envelope; returns the (encrypted) answer envelope."""
        sender = str(envelope.get("from", ""))
        peer = self.by_key(sender)
        if peer is None:
            body = self.open(envelope, sender)   # must still decrypt with the sender's own key
            if body.get("type") != "hello":
                raise PermissionError("unknown agent")
            return self.seal(sender, self._hello(body))
        now = time.time()
        recent = [t for t in self.recent.get(peer["id"], []) if now - t < 60]
        if len(recent) >= RATE_PER_MIN:
            raise PermissionError("too many messages; slow down")
        self.recent[peer["id"]] = recent + [now]
        body = self.open(envelope, sender)
        self.rt.store.execute("UPDATE peers SET last_seen=? WHERE id=?", (now, peer["id"]))
        return self.seal(sender, await self._dispatch(peer, body))

    def _hello(self, body: dict) -> dict:
        rows = self.rt.store.query("SELECT * FROM peer_invites WHERE token=? AND used=0", (str(body.get("token")),))
        if not rows or time.time() - rows[0]["created_at"] > INVITE_TTL:
            raise PermissionError("invite not valid (used, expired or never made here)")
        self.rt.store.execute("UPDATE peer_invites SET used=1 WHERE token=?", (body["token"],))
        peer = self.add_peer(body["card"])
        self.rt.audit.append("peer_paired", "peers", outcome="ok", detail=f"{peer['name']} accepted your invite")
        return {"type": "welcome", "card": self.card()}

    async def _dispatch(self, peer: dict, body: dict) -> dict:
        kind = body.get("type")
        who = f"{peer['owner'] or peer['name']}'s agent"
        if kind == "ask":
            ask = body.get("kind", "question")
            text = str(body.get("text", ""))[:2000]
            if not peer["verified"]:
                # Until you've compared safety codes, nothing is answered automatically.
                who += " (not verified yet)"
                ask = "question"
            if ask == "freebusy" and "freebusy" in peer["scopes"]:
                busy = await self._busy(str(body.get("start", "")), str(body.get("end", "")))
                self.rt.audit.append("peer_answered", "peers", outcome="ok",
                                     detail=f"free/busy for {who}: {len(busy)} busy block(s)")
                return {"type": "answer", "id": body.get("id"), "busy": busy,
                        "text": ("Busy: " + "; ".join(busy)) if busy else "Free the whole time."}
            if ask == "message" and "message" in peer["scopes"]:
                await self.rt.nudges.deliver("peer", f"peer:{body.get('id')}", f"Message from {who}", text, 3,
                                             {"peer_id": peer["id"]})
                return {"type": "answer", "id": body.get("id"), "text": "Delivered."}
            cur = self.rt.store.execute("INSERT INTO peer_inbox(peer_id, ts, ask_id, text) VALUES (?,?,?,?)",
                                        (peer["id"], time.time(), str(body.get("id")), text))
            inbox_id = int(cur.lastrowid)
            await self.rt.nudges.deliver("peer", f"peer-ask:{inbox_id}", f"{who} asks", text, 3,
                                         {"peer_id": peer["id"], "peer_inbox_id": inbox_id})
            return {"type": "answer", "id": body.get("id"), "queued": True,
                    "text": f"I've passed this on; {self.rt.settings.user_name or 'they'} will answer."}
        if kind == "reply":
            await self.rt.nudges.deliver("peer", f"peer-reply:{body.get('id')}:{peer['id']}",
                                         f"{who} replied", str(body.get("text", ""))[:2000], 3,
                                         {"peer_id": peer["id"]})
            return {"type": "ok"}
        if kind == "hello":
            return self._hello(body)
        raise PermissionError(f"unknown message type {kind!r}")

    async def _busy(self, start: str, end: str) -> list[str]:
        tool = self.rt.tools.get("calendar_list_events")
        if tool is None:
            return []
        try:
            st = parse_when(start) if start else datetime.now()
            en = parse_when(end, end_of_day=True) if end else st + timedelta(days=1)
        except ToolError:
            st, en = datetime.now(), datetime.now() + timedelta(days=1)
        if en - st > timedelta(days=14):
            en = st + timedelta(days=14)
        res = await tool.run({"start": st.isoformat(timespec="minutes"), "end": en.isoformat(timespec="minutes")})
        out = []
        for e in res.data or []:
            if e.get("status") == "declined":
                continue
            s0 = datetime.fromisoformat(e["start"])
            out.append(f"{s0.strftime('%a %d %b')} all day" if e.get("all_day")
                       else f"{s0.strftime('%a %d %b %H:%M')}–{e['end'][11:16]}")
        return sorted(set(out))

    async def reply(self, inbox_id: int, text: str) -> dict:
        rows = self.rt.store.query("SELECT * FROM peer_inbox WHERE id=?", (inbox_id,))
        if not rows:
            raise ToolError("That request wasn't found.")
        row = dict(rows[0])
        peer = self.get(row["peer_id"])
        if peer is None:
            raise ToolError("That agent isn't paired any more.")
        await self.send(peer, {"type": "reply", "id": row["ask_id"], "text": text})
        self.rt.store.execute("UPDATE peer_inbox SET status='answered', reply=? WHERE id=?", (text, inbox_id))
        self.rt.audit.append("peer_reply", "peers", outcome="ok", detail=f"to {peer['name']}")
        return {**row, "status": "answered", "reply": text}

    def waiting(self) -> list[dict]:
        rows = self.rt.store.query("SELECT i.*, p.name, p.owner FROM peer_inbox i JOIN peers p ON p.id=i.peer_id "
                                   "WHERE i.status='waiting' ORDER BY i.ts DESC")
        return [dict(r) for r in rows]


def peer_tools(peers: Peers) -> list[Tool]:
    async def list_peers(a: dict) -> ToolResult:
        ps = peers.list()
        if not ps:
            return ToolResult("No trusted agents yet. Pair one in Settings → Trusted agents.", "No trusted agents", [])
        lines = [f"- {p['owner'] or p['name']}'s agent ({p['name']}); allowed: {', '.join(p['scopes']) or 'nothing'}"
                 for p in ps]
        return ToolResult("Trusted agents:\n" + "\n".join(lines), f"{len(ps)} trusted agent(s)",
                          [{"name": p["owner"] or p["name"], "title": p["name"]} for p in ps])

    async def ask(a: dict) -> ToolResult:
        peer = peers.find(a.get("peer", ""))
        if not peer["verified"]:
            raise ToolError(f"{peer['owner'] or peer['name']}'s agent isn't verified yet. Compare the safety code "
                            f"({peer['safety_code']}) with them, then press 'They match' in Settings → Trusted agents.")
        kind = a.get("kind", "question")
        ask_id = secrets.token_hex(6)
        body = {"type": "ask", "id": ask_id, "kind": kind, "text": a.get("text", ""),
                "start": a.get("start", ""), "end": a.get("end", "")}
        ans = await peers.send(peer, body)
        who = f"{peer['owner'] or peer['name']}'s agent"
        text = str(ans.get("text", ""))
        note = " (They'll answer later; you'll get a nudge.)" if ans.get("queued") else ""
        return ToolResult(f"{who} answered: {text}{note}", f"{who}: {text[:80]}", {"answer": text},
                          untrusted=True)

    return [
        Tool("peers_list", "List the trusted agents (friends' and family's agents) this agent is paired with.",
             obj({}), "read", "peers", list_peers, lambda a: "List trusted agents",
             ("task", "schedule", "quick_answer", "computer_action")),
        Tool("peer_ask", "Ask a trusted friend's agent something: their free/busy times (kind=freebusy with "
             "start/end), leave them a message (kind=message), or a question their owner answers (kind=question).",
             obj({"peer": s("Whose agent: the friend's name"),
                  "kind": s("What to ask", enum=["freebusy", "message", "question"]),
                  "text": s("The message or question"),
                  "start": s("freebusy: from (ISO date/time)"), "end": s("freebusy: until (ISO date/time)")},
                 ["peer", "kind"]),
             "write", "peers", ask,
             lambda a: f"Send to {a.get('peer', '')}'s agent ({a.get('kind', 'question')}): “{a.get('text', '')[:80]}”",
             ("task", "schedule", "computer_action")),
    ]
