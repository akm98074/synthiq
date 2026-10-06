"""The proactive jobs: morning brief, periodic checks, and the nightly "dream"."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import psutil

from ..agent.chat import remember
from ..decide.questions import NUDGE_GATING, NUDGE_QUESTIONS
from ..llm.ollama import OllamaError
from ..memory.store import normalize
from ..persona import system_prompt
from ..safety.injection import fence, scan
from ..tools.base import ToolError, ToolResult
from .scheduler import Deferred, JobSpec

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)

MERGE_SIMILARITY = 0.88
MAX_MERGES = 10


async def _tool(rt: "Runtime", name: str, args: dict) -> ToolResult | None:
    tool = rt.tools.get(name)
    if tool is None:
        return None
    try:
        return await tool.run(args)
    except ToolError as exc:
        log.info("proactive %s failed: %s", name, exc)
        return None


def _now(rt: "Runtime") -> datetime:
    return datetime.fromtimestamp(rt.clock())


# ── morning brief ─────────────────────────────────────────────────────────
BRIEF_PROMPT = """Write my morning brief for {day}.
Use ONLY the data below; never invent events, emails or tasks.
Format: 4-8 short lines starting with "- ": today's schedule, what's due or overdue,
emails and chats waiting on my reply, then one practical suggestion. No greeting, no preamble.
If a section has no data, skip it.

