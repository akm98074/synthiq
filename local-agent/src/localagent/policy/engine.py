"""Approvals, standing grants and the tamper-evident audit log.

The policy engine, not the model, decides whether a tool call may run:
read/draft tiers run automatically; write needs approval unless a matching
grant exists; danger needs a fresh one-time approval every time.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from ..memory.store import Store
from ..tools.base import Tool

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  tool TEXT NOT NULL,
  tier TEXT NOT NULL,
  args TEXT NOT NULL,
  summary TEXT NOT NULL,
  task_id INTEGER,
  state TEXT,
  scope TEXT,
  decided_at REAL
);
CREATE TABLE IF NOT EXISTS grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool TEXT NOT NULL,
  scope TEXT NOT NULL,
  task_id INTEGER,
  boot_id TEXT,
  expires_at REAL,
  created_at REAL NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  tool TEXT,
  tier TEXT,
  args TEXT,
  outcome TEXT,
  detail TEXT,
  approval_id INTEGER,
  task_id INTEGER,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
"""

SCOPES = {
    "once": "Just this once",
    "task": "For the rest of this request",
    "session": "Until the agent restarts",
    "hour": "For 1 hour",
    "day": "For 24 hours",
    "always": "Always for this action",
}
ALLOWED_SCOPES = {"write": list(SCOPES), "danger": ["once"]}
DURATIONS = {"hour": 3600, "day": 86400}
GENESIS = "0" * 64


class ApprovalError(ValueError):
    pass


class Policy:
    def __init__(self, store: Store):
        self.store = store
        self.boot_id = uuid.uuid4().hex
        store.db.executescript(SCHEMA)
        store.db.commit()
        # Approvals left pending by a previous run can't be resumed.
        store.execute("UPDATE approvals SET status='expired' WHERE status='pending'")

    # ── decisions ─────────────────────────────────────────────────────────
    def needs_approval(self, tool: Tool, task_id: int | None) -> bool:
        if tool.tier in ("read", "draft"):
            return False
        if tool.tier == "danger":
            return True
        return self.matching_grant(tool.name, task_id) is None

    def matching_grant(self, tool_name: str, task_id: int | None) -> dict | None:
        now = time.time()
        for g in self.active_grants():
            if g["tool"] != tool_name:
                continue
            if g["scope"] == "always":
                return g
            if g["scope"] == "session" and g["boot_id"] == self.boot_id:
                return g
            if g["scope"] == "task" and task_id is not None and g["task_id"] == task_id:
                return g
            if g["scope"] in DURATIONS and (g["expires_at"] or 0) > now:
                return g
        return None

    # ── approvals ─────────────────────────────────────────────────────────
    def request(self, tool: Tool, args: dict, task_id: int | None, state: dict) -> dict:
        cur = self.store.execute(
            "INSERT INTO approvals(created_at, tool, tier, args, summary, task_id, state)"
            " VALUES (?,?,?,?,?,?,?)",
            (time.time(), tool.name, tool.tier, json.dumps(args), tool.summary(args), task_id,
             json.dumps(state)),
        )
        return self.get(int(cur.lastrowid))

    def get(self, approval_id: int, with_state: bool = False) -> dict | None:
        rows = self.store.query("SELECT * FROM approvals WHERE id=?", (approval_id,))
        return self._row(rows[0], with_state) if rows else None

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        if status:
            rows = self.store.query(
                "SELECT * FROM approvals WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            rows = self.store.query("SELECT * FROM approvals ORDER BY id DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def decide(self, approval_id: int, approve: bool, scope: str = "once") -> dict:
        ap = self.get(approval_id, with_state=True)
        if ap is None:
            raise KeyError(approval_id)
        if ap["status"] != "pending":
            raise ApprovalError(f"This request is already {ap['status']}.")
        if approve and scope not in ALLOWED_SCOPES.get(ap["tier"], ["once"]):
            raise ApprovalError(f"Scope '{scope}' isn't allowed for {ap['tier']} actions.")
        status = "approved" if approve else "denied"
        self.store.execute(
            "UPDATE approvals SET status=?, scope=?, decided_at=? WHERE id=?",
            (status, scope if approve else None, time.time(), approval_id),
        )
        if approve and scope != "once":
            self.store.execute(
                "INSERT INTO grants(tool, scope, task_id, boot_id, expires_at, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (ap["tool"], scope, ap["task_id"], self.boot_id,
                 time.time() + DURATIONS[scope] if scope in DURATIONS else None, time.time()),
            )
        ap.update(status=status, scope=scope if approve else None)
        return ap

    @staticmethod
    def _row(r, with_state: bool = False) -> dict:
        d = dict(r)
        d["args"] = json.loads(d["args"])
        state = d.pop("state", None)
        if with_state:
            d["state"] = json.loads(state) if state else None
        d["allowed_scopes"] = [{"id": s, "label": SCOPES[s]} for s in ALLOWED_SCOPES.get(d["tier"], ["once"])]
        return d

    # ── grants ────────────────────────────────────────────────────────────
    def active_grants(self) -> list[dict]:
        now = time.time()
        rows = self.store.query("SELECT * FROM grants WHERE revoked=0 ORDER BY id DESC")
        out = []
        for r in rows:
            g = dict(r)
            if g["scope"] in DURATIONS and (g["expires_at"] or 0) <= now:
                continue
            if g["scope"] == "session" and g["boot_id"] != self.boot_id:
                continue
            g["label"] = SCOPES.get(g["scope"], g["scope"])
            out.append(g)
        return out

    def revoke(self, grant_id: int) -> bool:
        return self.store.execute("UPDATE grants SET revoked=1 WHERE id=? AND revoked=0",
                                  (grant_id,)).rowcount > 0


def _hash(prev: str, payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev + blob).encode()).hexdigest()


class Audit:
    """Append-only log; each row's hash covers the previous row's hash."""

    FIELDS = ("ts", "kind", "tool", "tier", "args", "outcome", "detail", "approval_id", "task_id")

    def __init__(self, store: Store):
        self.store = store
        store.db.executescript(SCHEMA)
        store.db.commit()

    def append(self, kind: str, tool: str | None = None, tier: str | None = None,
               args: dict | None = None, outcome: str | None = None, detail: str | None = None,
               approval_id: int | None = None, task_id: int | None = None) -> int:
        with self.store._lock:
            last = self.store.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else GENESIS
            payload = {"ts": round(time.time(), 3), "kind": kind, "tool": tool, "tier": tier,
                       "args": json.dumps(args, sort_keys=True) if args is not None else None,
                       "outcome": outcome, "detail": (detail or "")[:2000] or None,
                       "approval_id": approval_id, "task_id": task_id}
            h = _hash(prev, payload)
            cur = self.store.db.execute(
                "INSERT INTO audit(ts, kind, tool, tier, args, outcome, detail, approval_id, task_id,"
                " prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(payload[f] for f in self.FIELDS) + (prev, h),
            )
            self.store.db.commit()
            return int(cur.lastrowid)

    def list(self, limit: int = 200) -> list[dict]:
        rows = self.store.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["args"] = json.loads(d["args"]) if d["args"] else None
            out.append(d)
        return out

    def verify(self) -> dict:
        rows = self.store.query("SELECT * FROM audit ORDER BY id ASC")
        prev = GENESIS
        for r in rows:
            payload = {f: r[f] for f in self.FIELDS}
            if r["prev_hash"] != prev or _hash(prev, payload) != r["hash"]:
                return {"ok": False, "count": len(rows), "broken_at": r["id"]}
            prev = r["hash"]
        return {"ok": True, "count": len(rows), "broken_at": None}
