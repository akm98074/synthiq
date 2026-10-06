import asyncio
from datetime import datetime, timedelta

from localagent.connectors.eventkit import EventKitCalendar, event_to_dict
from localagent.connectors.mac import APPLESCRIPT_NOTE, calendar_tools
from localagent.llm.ollama import RESET, ThinkFilter, strip_think
from localagent.tools.base import ToolError


class _NSDate:
    def __init__(self, ts): self.ts = ts
    def timeIntervalSince1970(self): return self.ts


class _Obj:
    def __init__(self, **kw): self.kw = kw
    def __getattr__(self, name):
        if name in self.kw:
            return lambda: self.kw[name]
        raise AttributeError(name)


def _event(title, start, hours=1, recurring=False, cal="Work", account="Exchange", status=None):
    me = [_Obj(isCurrentUser=True, participantStatus=status)] if status else []
    return _Obj(title=title, startDate=_NSDate(start.timestamp()),
                endDate=_NSDate((start + timedelta(hours=hours)).timestamp()),
                location="", calendar=_Obj(title=cal, source=_Obj(title=account)),
                isAllDay=False, hasRecurrenceRules=recurring, attendees=me)


class FakeEventKit:
    def __init__(self, status="authorized", events=()):
        self.status, self.events, self.requested = status, list(events), 0

    def installed(self): return True
    def authorization(self): return self.status

    def status_detail(self):
        return {"authorized": "ok", "not_determined": "not asked yet",
                "denied": "access denied"}.get(self.status, self.status)

    async def request_access(self):
        self.requested += 1
        self.status = "authorized"
        return True

    async def list(self, start, end):
        return sorted((event_to_dict(e) for e in self.events), key=lambda e: e["start"])


class Runner:
    def __init__(self, recurring=""):
        self.calls, self.recurring = [], recurring

    async def run(self, name, args):
        self.calls.append(name)
        if name == "calendar_recurring":
            return self.recurring
        return "Old\x1f3600\x1f7200\x1f\x1fHome\x1ffalse\x1e"


def _list(tools, **args):
    t = {x.name: x for x in tools}["calendar_list_events"]
    return asyncio.run(t.run(args))


def test_event_to_dict_marks_repeats_invites_and_accounts():
    d = event_to_dict(_event("ViTea Touch", datetime(2026, 10, 6, 8), recurring=True, status=1,
                             cal="Calendar", account="Google"))
    assert d["recurring"] and d["status"] == "pending"
    assert d["calendar"] == "Calendar" and d["account"] == "Google"
    assert d["start"] == "2026-10-06T08:00"


def test_eventkit_preferred_and_lists_every_occurrence():
    base = datetime(2026, 10, 6, 9)
    ek = FakeEventKit(events=[
        _event("ViTea Touch", base - timedelta(hours=1), recurring=True, account="Google"),
        _event("ViTea Touch", base + timedelta(days=3, hours=-1), recurring=True, account="Google"),
        _event("AI Threat Readiness", base + timedelta(days=2), account="Google"),
        _event("AI Threat Readiness", base + timedelta(days=2), account="Exchange"),
        _event("Zettabolt", base, status=1),
    ])
    runner = Runner()
    res = _list(calendar_tools(runner, ek, "auto"), start="2026-10-05", end="2026-10-11")
    assert res.display == "Found 5 event(s) via EventKit"
    assert runner.calls == []                                  # AppleScript not used
    assert res.content.count("ViTea Touch") == 2 and res.content.count("AI Threat Readiness") == 2
    assert "repeats" in res.content and "invitation, not answered yet" in res.content
    assert "list every one" in res.content and APPLESCRIPT_NOTE not in res.content


def test_server_never_prompts_and_reports_why():
    ek = FakeEventKit(status="not_determined", events=[_event("A", datetime(2026, 10, 6, 9))])
    res = _list(calendar_tools(Runner(), ek, "auto"), start="2026-10-06")
    assert ek.requested == 0
    assert res.display.endswith("via AppleScript (EventKit: not asked yet)")


