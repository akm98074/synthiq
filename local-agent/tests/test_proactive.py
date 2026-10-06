import asyncio
import json
from datetime import datetime, timedelta

import pytest

from localagent.config import Settings
from localagent.memory.store import Store
from localagent.proactive.nudges import Nudges, in_quiet_hours
from localagent.proactive.scheduler import Deferred, JobSpec, Scheduler, next_daily


class Clock:
    def __init__(self, dt):
        self.t = dt.timestamp()

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw).total_seconds()


def test_quiet_hours_wrap_midnight():
    at = lambda h, m=0: datetime(2026, 1, 1, h, m)  # noqa: E731
    assert in_quiet_hours(at(23), "22:00", "07:30")
    assert in_quiet_hours(at(3), "22:00", "07:30")
    assert not in_quiet_hours(at(7, 30), "22:00", "07:30")
    assert not in_quiet_hours(at(12), "22:00", "07:30")
    assert in_quiet_hours(at(13), "12:00", "14:00")
    assert not in_quiet_hours(at(13), "00:00", "00:00")


def test_next_daily():
    assert next_daily(datetime(2026, 1, 1, 7, 0), "08:00") == datetime(2026, 1, 1, 8, 0)
    assert next_daily(datetime(2026, 1, 1, 8, 0), "08:00") == datetime(2026, 1, 2, 8, 0)


def test_scheduler_runs_once_and_catches_up(tmp_path):
    clock = Clock(datetime(2026, 1, 1, 7, 0))
    sched = Scheduler(Store(tmp_path / "s.db"), clock)
    runs = []

    async def job(manual):
        runs.append(manual)
        return {"summary": "ran"}

    sched.register([JobSpec("brief", "daily", "08:00", job, "Brief"),
                    JobSpec("check", "interval", "30", job, "Check")])
    assert asyncio.run(sched.tick()) == []
    clock.advance(hours=1, minutes=1)            # 08:01: both due
    assert sorted(asyncio.run(sched.tick())) == ["brief", "check"]
    assert asyncio.run(sched.tick()) == []        # not again
    clock.advance(days=3)                         # Mac asleep for 3 days
    ran = asyncio.run(sched.tick())
    assert sorted(ran) == ["brief", "check"]      # once each, not 3x / 144x
    jobs = {j["name"]: j for j in sched.jobs()}
    assert jobs["brief"]["last_status"] == "late"
    assert datetime.fromtimestamp(jobs["brief"]["next_run"]).hour == 8
    assert asyncio.run(sched.tick()) == []


def test_scheduler_defer_and_manual(tmp_path):
    clock = Clock(datetime(2026, 1, 1, 2, 59))
    sched = Scheduler(Store(tmp_path / "s.db"), clock)

    async def dream(manual):
        if not manual:
            raise Deferred("on battery")
        return {"summary": "dreamt"}

    sched.register([JobSpec("dream", "daily", "03:00", dream, "Dream")])
    clock.advance(minutes=2)
    asyncio.run(sched.tick())
    j = sched.jobs()[0]
    assert j["last_status"] == "deferred"
    assert j["next_run"] == pytest.approx(clock() + 1800)
    before = j["next_run"]
    assert asyncio.run(sched.run("dream", manual=True))["status"] == "ok"
    assert sched.jobs()[0]["next_run"] == before   # manual run keeps the schedule
    # changing the schedule recomputes next_run
    sched.register([JobSpec("dream", "daily", "04:00", dream, "Dream")])
    assert datetime.fromtimestamp(sched.jobs()[0]["next_run"]).hour == 4


def test_nudges_dedupe_quiet_hours_and_cap(tmp_path):
    clock = Clock(datetime(2026, 1, 1, 12, 0))
    sent = []

    async def notifier(*a):
        sent.append(a)

    s = Settings(quiet_start="22:00", quiet_end="07:00", max_nudges_per_day=2)
    n = Nudges(Store(tmp_path / "n.db"), s, notifier, clock)
    run = lambda *a: asyncio.run(n.deliver(*a))  # noqa: E731
    assert run("followup", "k1", "Reply to Sam")["notified"] == 1
    assert run("followup", "k1", "Reply to Sam") is None           # duplicate
    run("reminder", "k2", "Pay bill")
    third = run("event", "k3", "Dentist")
    assert third["notified"] == 0 and third["data"]["silent_reason"] == "daily limit reached"
    assert run("brief", "b1", "Brief")["notified"] == 1             # briefs aren't capped
    clock.advance(hours=11)                                          # 23:00
    late = run("followup", "k4", "Late one")
    assert late["notified"] == 0  # cap or quiet hours
    assert len(sent) == 3
    assert n.count_new() == 5
    assert n.snooze(third["id"], 1) and n.dismiss(late["id"])
    assert n.count_new() == 3
    clock.advance(hours=2)
    assert n.count_new() == 4                                        # snooze expired


