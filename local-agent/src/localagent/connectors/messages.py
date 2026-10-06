"""iMessage/SMS and WhatsApp: read chats from their local databases, reply safely.

Reading opens each app's own SQLite file read-only, which needs **Full Disk Access**
for the app that starts the agent (Terminal):

  iMessage   ~/Library/Messages/chat.db
  WhatsApp   ~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite

WhatsApp's file is not a public interface; its schema is checked before use and a
change is reported rather than guessed at. Sending:

  iMessage   Messages' AppleScript `send` (a write-tier tool: approval first)
  WhatsApp   the official click-to-chat link opens WhatsApp with the reply typed in;
             the user presses Send. There is no automatic WhatsApp sending.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
FDA_HELP = ("macOS blocked reading {what}. Open System Settings → Privacy & Security → Full Disk Access, "
            "turn on your Terminal app, then quit Terminal completely, reopen it and run "
            "`localagent stop` and `localagent start`.")


class SchemaChanged(ToolError):
    pass


def apple_time(value) -> datetime | None:
    """Messages stores nanoseconds since 2001 (older macOS: seconds); WhatsApp uses seconds."""
    if not value:
        return None
    v = float(value)
    if v > 1e11:
        v /= 1e9
    return (APPLE_EPOCH + timedelta(seconds=v)).astimezone().replace(tzinfo=None)


def decode_attributed_body(blob: bytes | None) -> str:
    """Recent macOS keeps message text only in `attributedBody`, an NSArchiver typedstream.
    The NSString payload follows the class name as `+` <length> <utf-8 bytes>."""
    if not blob:
        return ""
    idx = blob.find(b"NSString")
    if idx < 0:
        return ""
    p = blob.find(b"\x01\x2b", idx)
    if p < 0 or p + 3 > len(blob):
        return ""
    p += 2
    n = blob[p]
    p += 1
    if n == 0x81:
        n, p = int.from_bytes(blob[p:p + 2], "little"), p + 2
    elif n == 0x82:
        n, p = int.from_bytes(blob[p:p + 4], "little"), p + 4
    return blob[p:p + n].decode("utf-8", errors="replace")


def norm_handle(value: str) -> str:
    """Comparable form of a phone number or email (last 10 digits, or lower-case email)."""
    v = (value or "").strip().lower()
    if "@" in v and not v.endswith(("@s.whatsapp.net", "@c.us")):
        return v
    digits = re.sub(r"\D", "", v.split("@")[0])
    return digits[-10:] if len(digits) >= 7 else v


def open_ro(path: Path, what: str) -> sqlite3.Connection:
    try:
        path.stat()
    except PermissionError as exc:
        raise ToolError(FDA_HELP.format(what=what)) from exc
    except FileNotFoundError as exc:
        raise ToolError(f"{what} wasn't found at {path}.") from exc
    try:
        db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return db
    except sqlite3.OperationalError as exc:
        if "unable to open" in str(exc) or "authorization" in str(exc) or "not authorized" in str(exc):
            raise ToolError(FDA_HELP.format(what=what)) from exc
        raise ToolError(f"Couldn't read {what}: {exc}") from exc


def present(path: Path) -> bool:
    """True if the file exists, including when macOS hides it behind Full Disk Access."""
    try:
        path.stat()
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


class ContactNames:
    """Phone/email → name, read from the Contacts database (also needs Full Disk Access).
    Best effort: unknown handles are shown as the number or address."""

    TTL = 600

    def __init__(self, folder: Path):
        self.folder = folder
        self._map: dict[str, str] = {}
        self._loaded = 0.0

    def _load(self) -> None:
        self._map, self._loaded = {}, time.time()
        try:
            files = [self.folder / "AddressBook-v22.abcddb",
                     *sorted(self.folder.glob("Sources/*/AddressBook-v22.abcddb"))]
        except OSError:
            return
        for f in files:
            try:
                db = open_ro(f, "Contacts")
            except ToolError:
                continue
            try:
                names = {}
                for r in db.execute("SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION FROM ZABCDRECORD"):
                    name = " ".join(x for x in (r["ZFIRSTNAME"], r["ZLASTNAME"]) if x) or r["ZORGANIZATION"]
                    if name:
                        names[r["Z_PK"]] = name
                for r in db.execute("SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER"):
                    if r["ZOWNER"] in names and r["ZFULLNUMBER"]:
                        self._map.setdefault(norm_handle(r["ZFULLNUMBER"]), names[r["ZOWNER"]])
                for r in db.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS"):
                    if r["ZOWNER"] in names and r["ZADDRESS"]:
                        self._map.setdefault(norm_handle(r["ZADDRESS"]), names[r["ZOWNER"]])
            except sqlite3.Error:
                pass
            finally:
                db.close()

    def name(self, handle: str) -> str | None:
        if time.time() - self._loaded > self.TTL:
            self._load()
        return self._map.get(norm_handle(handle))


def _thread(app: str, tid, name: str, handle: str, group: bool, text: str, from_me: bool,
            at: datetime | None, unread: int, **extra) -> dict:
    return {"id": f"{app.lower()}:{tid}", "app": app, "name": name, "handle": handle, "group": group,
            "last_text": " ".join((text or "").split())[:300], "last_from_me": from_me,
            "last_at": at.isoformat(timespec="minutes") if at else None, "unread": unread,
            "needs_reply": not from_me, **extra}


class IMessages:
    def __init__(self, path: Path, names: ContactNames):
        self.path, self.names = path, names

    def _db(self) -> sqlite3.Connection:
        return open_ro(self.path, "your Messages history")

    @staticmethod
    def _text(row) -> str:
        text = row["text"] or decode_attributed_body(row["attributedBody"])
        return text.replace("￼", "").strip() or "[attachment]"

    def _label(self, handle: str) -> str:
        return self.names.name(handle) or handle

    def threads(self, scan: int = 300) -> list[dict]:
        db = self._db()
        try:
            mcols = columns(db, "message")
            if not {"text", "is_from_me", "date", "handle_id"} <= mcols:
                raise SchemaChanged("The Messages database format isn't recognised.")
            body = "m.attributedBody" if "attributedBody" in mcols else "NULL"
            not_reaction = ("AND (m2.associated_message_type IS NULL OR m2.associated_message_type=0)"
                            if "associated_message_type" in mcols else "")
            rows = db.execute(f"""
                SELECT c.ROWID AS cid, c.guid, c.chat_identifier, c.display_name, c.style,
                       c.service_name, m.text, {body} AS attributedBody, m.is_from_me, m.date,
                       h.id AS handle
                FROM chat c
                JOIN message m ON m.ROWID = (
                    SELECT MAX(j2.message_id) FROM chat_message_join j2
                    JOIN message m2 ON m2.ROWID = j2.message_id
                    WHERE j2.chat_id = c.ROWID {not_reaction})
                LEFT JOIN handle h ON h.ROWID = m.handle_id
                ORDER BY m.date DESC LIMIT ?""", (scan,)).fetchall()
            unread = dict(db.execute("""
                SELECT j.chat_id, COUNT(*) FROM chat_message_join j JOIN message m ON m.ROWID=j.message_id
                WHERE m.is_from_me=0 AND m.is_read=0 GROUP BY j.chat_id""").fetchall()) \
                if "is_read" in mcols else {}
            members: dict[int, list[str]] = {}
            for r in db.execute("SELECT chj.chat_id, h.id FROM chat_handle_join chj "
                                "JOIN handle h ON h.ROWID = chj.handle_id"):
                members.setdefault(r[0], []).append(r[1])
        except sqlite3.Error as exc:
            raise SchemaChanged(f"Couldn't read the Messages database: {exc}") from exc
        finally:
            db.close()
        out = []
        for r in rows:
            people = members.get(r["cid"], [])
            group = r["style"] == 43 or len(people) > 1
            if group:
                name = r["display_name"] or ", ".join(self._label(p) for p in people[:4]) or "Group chat"
            else:
                handle = people[0] if people else r["chat_identifier"]
                name = self._label(handle)
            sender = "" if r["is_from_me"] or not group else self._label(r["handle"] or "") + ": "
            ident = r["chat_identifier"] or ""
            # Short codes (banks, delivery, 2FA) can't be answered: never "waiting on your reply".
            automated = not group and ident.isdigit() and len(ident) < 7
            out.append(_thread(
                "iMessage", r["cid"], name, people[0] if len(people) == 1 else r["chat_identifier"],
                group, sender + self._text(r), bool(r["is_from_me"]), apple_time(r["date"]),
                int(unread.get(r["cid"], 0)), guid=r["guid"], service=r["service_name"] or "iMessage"))
            if automated:
                out[-1]["needs_reply"] = False
        return out

    def thread(self, tid: int) -> dict | None:
        return next((t for t in self.threads(2000) if t["id"] == f"imessage:{tid}"), None)

    def max_rowid(self) -> int:
        db = self._db()
        try:
            return int(db.execute("SELECT COALESCE(MAX(ROWID), 0) FROM message").fetchone()[0])
        finally:
            db.close()

    def new_since(self, rowid: int, limit: int = 50) -> list[dict]:
        """Messages added after `rowid` (oldest first), with their chat, for the iMessage channel."""
        db = self._db()
        try:
            body = "m.attributedBody" if "attributedBody" in columns(db, "message") else "NULL"
            rows = db.execute(f"""
                SELECT m.ROWID AS rowid, m.text, {body} AS attributedBody, m.is_from_me, m.date,
                       h.id AS handle, c.ROWID AS cid, c.guid, c.chat_identifier, c.style
                FROM message m
                JOIN chat_message_join j ON j.message_id = m.ROWID
                JOIN chat c ON c.ROWID = j.chat_id
                LEFT JOIN handle h ON h.ROWID = m.handle_id
                WHERE m.ROWID > ? ORDER BY m.ROWID LIMIT ?""", (rowid, limit)).fetchall()
        except sqlite3.Error as exc:
            raise SchemaChanged(f"Couldn't read the Messages database: {exc}") from exc
        finally:
            db.close()
        return [{"rowid": r["rowid"], "text": (r["text"] or decode_attributed_body(r["attributedBody"])).strip(),
                 "from_me": bool(r["is_from_me"]), "handle": r["handle"] or "", "chat_id": r["cid"],
                 "guid": r["guid"], "chat_identifier": r["chat_identifier"] or "", "group": r["style"] == 43}
                for r in rows]

    def messages(self, tid: int, limit: int) -> list[dict]:
        db = self._db()
        try:
            body = "m.attributedBody" if "attributedBody" in columns(db, "message") else "NULL"
            rows = db.execute(f"""
                SELECT m.text, {body} AS attributedBody, m.is_from_me, m.date, h.id AS handle
                FROM chat_message_join j JOIN message m ON m.ROWID = j.message_id
                LEFT JOIN handle h ON h.ROWID = m.handle_id
                WHERE j.chat_id = ? ORDER BY m.date DESC LIMIT ?""", (tid, limit)).fetchall()
        except sqlite3.Error as exc:
            raise SchemaChanged(f"Couldn't read the Messages database: {exc}") from exc
        finally:
            db.close()
        return [{"from_me": bool(r["is_from_me"]),
                 "sender": "You" if r["is_from_me"] else self._label(r["handle"] or ""),
                 "at": (apple_time(r["date"]) or datetime.now()).isoformat(timespec="minutes"),
                 "text": self._text(r)} for r in reversed(rows)]


class WhatsApp:
    SESSION_COLS = {"Z_PK", "ZCONTACTJID", "ZPARTNERNAME"}
    MESSAGE_COLS = {"Z_PK", "ZCHATSESSION", "ZISFROMME", "ZTEXT", "ZMESSAGEDATE"}

    def __init__(self, path: Path, names: ContactNames):
        self.path, self.names = path, names

    def _db(self) -> sqlite3.Connection:
        db = open_ro(self.path, "WhatsApp's chat history")
        try:
            ok = (self.SESSION_COLS <= columns(db, "ZWACHATSESSION")
                  and self.MESSAGE_COLS <= columns(db, "ZWAMESSAGE"))
        except sqlite3.Error:
            ok = False
        if not ok:
            db.close()
            raise SchemaChanged("WhatsApp changed how it stores chats on this Mac, so they can't be read "
                                "right now. Replying through WhatsApp links still works.")
        return db

    def threads(self, scan: int = 300) -> list[dict]:
        db = self._db()
        try:
            scols = columns(db, "ZWACHATSESSION")
            unread = "s.ZUNREADCOUNT" if "ZUNREADCOUNT" in scols else "0"
            hidden = "AND COALESCE(s.ZREMOVED, 0) = 0" if "ZREMOVED" in scols else ""
            rows = db.execute(f"""
                SELECT s.Z_PK AS sid, s.ZCONTACTJID AS jid, s.ZPARTNERNAME AS partner, {unread} AS unread,
                       m.ZTEXT AS text, m.ZISFROMME AS from_me, m.ZMESSAGEDATE AS date
                FROM ZWACHATSESSION s
                JOIN ZWAMESSAGE m ON m.Z_PK = (SELECT m2.Z_PK FROM ZWAMESSAGE m2
                     WHERE m2.ZCHATSESSION = s.Z_PK ORDER BY m2.ZMESSAGEDATE DESC LIMIT 1)
                WHERE s.ZCONTACTJID IS NOT NULL AND s.ZCONTACTJID NOT LIKE '%broadcast%' {hidden}
                ORDER BY m.ZMESSAGEDATE DESC LIMIT ?""", (scan,)).fetchall()
        except sqlite3.Error as exc:
            raise SchemaChanged(f"Couldn't read WhatsApp's chat history: {exc}") from exc
        finally:
            db.close()
        out = []
        for r in rows:
            jid = r["jid"]
            group = jid.endswith("@g.us")
            name = r["partner"] or (None if group else self.names.name(jid)) or jid.split("@")[0]
            out.append(_thread("WhatsApp", r["sid"], name, jid, group, r["text"] or "[media]",
                               bool(r["from_me"]), apple_time(r["date"]), int(r["unread"] or 0)))
        return out

    def thread(self, tid: int) -> dict | None:
        return next((t for t in self.threads(2000) if t["id"] == f"whatsapp:{tid}"), None)

    def messages(self, tid: int, limit: int) -> list[dict]:
        db = self._db()
        try:
            partner = db.execute("SELECT ZPARTNERNAME, ZCONTACTJID FROM ZWACHATSESSION WHERE Z_PK=?",
                                 (tid,)).fetchone()
            rows = db.execute("""SELECT ZTEXT, ZISFROMME, ZMESSAGEDATE FROM ZWAMESSAGE
                                 WHERE ZCHATSESSION=? ORDER BY ZMESSAGEDATE DESC LIMIT ?""",
                              (tid, limit)).fetchall()
        except sqlite3.Error as exc:
            raise SchemaChanged(f"Couldn't read WhatsApp's chat history: {exc}") from exc
        finally:
            db.close()
        other = (partner["ZPARTNERNAME"] if partner else None) or "Them"
        if partner and partner["ZCONTACTJID"].endswith("@g.us"):
            other = "Someone in the group"
        return [{"from_me": bool(r["ZISFROMME"]), "sender": "You" if r["ZISFROMME"] else other,
                 "at": (apple_time(r["ZMESSAGEDATE"]) or datetime.now()).isoformat(timespec="minutes"),
                 "text": r["ZTEXT"] or "[media]"} for r in reversed(rows)]


def whatsapp_link(jid: str, text: str) -> str:
    phone = re.sub(r"\D", "", jid.split("@")[0])
    return f"whatsapp://send?phone={phone}&text={quote(text)}"


def imessage_targets(guid: str) -> list[str]:
    """Chat ids to try with Messages' AppleScript. Newer macOS stores 'any;-;…' in chat.db,
    while AppleScript may expect the service prefix."""
    if not guid:
        return []
    rest = guid.split(";", 1)[1] if ";" in guid else guid
    out = [guid] + [f"{svc};{rest}" for svc in ("iMessage", "SMS", "any")]
    return list(dict.fromkeys(out))


def _ago(iso: str | None, now: datetime) -> str:
    if not iso:
        return ""
    delta = now - datetime.fromisoformat(iso)
    if delta.days:
        return f"{delta.days}d ago"
    hours = int(delta.total_seconds() // 3600)
    return f"{hours}h ago" if hours else f"{max(0, int(delta.total_seconds() // 60))}m ago"


def messages_tools(runner, imessage: IMessages | None, whatsapp: WhatsApp | None,
                   include_groups: bool = False) -> list[Tool]:
    sources = {k: v for k, v in (("imessage", imessage), ("whatsapp", whatsapp)) if v is not None}
    apps = ["all", *sources]

    def source_for(thread_id: str):
        app, _, tid = str(thread_id).partition(":")
        src = sources.get(app.lower())
        if src is None or not tid.isdigit():
            raise ToolError(f"Unknown chat '{thread_id}'. Use an id from messages_list, like imessage:12.")
        return app.lower(), src, int(tid)

    async def list_threads(a: dict) -> ToolResult:
        now = datetime.now()
        wanted = [a.get("app", "all")] if a.get("app", "all") != "all" else list(sources)
        groups = a.get("include_groups", include_groups)
        query = (a.get("query") or "").lower()
        max_days = a.get("max_days", 0)
        min_minutes = a.get("min_minutes", 0)
        threads, notes, errors = [], [], []
        for app in wanted:
            try:
                threads += await asyncio.to_thread(sources[app].threads)
            except ToolError as exc:
                errors.append(exc)
                notes.append(f"{app}: {exc}")
        if errors and len(errors) == len(wanted):
            raise errors[0]
        out = []
        for t in sorted(threads, key=lambda t: t["last_at"] or "", reverse=True):
            if t["group"] and not groups:
                continue
            if query and query not in t["name"].lower() and query not in t["handle"].lower():
                continue
            at = datetime.fromisoformat(t["last_at"]) if t["last_at"] else None
            if max_days and (at is None or now - at > timedelta(days=max_days)):
                continue
            if a.get("needs_reply"):
                if not t["needs_reply"] or (at and now - at < timedelta(minutes=min_minutes)):
                    continue
            if a.get("unread_only") and not t["unread"]:
                continue
            out.append(t)
            if len(out) >= a.get("limit", 10):
                break
        note = ("\n" + "\n".join(f"(Couldn't read {n})" for n in notes)) if notes else ""
        if not out:
            return ToolResult("No matching chats." + note, "No matching chats", [])
        lines = [f"- [{t['id']}] {t['app']} · {t['name']}{' (group)' if t['group'] else ''} · "
                 f"{_ago(t['last_at'], now)}{' · ' + str(t['unread']) + ' unread' if t['unread'] else ''}"
                 f"{' · waiting on your reply' if t['needs_reply'] else ''}\n  "
                 f"{'You: ' if t['last_from_me'] else ''}{t['last_text'][:160]}" for t in out]
        label = "waiting on your reply" if a.get("needs_reply") else "chat(s)"
        return ToolResult("Recent chats (newest first):\n" + "\n".join(lines) + note,
                          f"Found {len(out)} {label}", out, untrusted=True)

    async def read_thread(a: dict) -> ToolResult:
        app, src, tid = source_for(a["thread"])
        msgs = await asyncio.to_thread(src.messages, tid, a.get("limit", 20))
        if not msgs:
            return ToolResult("That chat has no messages.", "Empty chat", [])
        lines = [f"[{m['at'].replace('T', ' ')}] {m['sender']}: {m['text']}" for m in msgs]
        return ToolResult(f"Chat {a['thread']} (oldest first):\n" + "\n".join(lines),
                          f"Read {len(msgs)} message(s)", msgs, untrusted=True)

    async def send_imessage(a: dict) -> ToolResult:
        text = a["text"].strip()
        if not text:
            raise ToolError("The message is empty.")
        _, src, tid = source_for(a["thread"])
        t = await asyncio.to_thread(src.thread, tid)
        if t is None:
            raise ToolError("That chat wasn't found.")
        await runner.run("messages_send", [text, "" if t["group"] else t["handle"],
                                           *imessage_targets(t.get("guid", ""))])
        return ToolResult(f"Sent the iMessage to {t['name']}.", f"Sent to {t['name']}",
                          {"to": t["name"], "text": text})

    async def open_whatsapp(a: dict) -> ToolResult:
        text = a["text"].strip()
        _, src, tid = source_for(a["thread"])
        t = await asyncio.to_thread(src.thread, tid)
        if t is None:
            raise ToolError("That chat wasn't found.")
        if t["handle"].endswith("@lid"):
            raise ToolError("WhatsApp doesn't show this contact's phone number on the Mac, so the chat can't "
                            "be opened by link. Show the user the reply text so they can paste it.")
        if t["group"]:
            raise ToolError("WhatsApp links can't open a group chat. Show the user the reply text so "
                            "they can paste it into the group themselves.")
        await runner.run("open_url", [whatsapp_link(t["handle"], text)])
        return ToolResult(f"Opened WhatsApp with the reply to {t['name']} typed in. The user reviews it "
                          "and presses Send themselves.", f"Reply ready in WhatsApp for {t['name']}",
                          {"to": t["name"], "text": text})

    def name_of(thread_id: str) -> str:
        try:
            _, src, tid = source_for(thread_id)
            t = src.thread(tid)
            return t["name"] if t else thread_id
        except Exception:  # noqa: BLE001 - only used for the approval card text
            return thread_id

    reply = obj({"thread": s("Chat id from messages_list, e.g. imessage:12"),
                 "text": s("The exact message to send")}, ["thread", "text"])
    intents = ("task", "computer_action", "quick_answer", "schedule")
    tools = [
        Tool("messages_list",
             "List recent iMessage/SMS and WhatsApp chats; filter to chats waiting on the user's reply.",
             obj({"app": s("Which app", enum=apps), "needs_reply": {"type": "boolean",
                  "description": "Only chats whose last message is from the other person"},
                  "unread_only": {"type": "boolean", "description": "Only chats with unread messages"},
                  "query": s("Part of a contact name, number or address"),
                  "include_groups": {"type": "boolean", "description": "Include group chats"},
                  "max_days": i("Only chats active in the last N days"),
                  "min_minutes": i("With needs_reply: last message at least this many minutes old"),
                  "limit": i("Max chats (default 10)")}),
             "read", "messages", list_threads, lambda a: "Look at your messages", intents),
        Tool("messages_read", "Read the latest messages in one chat (id from messages_list).",
             obj({"thread": s("Chat id from messages_list, e.g. whatsapp:7"),
                  "limit": i("How many recent messages (default 20)")}, ["thread"]),
             "read", "messages", read_thread, lambda a: "Read a chat", intents),
    ]
    if "imessage" in sources:
        tools.append(Tool(
            "imessage_send", "Send an iMessage/SMS reply in an existing chat. The app asks the user first.",
            reply, "write", "messages", send_imessage,
            lambda a: f"Send iMessage to {name_of(a.get('thread', ''))}: “{a.get('text', '')}”",
            ("task", "computer_action")))
    if "whatsapp" in sources:
        tools.append(Tool(
            "whatsapp_open_draft",
            "Open WhatsApp with a reply typed into a one-to-one chat; the user presses Send.",
            reply, "draft", "messages", open_whatsapp,
            lambda a: f"Open WhatsApp reply to {name_of(a.get('thread', ''))}", ("task", "computer_action")))
    return tools