def test_fallback_to_applescript_with_note_when_denied():
    runner = Runner()
    res = _list(calendar_tools(runner, FakeEventKit(status="denied"), "auto"))
    assert runner.calls == ["calendar_list", "calendar_recurring"]
    assert "via AppleScript (EventKit: access denied)" in res.display
    assert APPLESCRIPT_NOTE in res.content


def test_forced_eventkit_denied_raises_help():
    try:
        _list(calendar_tools(Runner(), FakeEventKit(status="denied"), "eventkit"))
    except ToolError as exc:
        assert "access denied" in str(exc) and "calendar-access" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_forced_applescript_and_no_eventkit():
    runner = Runner()
    r1 = _list(calendar_tools(runner, FakeEventKit(), "applescript"))
    r2 = _list(calendar_tools(runner, None, "auto"))
    assert runner.calls == ["calendar_list", "calendar_recurring"] * 2
    assert r1.display.endswith("via AppleScript") and r2.display.endswith("via AppleScript")


def test_eventkit_unavailable_off_macos():
    import sys
    if sys.platform != "darwin":
        assert not EventKitCalendar().installed()
        assert EventKitCalendar().authorization() == "unavailable"


def test_orphan_think_is_stripped():
    text = "Okay, the user wants their events.\nI think the response is clear.\n</think>\n\nThis week has:"
    assert strip_think(text) == "This week has:"
    assert strip_think("<think>x</think>Answer") == "Answer"
    assert strip_think("Plain answer") == "Plain answer"


def _stream(chunks):
    f = ThinkFilter()
    out = "".join(f.feed(c) for c in chunks) + f.flush() + f.tail()
    return out


def test_think_filter_orphan_in_head_is_dropped():
    out = _stream(["Okay, let me ", "think.\n</thi", "nk>\n\nHere ", "you go."])
    assert out == "Here you go."


def test_think_filter_orphan_after_release_emits_reset():
    reasoning = "Let me reason about this carefully. " * 10   # > HOLD_CHARS
    out = _stream([reasoning, "more\n</think>\n", "Final answer."])
    assert RESET in out and out.split(RESET)[-1] == "Final answer."


def test_think_filter_short_plain_and_tagged():
    assert _stream(["Hi ", "there!"]) == "Hi there!"
    assert _stream(["<think>hidden</think>", "Shown"]) == "Shown"
    assert _stream(["a < b and </br"]) == "a < b and </br"


class BrokenEventKit(FakeEventKit):
    async def list(self, start, end):
        raise RuntimeError("bridge exploded")


def test_eventkit_runtime_error_falls_back():
    runner = Runner()
    res = _list(calendar_tools(runner, BrokenEventKit(), "auto"))
    assert "via AppleScript (EventKit: error: RuntimeError)" in res.display
    assert runner.calls == ["calendar_list", "calendar_recurring"]
    try:
        _list(calendar_tools(Runner(), BrokenEventKit(), "eventkit"))
    except ToolError as exc:
        assert "EventKit failed" in str(exc)


def test_access_is_requested_only_once():
    ek = EventKitCalendar(ek=object(), foundation=object())
    calls = []
    ek._request_sync = lambda timeout: calls.append(timeout) or False
    assert asyncio.run(ek.request_access()) is False
    assert asyncio.run(ek.request_access()) is False
    assert calls == [60]


# ── repeating events via AppleScript + RRULE expansion ───────────────────
from localagent.connectors.recurrence import expand, merge  # noqa: E402

US, RS = "\x1f", "\x1e"
WEEK = (datetime(2026, 10, 5), datetime(2026, 10, 12))   # Mon 5 Oct .. Mon 12 Oct


def _series(title, start, end, rrule, excluded="", cal="Work", all_day=False):
    return {"title": title, "start": start, "end": end, "rrule": rrule, "calendar": cal,
            "all_day": all_day, "location": "", "excluded": [x for x in excluded.split(",") if x]}


def _starts(events):
    return [e["start"] for e in events]


def test_weekly_byday_series_started_long_ago():
    s = _series("ViTea Touch", "2023-01-03 08:00:00", "2023-01-03 08:30:00", "FREQ=WEEKLY;BYDAY=TU,FR")
    out = expand([s], *WEEK)
    assert _starts(out) == ["2026-10-06T08:00", "2026-10-09T08:00"]
    assert all(e["recurring"] and e["end"][11:] == "08:30" for e in out)


