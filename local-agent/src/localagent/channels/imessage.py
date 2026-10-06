"""Talk to the agent from your iPhone over iMessage.

Two set-ups:
  self      (default) Text yourself from your iPhone, starting with the agent's name
            ("Ari, what's on today?"). The Mac sees it in your note-to-self chat and replies
            there; replies start with 🤖 so it never answers itself.
  account   The agent has its own Apple ID signed into Messages on this Mac. Messages
            holds one Apple ID at a time, so this suits a spare Mac (your own chats, and
            the Messages connector, then aren't on it). Only `imessage_owner_handles` are
            listened to.

New messages are read from chat.db (read-only, the same Full Disk Access as the Messages
connector), run through the normal chat turn (decisions, memory, tools, approvals), and
the reply is sent back with Messages. Actions that need approval are answered by replying
"yes", "yes 1h", "always" or "no".
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

from ..connectors.messages import IMessages, imessage_targets, norm_handle
from ..policy.engine import ApprovalError
from ..tools.base import ToolError

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)

MARK = "🤖 "
MAX_CHUNK = 1500
RATE_PER_MIN = 12
YES = re.compile(r"^\s*(yes|y|ok|okay|approve|go ahead|👍)[\s,.!]*(?P<scope>once|1 ?h|hour|day|24 ?h|"
                 r"session|always)?[\s.!]*$", re.IGNORECASE)
NO = re.compile(r"^\s*(no|n|nope|decline|cancel|stop|👎)[\s.!]*$", re.IGNORECASE)
SCOPES = {"once": "once", "1h": "hour", "1 h": "hour", "hour": "hour", "day": "day", "24h": "day",
          "24 h": "day", "session": "session", "always": "always"}


def plain(text: str) -> str:
    """Markdown → plain text for a text message."""
    text = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), text, flags=re.S)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunks(text: str, size: int = MAX_CHUNK) -> list[str]:
    out = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > size // 2 else size
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return out + ([text] if text else [])


class IMessageChannel:
    def __init__(self, rt: "Runtime", store: IMessages, runner):
        self.rt, self.store, self.runner = rt, store, runner
        self.recent: list[float] = []
        self.status = "stopped"
        self.last_error = ""
        self._seen_self: dict[str, float] = {}

    # ── settings ──────────────────────────────────────────────────────────
    @property
    def owners(self) -> set[str]:
        return {norm_handle(h) for h in self.rt.settings.imessage_owner_handles.split(",") if h.strip()}

    @property
    def mode(self) -> str:
        return self.rt.settings.imessage_channel_mode

    def _prefix(self) -> re.Pattern:
        name = re.escape(self.rt.settings.agent_name.lower())
        return re.compile(rf"^\s*(hey\s+|hi\s+)?{name}\b[\s,:;.!-]*", re.IGNORECASE)

    # ── which messages are for the agent ──────────────────────────────────
    def accept(self, m: dict) -> str | None:
        """The command text if this message is for the agent, else None."""
        text = m["text"].strip()
        if not text or text.startswith(MARK.strip()) or m["group"]:
            return None
        if self.mode == "self":
            # A message you sent to your own number/address, starting with the agent's name.
            if not m["from_me"] or norm_handle(m["chat_identifier"]) not in self.owners:
                return None
            match = self._prefix().match(text)
            if not match:
                return None
            command = text[match.end():].strip()
            # The same message can show up twice in a self-chat (sent + received copy).
            now = time.time()
            self._seen_self = {k: v for k, v in self._seen_self.items() if now - v < 120}
            if command in self._seen_self:
                return None
            self._seen_self[command] = now
            return command or None
        if m["from_me"]:
            return None
        if norm_handle(m["handle"]) not in self.owners:
            self.rt.audit.append("channel_ignored", "imessage", outcome="ignored",
                                 detail=f"message from {m['handle'] or 'unknown'} (not an owner)")
            return None
        return text

    # ── polling ───────────────────────────────────────────────────────────
    def _last(self) -> int | None:
        v = self.rt.store.meta_get("imessage_channel_last")
        return int(v) if v else None

    async def poll_once(self) -> int:
        """Process new messages; returns how many were for the agent."""
        last = self._last()
        if last is None:   # first start: never answer old messages
            self.rt.store.meta_set("imessage_channel_last", str(await asyncio.to_thread(self.store.max_rowid)))
            return 0
        rows = await asyncio.to_thread(self.store.new_since, last)
        handled = 0
        for m in rows:
            self.rt.store.meta_set("imessage_channel_last", str(m["rowid"]))
            command = self.accept(m)
            if command is None:
                continue
            now = time.time()
            self.recent = [t for t in self.recent if now - t < 60]
            if len(self.recent) >= RATE_PER_MIN:
                continue
            self.recent.append(now)
            handled += 1
            reply = await self.respond(command)
            await self.send(m, reply)
        return handled

    async def loop(self) -> None:
        self.status = "running"
        delay = 3.0
        while True:
            try:
                if self.rt.settings.enable_imessage_channel and self.owners:
                    await self.poll_once()
                    self.status, self.last_error, delay = "running", "", 3.0
                else:
                    self.status = "off" if not self.rt.settings.enable_imessage_channel else "no owner set"
            except ToolError as exc:
                self.status, self.last_error, delay = "error", str(exc), min(delay * 2, 60)
                log.warning("iMessage channel: %s", exc)
            except Exception as exc:  # noqa: BLE001 - keep the channel alive
                self.status, self.last_error, delay = "error", f"{exc.__class__.__name__}: {exc}", min(delay * 2, 60)
                log.exception("iMessage channel failed")
            await asyncio.sleep(delay)

    # ── replying ──────────────────────────────────────────────────────────
    def _pending(self) -> dict | None:
        v = self.rt.store.meta_get("imessage_channel_approval")
        ap = self.rt.policy.get(int(v), with_state=True) if v else None
        return ap if ap and ap["status"] == "pending" else None

    async def respond(self, text: str) -> str:
        from ..agent.chat import handle_turn, resume_after_decision

        pending = self._pending()
        if pending and (YES.match(text) or NO.match(text)):
            approve = bool(YES.match(text))
            scope = SCOPES.get((YES.match(text).group("scope") or "once").lower().replace("  ", " "), "once") \
                if approve else "once"
            if pending["tier"] == "danger":
                scope = "once"
            try:
                ap = self.rt.policy.decide(pending["id"], approve, scope)
            except ApprovalError as exc:
                return str(exc)
            self.rt.audit.append("approval_" + ap["status"], ap["tool"], ap["tier"], ap["args"], ap["status"],
                                 f"scope={ap['scope']} (by iMessage)" if ap["scope"] else "by iMessage",
                                 ap["id"], ap["task_id"])
            self.rt.store.meta_set("imessage_channel_approval", "")
            return await self._collect(resume_after_decision(self.rt, ap, approve),
                                       "Done." if approve else "OK, I won't do that.")
        return await self._collect(handle_turn(self.rt, text), "")

    async def _collect(self, events, default: str) -> str:
        parts: list[str] = []
        notes: list[str] = []
        async for ev in events:
            t = ev.get("type")
            if t == "token":
                parts.append(ev["text"])
            elif t == "reset":
                parts.clear()
            elif t == "approval_required":
                ap = ev["approval"]
                self.rt.store.meta_set("imessage_channel_approval", str(ap["id"]))
                how = ("Reply yes or no." if ap["tier"] == "danger"
                       else "Reply yes, yes 1h, always, or no.")
                preview = (ap.get("preview") or "").strip()
                if len(preview) > 600:
                    preview = preview[:600] + "… (open the app to see all of it)"
                notes.append(f"Needs your OK: {ap['summary']}\nWhy: {ap.get('reason') or ''}"
                             + (f"\n---\n{preview}\n---" if preview else "") + f"\n{how}")
            elif t == "error":
                notes.append(f"Problem: {ev['message']}")
        return plain("".join(parts).strip() or default) + ("\n\n" + "\n\n".join(notes) if notes else "")

    async def send(self, m: dict, text: str) -> None:
        text = text.strip() or "…"
        handle = "" if m["group"] else (m["chat_identifier"] if self.mode == "self" else m["handle"])
        for part in chunks(text):
            body = (MARK + part) if self.mode == "self" else part
            await self.runner.run("messages_send", [body, handle, *imessage_targets(m["guid"])])

    async def forward_test(self, owner: str) -> None:
        name = self.rt.settings.agent_name
        text = (f"Hi, it's {name}. Text me here any time." if self.mode == "account"
                else f"Hi, it's {name}. Text yourself starting with “{name}, …” to reach me.")
        await self.runner.run("messages_send", [(MARK + text) if self.mode == "self" else text, owner])

    async def forward(self, kind: str, title: str, body: str) -> None:
        """Send a nudge or the morning brief to the owner (if set up and switched on)."""
        s = self.rt.settings
        if not (s.enable_imessage_channel and s.imessage_forward_nudges and self.owners):
            return
        owner = s.imessage_owner_handles.split(",")[0].strip()
        text = plain(f"{title}\n{body}".strip())
        for part in chunks(text):
            await self.runner.run("messages_send", [(MARK + part) if self.mode == "self" else part, owner])
