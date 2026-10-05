"""macOS app connectors: Calendar, Reminders, Notes, Mail, Contacts (via AppleScript)."""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Protocol

from ..tools.base import (Tool, ToolError, ToolResult, fmt_dt, i, obj, offset_seconds,
                          parse_when, pretty_when, s)
from .applescript import parse_records


class Runner(Protocol):
    async def run(self, name: str, args: list[str]) -> str: ...


def _at(offset: str, now: datetime) -> datetime:
    return now + timedelta(seconds=float(offset))


def calendar_tools(runner: Runner) -> list[Tool]:
    async def list_events(a: dict) -> ToolResult:
        now = datetime.now()
        start = parse_when(a["start"]) if a.get("start") else now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = parse_when(a["end"], end_of_day=True) if a.get("end") else start + timedelta(days=1)
        if end <= start:
            raise ToolError("'end' must be after 'start'.")
        out = await runner.run("calendar_list", [str(offset_seconds(start, now)), str(offset_seconds(end, now))])
        events = []
        for rec in parse_records(out):
            if len(rec) < 6:
                continue
            title, so, eo, loc, cal, allday = rec[:6]
            st, en = _at(so, now), _at(eo, now)
            events.append({"title": title, "start": st.isoformat(timespec="minutes"),
                           "end": en.isoformat(timespec="minutes"), "location": loc,
                           "calendar": cal, "all_day": allday == "true"})
        events.sort(key=lambda e: e["start"])
        span = f"{fmt_dt(start)} – {fmt_dt(end)}"
        if not events:
            return ToolResult(f"No events between {span}.", f"No events ({span})", [])
        lines = [f"- {e['start'].replace('T', ' ')}–{e['end'][11:]} {e['title']}"
                 + (f" @ {e['location']}" if e["location"] else "") + f" [{e['calendar']}]"
                 for e in events]
        return ToolResult(f"Events between {span}:\n" + "\n".join(lines),
                          f"Found {len(events)} event(s)", events)

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
        return ToolResult("Open reminders:\n" + "\n".join(lines), f"{len(items)} open reminder(s)", items)

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
        return ToolResult(body, f"Found {len(notes)} note(s)", notes)

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


def mail_tools(runner: Runner) -> list[Tool]:
    async def list_mail(a: dict) -> ToolResult:
        now = datetime.now()
        out = await runner.run("mail_list", [a.get("query", ""), str(a.get("limit", 10)),
                                             "1" if a.get("unread_only") else "0"])
        msgs = []
        for rec in parse_records(out):
            if len(rec) < 6:
                continue
            mid, subj, sender, recv, read, snippet = rec[:6]
            msgs.append({"id": mid, "subject": subj, "from": sender,
                         "received": _at(recv, now).isoformat(timespec="minutes"),
                         "read": read == "true", "snippet": " ".join(snippet.split())[:200]})
        if not msgs:
            return ToolResult("No matching messages in the inbox.", "No matching mail", [])
        lines = [f"- [id {m['id']}] {m['received'].replace('T', ' ')} from {m['from']}: {m['subject']}"
                 + ("" if m["read"] else " (unread)") + f"\n  {m['snippet']}" for m in msgs]
        return ToolResult("Inbox messages (newest first):\n" + "\n".join(lines),
                          f"Found {len(msgs)} message(s)", msgs)

    async def read_mail(a: dict) -> ToolResult:
        now = datetime.now()
        out = await runner.run("mail_read", [str(a["id"])])
        parts = out.split("\x1f", 3)
        if len(parts) < 4:
            raise ToolError("Could not read that message.")
        subj, sender, recv, content = parts
        when = _at(recv, now).strftime("%a %d %b %H:%M")
        return ToolResult(f"From: {sender}\nDate: {when}\nSubject: {subj}\n\n{content}",
                          f"Read: {subj}", {"subject": subj, "from": sender})

    async def compose(a: dict, mode: str) -> ToolResult:
        to = _clean_recipients(a["to"])
        result = await runner.run("mail_compose", [to, a["subject"], a["body"], mode])
        if mode == "send":
            return ToolResult(f"Sent '{a['subject']}' to {to}.", f"Sent to {to}", {"to": to})
        return ToolResult(f"Opened a draft '{a['subject']}' to {to} in Mail for the user to review and send.",
                          f"Draft opened in Mail: {a['subject']}", {"to": to, "status": result})

    async def followups(a: dict) -> ToolResult:
        now = datetime.now()
        out = await runner.run("mail_followups", [str(a.get("min_days", 1)), str(a.get("max_days", 7)),
                                                  str(a.get("limit", 15))])
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
                          f"{len(msgs)} message(s) without a reply", msgs)

    params = obj({"to": s("Recipient email address(es), comma-separated"),
                  "subject": s("Subject line"), "body": s("Plain-text body")}, ["to", "subject", "body"])
    return [
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
        return ToolResult("Contacts:\n" + "\n".join(lines), f"Found {len(people)} contact(s)", people)

    return [
        Tool("contacts_find", "Look up a person's email addresses and phone numbers in Contacts.",
             obj({"name": s("Part of the person's name"), "limit": i("Max results (default 5)")}, ["name"]),
             "read", "contacts", find, lambda a: f"Look up {a.get('name', '')} in Contacts",
             ("task", "computer_action", "schedule", "quick_answer")),
    ]
