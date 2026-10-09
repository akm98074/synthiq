"""macOS app connectors: Calendar, Reminders, Notes, Mail, Contacts (via AppleScript)."""
from __future__ import annotations

import asyncio
import html
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Protocol

from ..tools.base import (Tool, ToolError, ToolResult, fmt_dt, i, obj, offset_seconds,
                          parse_when, pretty_when, s)
from .applescript import parse_records
from .recurrence import expand, merge


class Runner(Protocol):
    async def run(self, name: str, args: list[str]) -> str: ...


def _at(offset: str, now: datetime) -> datetime:
    return now + timedelta(seconds=float(offset))


APPLESCRIPT_NOTE = ("Note: read through AppleScript; repeating meetings were expanded from their "
                    "repeat rules, so a single occurrence that was moved or cancelled may differ slightly "
                    "from Calendar.")

def _event_line(e: dict) -> str:
    when = (f"{e['start'][:10]} (all day)" if e.get("all_day")
            else f"{e['start'].replace('T', ' ')}–{e['end'][11:]}")
    tags = [t for t in (
        "repeats" if e.get("recurring") else "",
        "invitation, not answered yet" if e.get("status") == "pending" else "",
        "you declined" if e.get("status") == "declined" else "",
        "tentative" if e.get("status") == "tentative" else "",
    ) if t]
    where = f" @ {e['location']}" if e.get("location") else ""
    cal = " · ".join(x for x in (e.get("calendar"), e.get("account")) if x)
    return (f"- {when} {e['title']}{where}" + (f" ({', '.join(tags)})" if tags else "")
            + (f" [{cal}]" if cal else ""))


def calendar_tools(runner: Runner, eventkit=None, backend: str = "auto") -> list[Tool]:
    async def applescript_events(start: datetime, end: datetime) -> list[dict]:
        now = datetime.now()
        base = await applescript_base(start, end, now)
        series = []
        for rec in parse_records(await runner.run("calendar_recurring", [str(offset_seconds(end, now))])):
            if len(rec) < 7:
                continue
            series.append({"title": rec[0], "start": rec[1], "end": rec[2], "location": rec[3],
                           "calendar": rec[4], "all_day": rec[5] == "true", "rrule": rec[6],
                           "excluded": rec[7].split(",") if len(rec) > 7 else []})
        return merge(base, expand(series, start, end))

    async def applescript_base(start: datetime, end: datetime, now: datetime) -> list[dict]:
        out = await runner.run("calendar_list", [str(offset_seconds(start, now)), str(offset_seconds(end, now))])
        events = []
        for rec in parse_records(out):
            if len(rec) < 6:
                continue
            title, so, eo, loc, cal, allday = rec[:6]
            st, en = _at(so, now), _at(eo, now)
            events.append({"title": title, "start": st.isoformat(timespec="minutes"),
                           "end": en.isoformat(timespec="minutes"), "location": loc,
                           "calendar": cal, "account": "", "all_day": allday == "true",
                           "recurring": False, "status": None})
        return events

    async def fetch(start: datetime, end: datetime) -> tuple[list[dict], str]:
        """Prefer EventKit when access is already granted; otherwise AppleScript with
        repeating events expanded from their rules. Access is never requested from the
        background server (macOS may not show that prompt); `localagent calendar-access`
        asks from Terminal instead."""
        detail = eventkit.status_detail() if eventkit is not None else None
        if backend != "applescript" and detail == "ok":
            try:
                return await eventkit.list(start, end), "EventKit"
            except Exception as exc:  # noqa: BLE001 - fall back rather than fail the request
                if backend == "eventkit":
                    raise ToolError(f"EventKit failed: {exc}") from exc
                detail = f"error: {exc.__class__.__name__}"
        if backend == "eventkit":
            raise ToolError(f"EventKit isn't usable ({detail or 'not available'}). In Terminal run: "
                            "localagent calendar-access")
        source = "AppleScript" + (f" (EventKit: {detail})" if detail and backend != "applescript" else "")
        return await applescript_events(start, end), source

    async def list_events(a: dict) -> ToolResult:
        now = datetime.now()
        start = parse_when(a["start"]) if a.get("start") else now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = parse_when(a["end"], end_of_day=True) if a.get("end") else start + timedelta(days=1)
        if end <= start:
            raise ToolError("'end' must be after 'start'.")
        events, source = await fetch(start, end)
        events.sort(key=lambda e: (e["start"], e["title"]))
        span = f"{fmt_dt(start)} – {fmt_dt(end)}"
        note = f"\n{APPLESCRIPT_NOTE}" if source.startswith("AppleScript") else ""
        if not events:
            return ToolResult(f"No events between {span}.{note}", f"No events ({span}) via {source}", [])
        body = "\n".join(_event_line(e) for e in events)
        return ToolResult(f"All {len(events)} events between {span} (list every one):\n{body}{note}",
                          f"Found {len(events)} event(s) via {source}", events,
                          untrusted=True)   # invites are written by other people

    async def create_event(a: dict) -> ToolResult:
        now = datetime.now()
        start = parse_when(a["start"])
        end = parse_when(a["end"]) if a.get("end") else start + timedelta(minutes=int(a.get("duration_minutes", 60)))
        if end <= start:
            raise ToolError("'end' must be after 'start'.")
        out = await runner.run("calendar_create", [
            a["title"], str(offset_seconds(start, now)), str(offset_seconds(end, now)),
            a.get("location", ""), a.get("calendar", ""), a.get("notes", ""),
        ])
        cal = out.split("\x1f")[0] if out else "calendar"
        return ToolResult(f"Created event '{a['title']}' on {fmt_dt(start)} in {cal}.",
                          f"Added '{a['title']}' to {cal}", {"calendar": cal})

    def create_summary(a: dict) -> str:
        when = pretty_when(a.get("start")) or "?"
        return f"Add calendar event “{a.get('title', '')}” on {when}" + (
            f" ({a['location']})" if a.get("location") else "")

    return [
        Tool("calendar_list_events",
             "List calendar events in a date/time range (defaults to today).",
             obj({"start": s("Start, ISO local time e.g. 2026-10-06 or 2026-10-06T09:00"),
                  "end": s("End, ISO local time (inclusive day if date only)")}),
             "read", "calendar", list_events,
             lambda a: "Look at your calendar", ("schedule", "task", "quick_answer", "computer_action")),
        Tool("calendar_create_event",
             "Create a calendar event.",
             obj({"title": s("Event title"), "start": s("Start, ISO local time e.g. 2026-10-06T15:00"),
                  "end": s("End, ISO local time (optional)"),
                  "duration_minutes": i("Length if no end is given (default 60)"),
                  "location": s("Location (optional)"), "calendar": s("Calendar name (optional)"),
                  "notes": s("Notes (optional)")}, ["title", "start"]),
             "write", "calendar", create_event, create_summary, ("schedule", "computer_action")),
    ]