def test_checks_job_creates_nudges(voice_client):
    c = voice_client
    # an overdue reminder alongside the canned calendar event (in 60 min) and follow-ups
    c.runner.outputs["reminders_list"] = "Pay credit card\x1f-7200\x1fBills\x1e"
    r = c.post("/api/jobs/checks/run").json()
    assert r["status"] == "ok", r
    items = c.get("/api/nudges").json()["items"]
    kinds = sorted(n["kind"] for n in items)
    assert kinds == ["event", "followup", "reminder"], items           # newsletter skipped
    follow = next(n for n in items if n["kind"] == "followup")
    assert "Priya" in follow["title"] and follow["urgency"] == 4
    assert any(call[0] == "notify" for call in c.runner.calls)
    # nudge decisions are logged and correctable like chat decisions
    decisions = c.get("/api/decisions").json()
    assert any("should_nudge" in d["answers"] for d in decisions)
    # running again doesn't duplicate
    c.post("/api/jobs/checks/run")
    assert len(c.get("/api/nudges").json()["items"]) == 3
    nid = follow["id"]
    assert c.post(f"/api/nudges/{nid}/dismiss").json() == {"ok": True}
    assert c.get("/api/nudges").json()["new"] == 2
    assert c.post("/api/nudges/9999/snooze", json={"hours": 1}).status_code == 404


def test_morning_brief(voice_client):
    r = voice_client.post("/api/jobs/morning_brief/run").json()
    assert r["status"] == "ok" and r["nudge"]["kind"] == "brief"
    assert set(r["nudge"]["data"]["sources"]) >= {"calendar", "reminders", "unread mail"}
    msgs = voice_client.get("/api/messages").json()
    assert msgs[-1]["role"] == "assistant" and msgs[-1]["content"].startswith("☀️ Morning brief")


def test_dream_merges_and_learns(voice_client):
    c = voice_client
    c.post("/api/memories", json={"text": "Likes window seats", "kind": "preference"})
    c.post("/api/memories", json={"text": "Likes window seats.", "kind": "preference"})
    c.post("/api/memories", json={"text": "Lives in Austin", "kind": "place"})
    c.post("/api/chat", json={"text": "hello there"})
    r = c.post("/api/jobs/dream/run").json()
    assert r["status"] == "ok" and r["merged"] == 1, r
    texts = [m["text"] for m in c.get("/api/memories").json()]
    assert len(texts) == 2 and "Lives in Austin" in texts
    dream = [n for n in c.get("/api/nudges").json()["items"] if n["kind"] == "dream"][0]
    assert "merged 1 duplicate" in dream["body"]


def test_jobs_endpoint_and_settings_reschedule(voice_client):
    jobs = {j["name"]: j for j in voice_client.get("/api/jobs").json()["jobs"]}
    assert set(jobs) == {"morning_brief", "checks", "dream"}
    voice_client.put("/api/settings", json={"brief_time": "06:45", "proactive_enabled": False})
    data = voice_client.get("/api/jobs").json()
    assert data["enabled"] is False
    brief = next(j for j in data["jobs"] if j["name"] == "morning_brief")
    assert brief["spec"] == "06:45" and datetime.fromtimestamp(brief["next_run"]).strftime("%H:%M") == "06:45"
    assert voice_client.put("/api/settings", json={"brief_time": "25:00"}).status_code == 400
    assert voice_client.post("/api/jobs/nope/run").status_code == 404


def test_nudge_seeds_added_on_upgrade(tmp_path):
    from localagent.decide.prototype import seed_store
    s = Store(tmp_path / "u.db")
    s.add_example("intent", "task", "old seed", source="seed")  # a 0.2.x database
    n = seed_store(s)
    assert n > 0 and s.count_examples_for("should_nudge", "seed") == 44
    assert seed_store(s) == 0


def test_checks_dont_duplicate_when_a_minute_passes(voice_client):
    """Event/reminder times come from offsets relative to "now", so a later check can compute the
    same item a minute apart (seen on a slow CI runner). It must still count as the same nudge."""
    from datetime import datetime, timedelta

    c = voice_client
    c.runner.outputs["reminders_list"] = "Pay credit card\x1f-7200\x1fBills\x1e"
    c.post("/api/jobs/checks/run")
    store = c.app.state.rt.store
    for r in store.query("SELECT id, key FROM nudges WHERE kind IN ('event','reminder')"):
        head, stamp = r["key"][:-16], r["key"][-16:]            # "...:" + "YYYY-MM-DDTHH:MM"
        shifted = (datetime.fromisoformat(stamp) - timedelta(minutes=1)).isoformat(timespec="minutes")
        store.execute("UPDATE nudges SET key=? WHERE id=?", (head + shifted, r["id"]))
    before = len(c.get("/api/nudges").json()["items"])
    c.post("/api/jobs/checks/run")
    assert len(c.get("/api/nudges").json()["items"]) == before
