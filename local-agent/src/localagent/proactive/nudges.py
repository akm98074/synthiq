"""Nudges: things the agent brings to you on its own, plus the rules for interrupting.

Every nudge is stored and shown in the Nudges tab. A macOS notification is
sent only when interrupting is allowed: notifications are on, it isn't quiet
hours, and today's cap isn't reached. Briefs and dream reports don't count
toward the cap.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Callable

from ..config import Settings
from ..memory.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS nudges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  urgency INTEGER NOT NULL DEFAULT 2,
  status TEXT NOT NULL DEFAULT 'new',
  snooze_until REAL,
  notified INTEGER NOT NULL DEFAULT 0,
  data TEXT
);
"""

INTERRUPTING = {"event", "reminder", "followup"}
KIND_LABEL = {"brief": "Morning brief", "event": "Coming up", "reminder": "Reminder",
              "followup": "Waiting on your reply", "dream": "Overnight"}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    """True if `now` falls in [start, end), handling ranges that cross midnight."""
    cur, s, e = now.hour * 60 + now.minute, _minutes(start), _minutes(end)
    if s == e:
        return False
    return s <= cur < e if s < e else (cur >= s or cur < e)


class Nudges:
    def __init__(self, store: Store, settings: Settings,
                 notifier: Callable | None = None, clock: Callable[[], float] = time.time):
        self.store = store
        self.settings = settings
        self.notifier = notifier
        self.clock = clock
        # Extra places a nudge goes (e.g. the iMessage channel): async (kind, title, body) -> None
        self.forwarders: list[Callable] = []
        store.db.executescript(SCHEMA)
        store.db.commit()

    def exists(self, key: str) -> bool:
        return bool(self.store.query("SELECT 1 FROM nudges WHERE key=?", (key,)))

    def notified_today(self) -> int:
        start = datetime.fromtimestamp(self.clock()).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.store.query(
            "SELECT COUNT(*) c FROM nudges WHERE notified=1 AND kind IN ('event','reminder','followup')"
            " AND created_at >= ?", (start.timestamp(),))[0]["c"]

    def may_notify(self, kind: str) -> tuple[bool, str]:
        s = self.settings
        if not s.notify_macos or self.notifier is None:
            return False, "notifications off"
        now = datetime.fromtimestamp(self.clock())
        if kind == "dream":
            return False, "dream reports are silent"
        if kind in INTERRUPTING and in_quiet_hours(now, s.quiet_start, s.quiet_end):
            return False, "quiet hours"
        if kind in INTERRUPTING and self.notified_today() >= s.max_nudges_per_day:
            return False, "daily limit reached"
        return True, ""

    def may_forward(self, kind: str) -> bool:
        now = datetime.fromtimestamp(self.clock())
        if kind == "dream":
            return False
        if kind in INTERRUPTING and in_quiet_hours(now, self.settings.quiet_start, self.settings.quiet_end):
            return False
        return True

    async def deliver(self, kind: str, key: str, title: str, body: str = "",
                      urgency: int = 2, data: dict | None = None) -> dict | None:
        """Store a nudge once per key; notify if allowed. Returns the nudge, or None if a duplicate."""
        if self.exists(key):
            return None
        ok, reason = self.may_notify(kind)
        notified = False
        if ok:
            try:
                await self.notifier(KIND_LABEL.get(kind, "LocalAIAgent"), title, body[:180])
                notified = True
            except Exception as exc:  # noqa: BLE001 - a failed notification must not lose the nudge
                reason = f"notification failed: {exc}"
        if self.forwarders and self.may_forward(kind):
            for forward in self.forwarders:
                try:
                    await forward(kind, title, body)
                except Exception:  # noqa: BLE001 - a failed forward must not lose the nudge
                    pass
        cur = self.store.execute(
            "INSERT INTO nudges(created_at, kind, key, title, body, urgency, notified, data)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (self.clock(), kind, key, title, body, urgency, int(notified),
             json.dumps({**(data or {}), "silent_reason": None if notified else reason})),
        )
        return self.get(int(cur.lastrowid))

    def get(self, nudge_id: int) -> dict | None:
        rows = self.store.query("SELECT * FROM nudges WHERE id=?", (nudge_id,))
        return self._row(rows[0]) if rows else None

    def list(self, include_done: bool = False, limit: int = 100) -> list[dict]:
        now = self.clock()
        rows = self.store.query("SELECT * FROM nudges ORDER BY created_at DESC LIMIT ?", (limit * 3,))
        out = []
        for r in rows:
            d = self._row(r)
            if d["status"] == "snoozed" and (d["snooze_until"] or 0) <= now:
                d["status"] = "new"
            if not include_done and d["status"] in ("dismissed", "snoozed"):
                continue
            out.append(d)
        return out[:limit]

    def count_new(self) -> int:
        return len([n for n in self.list() if n["status"] == "new"])

    def dismiss(self, nudge_id: int) -> bool:
        return self.store.execute("UPDATE nudges SET status='dismissed' WHERE id=?", (nudge_id,)).rowcount > 0

    def snooze(self, nudge_id: int, hours: float = 1.0) -> bool:
        return self.store.execute(
            "UPDATE nudges SET status='snoozed', snooze_until=? WHERE id=?",
            (self.clock() + hours * 3600, nudge_id)).rowcount > 0

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["data"] = json.loads(d["data"]) if d["data"] else {}
        d["label"] = KIND_LABEL.get(d["kind"], d["kind"])
        return d