def reminder_tools(runner: Runner) -> list[Tool]:
    async def list_reminders(a: dict) -> ToolResult:
        now = datetime.now()
        out = await runner.run("reminders_list", [a.get("list", ""), str(a.get("limit", 30))])
        items = []
        for rec in parse_records(out):
            if len(rec) < 3:
                continue
            name, due, lst = rec[:3]
            items.append({"title": name, "list": lst,
                          "due": _at(due, now).isoformat(timespec="minutes") if due.strip() else None})
        if not items:
            return ToolResult("No open reminders.", "No open reminders", [])
        lines = [f"- {r['title']}" + (f" (due {r['due'].replace('T', ' ')})" if r["due"] else "")
                 + f" [{r['list']}]" for r in items]
        return ToolResult("Open reminders:\n" + "\n".join(lines), f"{len(items)} open reminder(s)", items,
                          untrusted=True)   # shared lists

    async def create_reminder(a: dict) -> ToolResult:
        now = datetime.now()
        due = str(offset_seconds(parse_when(a["due"]), now)) if a.get("due") else ""
        lst = await runner.run("reminders_create", [a["title"], due, a.get("list", ""), a.get("notes", "")])
        when = f" for {fmt_dt(parse_when(a['due']))}" if a.get("due") else ""
        return ToolResult(f"Created reminder '{a['title']}'{when} in list {lst or 'Reminders'}.",
                          f"Reminder set: {a['title']}{when}", {"list": lst})

    return [
        Tool("reminders_list", "List open (not completed) reminders.",
             obj({"list": s("Reminders list name (optional)"), "limit": i("Max items (default 30)")}),
             "read", "reminders", list_reminders, lambda a: "Look at your reminders",
             ("schedule", "task", "computer_action")),
        Tool("reminders_create", "Create a reminder, optionally with a due date/time.",
             obj({"title": s("What to be reminded about"),
                  "due": s("When, ISO local time e.g. 2026-10-06T18:00 (optional)"),
                  "list": s("Reminders list name (optional)"), "notes": s("Extra notes (optional)")},
                 ["title"]),
             "write", "reminders", create_reminder,
             lambda a: f"Create reminder “{a.get('title', '')}”" + (f" due {pretty_when(a['due'])}" if a.get("due") else ""),
             ("schedule", "computer_action")),
    ]


