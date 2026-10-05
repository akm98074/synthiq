"""A small persistent scheduler that survives sleep and restarts.

Jobs live in SQLite with their next run time. The server ticks once a minute.
If the Mac was asleep or the agent was off when a job was due, the job runs
once on the next tick (marked "late"); missed runs are never replayed one by one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from ..memory.store import Store

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  name TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  spec TEXT NOT NULL,
  next_run REAL,
  last_run REAL,
  last_status TEXT,
  last_detail TEXT,
  enabled INTEGER NOT NULL DEFAULT 1
);
"""
LATE_AFTER = 5 * 60
DEFER_SECONDS = 30 * 60


class Deferred(Exception):
    """Raised by a job that can't run right now (e.g. dream on battery); retried later."""


@dataclass
class JobSpec:
    name: str
    kind: str            # "daily" (spec "HH:MM") or "interval" (spec minutes)
    spec: str
    func: Callable[[bool], Awaitable[dict]]   # receives manual=True for "Run now"
    title: str


def next_daily(after: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    cand = after.replace(hour=h, minute=m, second=0, microsecond=0)
    return cand if cand > after else cand + timedelta(days=1)


class Scheduler:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock
        self.specs: dict[str, JobSpec] = {}
        self.enabled = True
        self._running: set[str] = set()
        store.db.executescript(SCHEMA)
        store.db.commit()

    def compute_next(self, spec: JobSpec, after_ts: float) -> float:
        after = datetime.fromtimestamp(after_ts)
        if spec.kind == "daily":
            return next_daily(after, spec.spec).timestamp()
        return after_ts + int(spec.spec) * 60

    def register(self, specs: list[JobSpec]) -> None:
        """(Re)register jobs; a changed schedule recomputes next_run, otherwise it's kept."""
        now = self.clock()
        self.specs = {s.name: s for s in specs}
        for s in specs:
            row = self.store.query("SELECT * FROM jobs WHERE name=?", (s.name,))
            if not row:
                self.store.execute("INSERT INTO jobs(name, kind, spec, next_run) VALUES (?,?,?,?)",
                                   (s.name, s.kind, s.spec, self.compute_next(s, now)))
            elif row[0]["kind"] != s.kind or row[0]["spec"] != s.spec:
                self.store.execute("UPDATE jobs SET kind=?, spec=?, next_run=? WHERE name=?",
                                   (s.kind, s.spec, self.compute_next(s, now), s.name))

    def jobs(self) -> list[dict]:
        out = []
        for r in self.store.query("SELECT * FROM jobs ORDER BY name"):
            d = dict(r)
            if d["name"] not in self.specs:
                continue
            d["title"] = self.specs[d["name"]].title
            d["running"] = d["name"] in self._running
            out.append(d)
        return out

    async def run(self, name: str, *, manual: bool = False, late: bool = False) -> dict:
        spec = self.specs.get(name)
        if spec is None:
            raise KeyError(name)
        if name in self._running:
            return {"status": "busy"}
        self._running.add(name)
        now = self.clock()
        next_run = self.compute_next(spec, now)
        try:
            result = await spec.func(manual)
            status = "late" if late else "ok"
            detail = result.get("summary", "") if isinstance(result, dict) else ""
        except Deferred as exc:
            result, status, detail = {"deferred": True}, "deferred", str(exc)
            if not manual:
                next_run = now + DEFER_SECONDS
        except Exception as exc:  # noqa: BLE001 - one failing job must not stop the scheduler
            log.exception("job %s failed", name)
            result, status, detail = {"error": str(exc)}, "error", f"{exc.__class__.__name__}: {exc}"
        finally:
            self._running.discard(name)
        if manual and status != "deferred":
            # A manual run doesn't move the regular schedule.
            self.store.execute("UPDATE jobs SET last_run=?, last_status=?, last_detail=? WHERE name=?",
                               (now, "manual" if status == "ok" else status, detail, name))
        else:
            self.store.execute(
                "UPDATE jobs SET last_run=?, last_status=?, last_detail=?, next_run=? WHERE name=?",
                (now, status, detail, next_run, name))
        return {"status": status, **(result if isinstance(result, dict) else {})}

    async def tick(self) -> list[str]:
        """Run every due job once. Returns the names that ran."""
        if not self.enabled:
            return []
        now = self.clock()
        ran = []
        for row in self.store.query("SELECT * FROM jobs WHERE enabled=1 AND next_run <= ?", (now,)):
            if row["name"] not in self.specs:
                continue
            late = now - row["next_run"] > LATE_AFTER
            await self.run(row["name"], late=late)
            ran.append(row["name"])
        return ran

    async def loop(self, interval: float = 60.0) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick failed")
            await asyncio.sleep(interval)
