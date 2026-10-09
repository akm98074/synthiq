"""Apple Mail without scripting Mail: read Mail's own index (`Envelope Index`), read-only.

Asking Mail.app over AppleScript for "messages of inbox whose …" makes Mail build an object for
every message in every inbox, and `content of` loads whole messages; Mail keeps much of that in
memory, so a check every 30 minutes grew it to tens of GB. This reads the same facts (subject,
sender, date, read / replied, a short preview) from Mail's SQLite index, the way the Messages
connector reads chat.db: read-only, Full Disk Access, Mail.app not involved. A message is read in
full from its `.emlx` file. If the index looks different from what we expect (another macOS
version), `MailIndexUnavailable` is raised and the caller falls back to a small AppleScript.

Message ids are the index's ROWIDs, which are also Mail's AppleScript message ids.
"""
from __future__ import annotations

import email
import email.policy
import html
import re
import sqlite3
import time
from pathlib import Path

from ..tools.base import ToolError
from .messages import columns, open_ro, present

MAC_EPOCH = 978307200          # 2001-01-01: some Mail versions store dates in Mac absolute time
ANSWERED = 1 << 2              # Mail's message flags: read 1<<0, deleted 1<<1, answered 1<<2
TEXT_LIMIT = 4000


class MailIndexUnavailable(Exception):
    """The index can't be used here; use the AppleScript fallback."""