def notes_tools(runner: Runner) -> list[Tool]:
    async def search(a: dict) -> ToolResult:
        out = await runner.run("notes_search", [a["query"], str(a.get("limit", 5))])
        notes = [{"title": r[0], "text": r[1] if len(r) > 1 else ""} for r in parse_records(out)]
        if not notes:
            return ToolResult(f"No notes matching '{a['query']}'.", "No matching notes", [])
        body = "\n\n".join(f"## {n['title']}\n{n['text']}" for n in notes)
        return ToolResult(body, f"Found {len(notes)} note(s)", notes, untrusted=True)   # shared notes, pasted text

    async def create(a: dict) -> ToolResult:
        lines = html.escape(a["body"]).splitlines() or [""]
        body = f"<h1>{html.escape(a['title'])}</h1>" + "".join(f"<div>{l or '<br>'}</div>" for l in lines)
        folder = await runner.run("notes_create", [a["title"], body])
        return ToolResult(f"Created note '{a['title']}' in {folder or 'Notes'}.",
                          f"Note created: {a['title']}", {"folder": folder})

    return [
        Tool("notes_search", "Search Apple Notes by title or text.",
             obj({"query": s("Words to look for"), "limit": i("Max notes (default 5)")}, ["query"]),
             "read", "notes", search, lambda a: "Search your notes", ("task", "quick_answer", "computer_action", "memory_query")),
        Tool("notes_create", "Create a new note in Apple Notes.",
             obj({"title": s("Note title"), "body": s("Note text")}, ["title", "body"]),
             "draft", "notes", create, lambda a: f"Create note “{a.get('title', '')}”",
             ("task", "computer_action")),
    ]


def _clean_recipients(value) -> str:
    items = value if isinstance(value, list) else str(value).replace(";", ",").split(",")
    out = [x.strip() for x in items if x and "@" in x]
    if not out:
        raise ToolError("Give at least one email address (look it up with contacts_find first).")
    return ",".join(out)


class MailGuard:
    """Keeps background work from piling onto Mail.app.

    Background checks (nudges, the morning brief) use Mail's index when it can be read, which
    doesn't touch Mail.app. Only when they would have to script Mail.app, they run at most every
    3 hours, never while Mail is already using a lot of memory, and not for 6 hours after Mail
    failed to answer in time (osascript gives up, but Mail keeps working on the request).
    """

    MAX_RSS_MB = 2048
    MIN_GAP = 3 * 3600
    AFTER_TIMEOUT = 6 * 3600

    def __init__(self, runner, clock=time.time):
        self.runner = runner
        self.clock = clock
        self.last_background = 0.0
        self.last_skip = ""
        self.source = ""                 # "index" or "mail_app": what answered last

    @staticmethod
    def mail_rss_mb() -> float | None:
        """Mail.app's resident memory in MB (None if it isn't running or this isn't a Mac)."""
        if sys.platform != "darwin":
            return None
        try:
            out = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.splitlines():
            rss, _, comm = line.strip().partition(" ")
            if comm.strip().endswith("/Mail.app/Contents/MacOS/Mail") and rss.isdigit():
                return int(rss) / 1024
        return None

    def background_ok(self) -> tuple[bool, str]:
        now = self.clock()
        timed_out = max((getattr(self.runner, "last_timeout", {}) or {}).get(n, 0)
                        for n in ("mail_list", "mail_followups", "mail_read")) if hasattr(self.runner, "last_timeout") else 0
        if timed_out and now - timed_out < self.AFTER_TIMEOUT:
            return False, "Mail didn't answer in time recently"
        rss = self.mail_rss_mb()
        if rss is not None and rss > self.MAX_RSS_MB:
            return False, f"Mail is already using {rss / 1024:.1f} GB"
        if now - self.last_background < self.MIN_GAP:
            return False, "checked Mail less than 3 hours ago"
        return True, ""