def test_interval_count_until_and_exclusions():
    biweekly = _series("Sync", "2026-09-25 09:00:00", "2026-09-25 10:00:00", "FREQ=WEEKLY;INTERVAL=2")
    assert _starts(expand([biweekly], *WEEK)) == ["2026-10-09T09:00"]
    counted = _series("Course", "2026-10-01 18:00:00", "2026-10-01 19:00:00", "FREQ=DAILY;COUNT=5")
    assert _starts(expand([counted], *WEEK)) == ["2026-10-05T18:00"]          # Oct 1..5
    ended = _series("Old", "2026-09-01 09:00:00", "2026-09-01 10:00:00", "RRULE:FREQ=DAILY;UNTIL=20260930T235959Z")
    assert expand([ended], *WEEK) == []
    skip = _series("Daily", "2026-10-01 07:00:00", "2026-10-01 07:15:00", "FREQ=DAILY",
                   excluded="2026-10-07 07:00:00,")
    starts = _starts(expand([skip], *WEEK))
    assert "2026-10-07T07:00" not in starts and len(starts) == 6


def test_all_day_and_bad_rules():
    bday = _series("Birthday", "2000-10-08 00:00:00", "2000-10-09 00:00:00", "FREQ=YEARLY", all_day=True)
    out = expand([bday, _series("Broken", "2026-10-01 09:00:00", "2026-10-01 10:00:00", "FREQ=NOPE")], *WEEK)
    assert [(e["title"], e["start"], e["all_day"]) for e in out] == [("Birthday", "2026-10-08T00:00", True)]


def test_merge_dedupes_base_events():
    base = [{"title": "Sync", "start": "2026-10-09T09:00", "end": "2026-10-09T10:00", "calendar": "Work"}]
    extra = [{"title": "Sync", "start": "2026-10-09T09:00", "end": "x", "calendar": "Work", "recurring": True},
             {"title": "Sync", "start": "2026-10-09T09:00", "end": "x", "calendar": "Home", "recurring": True}]
    assert len(merge(base, extra)) == 2


def test_tool_lists_repeating_meetings_without_eventkit():
    rec = (f"ViTea Touch{US}2023-01-03 08:00:00{US}2023-01-03 08:30:00{US}Zoom{US}Work{US}false{US}FREQ=WEEKLY;BYDAY=TU,FR{US}{RS}"
           f"Vantree Weekly Sync{US}2025-06-06 09:00:00{US}2025-06-06 10:00:00{US}{US}Work{US}false{US}FREQ=WEEKLY;BYDAY=FR{US}{RS}")
    res = _list(calendar_tools(Runner(recurring=rec), FakeEventKit(status="denied"), "auto"),
                start="2026-10-05", end="2026-10-11")
    titles = [e["title"] for e in res.data]
    assert titles.count("ViTea Touch") == 2 and titles.count("Vantree Weekly Sync") == 1
    assert "(repeats)" in res.content


def test_status_detail_strings():
    ek = EventKitCalendar(ek=object(), foundation=object())
    ek.authorization = lambda: "denied"
    assert ek.status_detail() == "access denied"
    ek.authorization = lambda: "not_determined"
    assert ek.status_detail() == "not asked yet"
    ek._asked = True
    assert ek.status_detail() == "asked but not answered"
    ek.authorization = lambda: "authorized"
    assert ek.status_detail() == "ok"


def test_calendar_access_cli(monkeypatch):
    from typer.testing import CliRunner

    from localagent import cli

    ek = FakeEventKit(status="not_determined")
    monkeypatch.setattr(cli, "_eventkit", lambda: ek)
    r = CliRunner().invoke(cli.app, ["calendar-access"])
    assert r.exit_code == 0 and "Granted" in r.stdout and ek.requested == 1
    ek.status = "denied"
    r = CliRunner().invoke(cli.app, ["calendar-access"])
    assert r.exit_code == 1 and "Privacy & Security" in r.stdout