class MailIndex:
    def __init__(self, mail_dir: Path):
        self.mail_dir = Path(mail_dir).expanduser()
        self._shape: dict | None = None
        self._why = ""

    # ── locating and checking ─────────────────────────────────────────────
    def version_dir(self) -> Path | None:
        try:
            versions = sorted((p for p in self.mail_dir.glob("V*") if p.name[1:].isdigit()),
                              key=lambda p: int(p.name[1:]))
        except OSError:
            return None
        return versions[-1] if versions else None

    def path(self) -> Path | None:
        v = self.version_dir()
        return v / "MailData" / "Envelope Index" if v else None

    def _open(self) -> tuple[sqlite3.Connection, dict]:
        p = self.path()
        if p is None or not present(p):
            raise MailIndexUnavailable("Mail's index wasn't found (is Apple Mail set up?)")
        try:
            db = open_ro(p, "Mail's index")
        except ToolError as exc:
            raise MailIndexUnavailable(str(exc)) from exc
        try:
            shape = self._check(db)
        except MailIndexUnavailable:
            db.close()
            raise
        return db, shape

    def _check(self, db: sqlite3.Connection) -> dict:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = {"messages", "subjects", "addresses", "mailboxes"} - tables
        if missing:
            raise MailIndexUnavailable(f"Mail's index has no {', '.join(sorted(missing))} table")
        cols = columns(db, "messages")
        need = {"subject", "sender", "date_received", "mailbox"} - cols
        if need:
            raise MailIndexUnavailable(f"Mail's index has no {', '.join(sorted(need))} column")
        if "read" not in cols and "flags" not in cols:
            raise MailIndexUnavailable("Mail's index has no read/flags column")
        if "url" not in columns(db, "mailboxes") or "address" not in columns(db, "addresses"):
            raise MailIndexUnavailable("Mail's index has an unexpected mailbox/address layout")
        latest = db.execute("SELECT MAX(date_received) FROM messages").fetchone()[0] or 0
        return {"read": "read" in cols, "flags": "flags" in cols, "deleted": "deleted" in cols,
                "summary": "summary" in cols and "summaries" in tables,
                "comment": "comment" in columns(db, "addresses"),
                # Unix seconds today are ~1.8e9; Mac absolute time is ~8e8.
                "offset": MAC_EPOCH if 0 < latest < 1_200_000_000 else 0}

    def status(self) -> tuple[bool, str]:
        try:
            db, _ = self._open()
            db.close()
            return True, "reads Mail's index"
        except MailIndexUnavailable as exc:
            return False, str(exc)

    # ── queries ───────────────────────────────────────────────────────────
    def _select(self, shape: dict) -> str:
        sender = ("CASE WHEN a.comment IS NOT NULL AND a.comment != '' THEN a.comment || ' <' || a.address || '>' "
                  "ELSE a.address END") if shape["comment"] else "a.address"
        read = "m.read" if shape["read"] else "(m.flags & 1)"
        replied = f"(m.flags & {ANSWERED})" if shape["flags"] else "0"
        summary = "COALESCE(su.summary, '')" if shape["summary"] else "''"
        join_summary = "LEFT JOIN summaries su ON su.ROWID = m.summary" if shape["summary"] else ""
        deleted = "AND COALESCE(m.deleted, 0) = 0" if shape["deleted"] else ""
        return (f"SELECT m.ROWID AS id, COALESCE(s.subject, '') AS subject, COALESCE({sender}, '') AS sender, "
                f"m.date_received + {shape['offset']} AS received, {read} AS is_read, {replied} AS replied, "
                f"{summary} AS snippet FROM messages m "
                "LEFT JOIN subjects s ON s.ROWID = m.subject LEFT JOIN addresses a ON a.ROWID = m.sender "
                f"JOIN mailboxes mb ON mb.ROWID = m.mailbox {join_summary} "
                f"WHERE (LOWER(mb.url) LIKE '%/inbox' OR LOWER(mb.url) LIKE '%/inbox/') {deleted}")

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {"id": int(r["id"]), "subject": r["subject"], "from": r["sender"],
                "received": float(r["received"] or 0), "read": bool(r["is_read"]),
                "replied": bool(r["replied"]), "snippet": " ".join(str(r["snippet"] or "").split())[:200]}

    def recent(self, query: str = "", limit: int = 10, unread_only: bool = False) -> list[dict]:
        db, shape = self._open()
        try:
            sql, args = self._select(shape), []
            if unread_only:
                sql += " AND NOT (" + ("m.read" if shape["read"] else "(m.flags & 1)") + ")"
            if query:
                sql += " AND (s.subject LIKE ? OR a.address LIKE ?" + (" OR a.comment LIKE ?" if shape["comment"] else "") + ")"
                like = f"%{query}%"
                args += [like, like] + ([like] if shape["comment"] else [])
            sql += " ORDER BY m.date_received DESC LIMIT ?"
            return [self._row(r) for r in db.execute(sql, (*args, max(1, min(int(limit), 100))))]
        finally:
            db.close()

    def followups(self, min_days: float = 1, max_days: float = 7, limit: int = 15, now: float | None = None) -> list[dict]:
        db, shape = self._open()
        if not shape["flags"]:
            db.close()
            raise MailIndexUnavailable("Mail's index doesn't record replies")
        try:
            now = now or time.time()
            newest = now - float(min_days) * 86400 - shape["offset"]
            oldest = now - float(max_days) * 86400 - shape["offset"]
            sql = (self._select(shape) + f" AND (m.flags & {ANSWERED}) = 0 AND m.date_received BETWEEN ? AND ?"
                   " ORDER BY m.date_received DESC LIMIT ?")
            return [self._row(r) for r in db.execute(sql, (oldest, newest, max(1, min(int(limit), 100))))]
        finally:
            db.close()

    def read(self, rowid: int) -> dict | None:
        """The message in full from its .emlx file; None if the file isn't on this Mac."""
        db, shape = self._open()
        try:
            row = db.execute(self._select(shape) + " AND m.ROWID = ?", (int(rowid),)).fetchone()
            box = db.execute("SELECT mb.url FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox "
                             "WHERE m.ROWID = ?", (int(rowid),)).fetchone()
        finally:
            db.close()
        if row is None:
            return None
        path = self._emlx(int(rowid), box["url"] if box else "")
        if path is None:
            return None
        msg = self._row(row)
        msg["text"] = emlx_text(path)[:TEXT_LIMIT]
        return msg

    def _emlx(self, rowid: int, url: str) -> Path | None:
        v = self.version_dir()
        if v is None:
            return None
        # Mail stores message 123456 as …/<Mailbox>.mbox/<uuid>/Data/3/2/1/Messages/123456.emlx
        sub = "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""
        names = (f"{rowid}.emlx", f"{rowid}.partial.emlx")
        m = re.match(r"^[a-z]+://([^/]+)/(.+?)/?$", url or "")
        roots = [v / m.group(1)] if m else []
        for root in roots:
            for mbox in root.glob("*.mbox"):
                if mbox.name.lower() != m.group(2).split("/")[-1].lower() + ".mbox":
                    continue
                for data in mbox.glob("*/Data"):
                    for name in names:
                        p = data / sub / "Messages" / name if sub else data / "Messages" / name
                        if p.exists():
                            return p
        return None


def emlx_text(path: Path) -> str:
    """Plain text of an .emlx file: a byte count line, then the RFC 822 message."""
    raw = path.read_bytes()
    first, _, rest = raw.partition(b"\n")
    try:
        body = rest[:int(first.strip())]
    except ValueError:
        body = raw
    msg = email.message_from_bytes(body, policy=email.policy.default)
    part = msg.get_body(preferencelist=("plain", "html")) if msg.is_multipart() else msg
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, ValueError):
        text = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