def mail_tools(runner: Runner, index=None, guard: MailGuard | None = None) -> list[Tool]:
    """Apple Mail. Reads come from Mail's index (connectors/mailindex.py) when possible; otherwise a
    small AppleScript that only looks at the newest messages of each inbox. Background callers pass
    `_background`, and then never script Mail.app unless MailGuard allows it."""
    from .mailindex import MailIndexUnavailable

    guard = guard or MailGuard(runner)

    async def from_index(fn, *args):
        if index is None:
            raise MailIndexUnavailable("no index")
        res = await asyncio.to_thread(fn, *args)
        guard.source = "index"
        return res

    async def via_mail_app(a: dict, name: str, args: list[str]) -> str:
        if a.get("_background"):
            ok, why = guard.background_ok()
            if not ok:
                guard.last_skip = why
                raise ToolError(f"Mail check skipped: {why}.")
            guard.last_background = guard.clock()
        guard.source, guard.last_skip = "mail_app", ""
        return await runner.run(name, args)

    def when(ts: float) -> str:
        return datetime.fromtimestamp(ts).isoformat(timespec="minutes")

    async def list_mail(a: dict) -> ToolResult:
        now = datetime.now()
        limit = int(a.get("limit", 10) or 10)
        try:
            rows = await from_index(index.recent if index else None, a.get("query", ""), limit, bool(a.get("unread_only")))
            msgs = [{"id": str(r["id"]), "subject": r["subject"], "from": r["from"], "received": when(r["received"]),
                     "read": r["read"], "snippet": r["snippet"]} for r in rows]
        except MailIndexUnavailable:
            out = await via_mail_app(a, "mail_list", [a.get("query", ""), str(limit),
                                                      "1" if a.get("unread_only") else "0"])
            msgs = []
            for rec in parse_records(out):
                if len(rec) < 6:
                    continue
                mid, subj, sender, recv, read, snippet = rec[:6]
                msgs.append({"id": mid, "subject": subj, "from": sender,
                             "received": _at(recv, now).isoformat(timespec="minutes"),
                             "read": read == "true", "snippet": " ".join(snippet.split())[:200]})
            msgs = sorted(msgs, key=lambda m: m["received"], reverse=True)[:limit]
        if not msgs:
            return ToolResult("No matching messages in the inbox.", "No matching mail", [])
        lines = [f"- [id {m['id']}] {m['received'].replace('T', ' ')} from {m['from']}: {m['subject']}"
                 + ("" if m["read"] else " (unread)") + (f"\n  {m['snippet']}" if m["snippet"] else "") for m in msgs]
        return ToolResult("Inbox messages (newest first):\n" + "\n".join(lines),
                          f"Found {len(msgs)} message(s)", msgs, untrusted=True)

    async def read_mail(a: dict) -> ToolResult:
        now = datetime.now()
        try:
            msg = await from_index(index.read if index else None, int(a["id"]))
        except (MailIndexUnavailable, ValueError):
            msg = None
        if msg is not None:
            subj, sender, content = msg["subject"], msg["from"], msg["text"]
            when_s = datetime.fromtimestamp(msg["received"]).strftime("%a %d %b %H:%M")
        else:
            out = await via_mail_app(a, "mail_read", [str(a["id"])])
            parts = out.split("\x1f", 3)
            if len(parts) < 4:
                raise ToolError("Could not read that message.")
            subj, sender, recv, content = parts
            when_s = _at(recv, now).strftime("%a %d %b %H:%M")
        return ToolResult(f"From: {sender}\nDate: {when_s}\nSubject: {subj}\n\n{content}",
                          f"Read: {subj}", {"subject": subj, "from": sender}, untrusted=True)

    async def compose(a: dict, mode: str) -> ToolResult:
        to = _clean_recipients(a["to"])
        result = await runner.run("mail_compose", [to, a["subject"], a["body"], mode])
        if mode == "send":
            return ToolResult(f"Sent '{a['subject']}' to {to}.", f"Sent to {to}", {"to": to})
        return ToolResult(f"Opened a draft '{a['subject']}' to {to} in Mail for the user to review and send.",
                          f"Draft opened in Mail: {a['subject']}", {"to": to, "status": result})

    async def followups(a: dict) -> ToolResult:
        now = datetime.now()
        lo, hi, limit = a.get("min_days", 1), a.get("max_days", 7), int(a.get("limit", 15) or 15)
        try:
            rows = await from_index(index.followups if index else None, lo, hi, limit)
            msgs = [{"id": str(r["id"]), "subject": r["subject"], "from": r["from"], "received": when(r["received"]),
                     "days_ago": max(0, (now - datetime.fromtimestamp(r["received"])).days),
                     "snippet": r["snippet"]} for r in rows]
        except MailIndexUnavailable:
            out = await via_mail_app(a, "mail_followups", [str(lo), str(hi), str(limit)])
            msgs = []
            for rec in parse_records(out):
                if len(rec) < 5:
                    continue
                mid, subj, sender, recv, snippet = rec[:5]
                received = _at(recv, now)
                msgs.append({"id": mid, "subject": subj, "from": sender,
                             "received": received.isoformat(timespec="minutes"),
                             "days_ago": max(0, (now - received).days),
                             "snippet": " ".join(snippet.split())[:200]})
        if not msgs:
            return ToolResult("No unreplied messages in that window.", "Nothing waiting on a reply", [])
        lines = [f"- [id {m['id']}] {m['days_ago']}d ago from {m['from']}: {m['subject']}" for m in msgs]
        return ToolResult("Inbox messages you haven't replied to:\n" + "\n".join(lines),
                          f"{len(msgs)} message(s) without a reply", msgs, untrusted=True)

    params = obj({"to": s("Recipient email address(es), comma-separated"),
                  "subject": s("Subject line"), "body": s("Plain-text body")}, ["to", "subject", "body"])
    tools = [
        Tool("mail_list", "List or search recent inbox messages (subject or sender).",
             obj({"query": s("Text to match in subject or sender (optional)"),
                  "limit": i("Max messages (default 10)"),
                  "unread_only": {"type": "boolean", "description": "Only unread messages"}}),
             "read", "mail", list_mail, lambda a: "Look at your inbox",
             ("task", "computer_action", "quick_answer", "schedule")),
        Tool("mail_followups", "List inbox messages the user has not replied to (default: 1-7 days old).",
             obj({"min_days": i("Received at least this many days ago (default 1)"),
                  "max_days": i("Received at most this many days ago (default 7)"),
                  "limit": i("Max messages (default 15)")}),
             "read", "mail", followups, lambda a: "Check for emails waiting on your reply",
             ("task", "computer_action", "quick_answer", "schedule")),
        Tool("mail_read", "Read one inbox message in full by its id (from mail_list).",
             obj({"id": i("Message id from mail_list")}, ["id"]),
             "read", "mail", read_mail, lambda a: "Read an email", ("task", "computer_action")),
        Tool("mail_draft", "Open a new email draft in Mail for the user to review and send themselves.",
             params, "draft", "mail", lambda a: compose(a, "draft"),
             lambda a: f"Open a draft to {a.get('to', '')}: “{a.get('subject', '')}”",
             ("task", "computer_action")),
        Tool("mail_send", "Send an email immediately. Prefer mail_draft unless the user clearly asked to send.",
             params, "write", "mail", lambda a: compose(a, "send"),
             lambda a: f"Send email to {a.get('to', '')}: “{a.get('subject', '')}”",
             ("computer_action",)),
    ]
    for t in tools:
        t.mail_state = (index, guard)    # read by the Trust check
    return tools