DATA:
{data}"""


async def morning_brief(rt: "Runtime", manual: bool = False) -> dict:
    s = rt.settings
    now = _now(rt)
    results = {
        "calendar": await _tool(rt, "calendar_list_events", {}),
        "reminders": await _tool(rt, "reminders_list", {"limit": 20}),
        "unread mail": await _tool(rt, "mail_list", {"unread_only": True, "limit": 5}),
        "waiting on your reply": (None if "gmail_followups" in rt.tools else await _tool(
            rt, "mail_followups", {"min_days": 1, "max_days": s.followup_days, "limit": 5})),
        "Gmail waiting on your reply": await _tool(rt, "gmail_followups",
                                                   {"min_days": 1, "max_days": s.followup_days, "limit": 5}),
        "chats waiting on your reply": await _tool(rt, "messages_list", {
            "needs_reply": True, "max_days": 2, "min_minutes": 60, "limit": 5}),
    }
    used = [k for k, v in results.items() if v is not None]
    data = "\n\n".join(f"## {k}\n{fence(k, v.content)[0] if v.untrusted else v.content}"
                       for k, v in results.items() if v is not None)
    if not data:
        data = "(No calendar, reminder or mail connectors are available.)"
    messages = [
        {"role": "system", "content": system_prompt(s, "task", [], with_tools=True)},
        {"role": "user", "content": BRIEF_PROMPT.format(day=now.strftime("%A %d %B"), data=data)},
    ]
    text = (await rt.ollama.chat_text(s.chat_model, messages)).strip()
    nudge = await rt.nudges.deliver(
        "brief", f"brief:{now.date().isoformat()}:{int(rt.clock())}",
        f"Your brief for {now.strftime('%A')}", text, 2, {"sources": used})
    rt.store.add_message("assistant", f"☀️ Morning brief\n\n{text}")
    rt.audit.append("proactive_job", "morning_brief", outcome="ok",
                    detail=f"sources: {', '.join(used) or 'none'}")
    return {"summary": f"Brief written from {len(used)} source(s)", "nudge": nudge}


# ── periodic checks ───────────────────────────────────────────────────────
def _event_candidates(res: ToolResult | None, now: datetime) -> list[dict]:
    out = []
    for e in (res.data or []) if res else []:
        if e.get("all_day"):
            continue
        start = datetime.fromisoformat(e["start"])
        mins = int((start - now).total_seconds() // 60)
        if 0 <= mins <= 60:
            where = f" at {e['location']}" if e.get("location") else ""
            out.append({"kind": "event", "key": f"event:{e['title']}:{e['start']}",
                        "title": f"{e['title']} in {mins} min",
                        "body": f"{start.strftime('%H:%M')}{where} ({e.get('calendar', '')})",
                        "text": f"Calendar event in {mins} minutes: {e['title']}{where}"})
    return out


def _reminder_candidates(res: ToolResult | None, now: datetime) -> list[dict]:
    out = []
    for r in (res.data or []) if res else []:
        if not r.get("due"):
            continue
        due = datetime.fromisoformat(r["due"])
        delta = (due - now).total_seconds() / 60
        if delta > 60:
            continue
        if delta >= 0:
            when, text = f"due in {int(delta)} min", f"Reminder due in {int(delta)} minutes: {r['title']}"
        else:
            late = now - due
            ago = f"{late.days} day(s)" if late.days else f"{int(late.total_seconds() // 3600)} hour(s)"
            when, text = f"overdue by {ago}", f"Reminder overdue by {ago}: {r['title']}"
        out.append({"kind": "reminder", "key": f"reminder:{r['title']}:{r['due']}",
                    "title": r["title"], "body": f"{when} ({r.get('list', '')})", "text": text})
    return out


def _followup_candidates(res: ToolResult | None) -> list[dict]:
    out = []
    for m in (res.data or []) if res else []:
        out.append({"kind": "followup", "key": f"followup:{m['id']}",
                    "title": f"Reply to {m['from'].split('<')[0].strip() or m['from']}",
                    "body": f"{m['subject']} ({m['days_ago']}d ago)",
                    "text": (f"Unreplied email from {m['from']}, {m['days_ago']} days ago. "
                             f"Subject: {m['subject']}. {m['snippet']}"),
                    "data": {"mail_id": m["id"], "subject": m["subject"]}})
    return out


def _message_candidates(res: ToolResult | None) -> list[dict]:
    out = []
    for t in (res.data or []) if res else []:
        suspicious = bool(scan(t["last_text"]))
        out.append({"kind": "followup", "key": f"message:{t['id']}:{t['last_at']}",
                    "title": (f"⚠ Suspicious message from {t['name']} ({t['app']})" if suspicious
                              else f"Reply to {t['name']} ({t['app']})"),
                    "body": t["last_text"][:140],
                    "text": f"Unreplied {t['app']} message from {t['name']}: {t['last_text'][:300]}",
                    "data": {"thread": t["id"], "app": t["app"]}})
    return out


async def run_checks(rt: "Runtime", manual: bool = False) -> dict:
    s = rt.settings
    now = _now(rt)
    end = now + timedelta(minutes=60)
    candidates = (
        _event_candidates(await _tool(rt, "calendar_list_events", {
            "start": now.strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M")}), now)
        + _reminder_candidates(await _tool(rt, "reminders_list", {"limit": 50}), now)
        + _followup_candidates(await _tool(rt, "mail_followups",
                                           {"min_days": 1, "max_days": s.followup_days, "limit": 15}))
        + _followup_candidates(await _tool(rt, "gmail_followups",
                                           {"min_days": 1, "max_days": s.followup_days, "limit": 15}))
        + _message_candidates(await _tool(rt, "messages_list", {
            "needs_reply": True, "max_days": min(s.followup_days, 3), "min_minutes": 60, "limit": 15}))
    )
    # The same email can come from Apple Mail and Gmail: keep one nudge per (sender, subject).
    seen, unique = set(), []
    for c in candidates:
        if c["kind"] == "followup" and "subject" in c.get("data", {}):
            sig = (c["title"].lower(), c["data"]["subject"].lower())
            if sig in seen:
                continue
            seen.add(sig)
        unique.append(c)
    candidates = unique
    delivered, skipped = [], 0
    for c in candidates:
        if rt.nudges.exists(c["key"]):
            continue
        # The Jev-style decision: is this worth interrupting for, and how urgent?
        d = await rt.router.decide(c["text"], questions=NUDGE_QUESTIONS, gating=NUDGE_GATING)
        if not d["should_nudge"].yes:
            skipped += 1
            continue
        n = await rt.nudges.deliver(c["kind"], c["key"], c["title"], c["body"],
                                    int(d["urgency"].label), {**c.get("data", {}), "decision_id": d.id})
        if n:
            delivered.append(n)
    rt.audit.append("proactive_job", "checks", outcome="ok",
                    detail=f"{len(candidates)} candidate(s), {len(delivered)} nudge(s), {skipped} skipped")
    return {"summary": f"{len(delivered)} new nudge(s) from {len(candidates)} item(s)",
            "nudges": delivered}


# ── dream: overnight memory review ────────────────────────────────────────
MERGE_SCHEMA = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}, "merged": {"type": "string"}},
    "required": ["same", "merged"],
}
MERGE_PROMPT = """Two notes from a personal memory about the user:
A: {a}
B: {b}
Do they state the same fact (one may be more detailed)? If yes, write one merged note that keeps
every detail, as a short third-person statement. If they are different facts, set same=false."""


def on_battery() -> bool:
    batt = psutil.sensors_battery()
    return batt is not None and not batt.power_plugged


async def merge_duplicates(rt: "Runtime") -> int:
    s = rt.settings
    rows = rt.store.memory_vectors(s.embed_model)
    if len(rows) < 2:
        return 0
    mat = normalize(np.stack([v for _, _, v in rows]).astype(np.float32))
    sims = mat @ mat.T
    gone: set[int] = set()
    merged = 0
    pairs = sorted(((sims[i, j], i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))
                    if sims[i, j] >= MERGE_SIMILARITY), reverse=True)
    for _, i, j in pairs:
        if merged >= MAX_MERGES:
            break
        (id_a, text_a, _), (id_b, text_b, _) = rows[i], rows[j]
        if id_a in gone or id_b in gone:
            continue
        try:
            out = await rt.ollama.chat_json(
                s.fast_model, [{"role": "user", "content": MERGE_PROMPT.format(a=text_a, b=text_b)}],
                MERGE_SCHEMA)
        except OllamaError:
            continue
        if out.get("same") and str(out.get("merged", "")).strip():
            text = out["merged"].strip()
            vec = (await rt.embed([text]))[0]
            rt.store.update_memory(id_a, text=text, embedding=vec, embed_model=s.embed_model)
            rt.store.delete_memory(id_b)
            gone.add(id_b)
            merged += 1
    return merged


async def dream(rt: "Runtime", manual: bool = False) -> dict:
    if not manual and on_battery():
        raise Deferred("On battery; the overnight review waits until the Mac is plugged in.")
    now = rt.clock()
    since = float(rt.store.meta_get("last_dream") or (now - 86400))
    msgs = rt.store.user_messages_since(since)
    learned = 0
    if msgs:
        joined = "\n".join(f"- {m}" for m in msgs[-40:])
        saved = await remember(rt, joined, None)
        learned = sum(1 for item in saved if not item["updated"])
    merged = await merge_duplicates(rt)
    rt.store.meta_set("last_dream", str(now))
    rt.write_identity()
    report = (f"Reviewed {len(msgs)} message(s) since the last review, learned {learned} new "
              f"fact(s) and merged {merged} duplicate memor{'y' if merged == 1 else 'ies'}.")
    await rt.nudges.deliver("dream", f"dream:{int(now)}", "Overnight memory review", report, 1,
                            {"learned": learned, "merged": merged, "messages": len(msgs)})
    rt.audit.append("proactive_job", "dream", outcome="ok", detail=report)
    return {"summary": report, "learned": learned, "merged": merged}


async def screen_glance(rt: "Runtime", manual: bool = False) -> dict:
    if not rt.settings.screen_context_enabled:
        return {"summary": "Screen context is off"}
    try:
        r = await rt.screen.snap()
    except ToolError as exc:
        raise Deferred(str(exc)) from exc
    if r.get("skipped"):
        return {"summary": f"Skipped: {r['skipped']}"}
    return {"summary": f"Read {r['app']} ({len(r['text'])} characters); {rt.screen.count()} kept"}


def job_specs(rt: "Runtime") -> list[JobSpec]:
    s = rt.settings
    extra = ([JobSpec("screen", "interval", str(s.screen_every_minutes), lambda manual: screen_glance(rt, manual),
                      "Screen context")] if s.screen_context_enabled and rt.mac_available else [])
    return extra + [
        JobSpec("morning_brief", "daily", s.brief_time, lambda manual: morning_brief(rt, manual),
                "Morning brief"),
        JobSpec("checks", "interval", str(s.check_every_minutes), lambda manual: run_checks(rt, manual),
                "Check calendar, reminders, email and chats"),
        JobSpec("dream", "daily", s.dream_time, lambda manual: dream(rt, manual),
                "Overnight memory review"),
    ]