def contacts_tools(runner: Runner) -> list[Tool]:
    async def find(a: dict) -> ToolResult:
        out = await runner.run("contacts_find", [a["name"], str(a.get("limit", 5))])
        people = []
        for rec in parse_records(out):
            name = rec[0]
            emails = [e for e in (rec[1].split(",") if len(rec) > 1 else []) if e]
            phones = [p for p in (rec[2].split(",") if len(rec) > 2 else []) if p]
            people.append({"name": name, "emails": emails, "phones": phones})
        if not people:
            return ToolResult(f"No contact matching '{a['name']}'.", "No matching contact", [])
        lines = [f"- {p['name']}: emails {', '.join(p['emails']) or 'none'}; phones {', '.join(p['phones']) or 'none'}"
                 for p in people]
        return ToolResult("Contacts:\n" + "\n".join(lines), f"Found {len(people)} contact(s)", people,
                          untrusted=True)   # cards can come from others

    return [
        Tool("contacts_find", "Look up a person's email addresses and phone numbers in Contacts.",
             obj({"name": s("Part of the person's name"), "limit": i("Max results (default 5)")}, ["name"]),
             "read", "contacts", find, lambda a: f"Look up {a.get('name', '')} in Contacts",
             ("task", "computer_action", "schedule", "quick_answer")),
    ]
