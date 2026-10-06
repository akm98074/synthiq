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

    async def request_access(self):
        self.requested += 1
        self.status = "authorized"
        return True

    async def list(self, start, end):
        return sorted((event_to_dict(e) for e in self.events), key=lambda e: e["start"])


class Runner:
    def __init__(self): self.calls = []
    async def run(self, name, args):
        self.calls.append(name)
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


def test_eventkit_requests_access_once_then_uses_it():
    ek = FakeEventKit(status="not_determined", events=[_event("A", datetime(2026, 10, 6, 9))])
    res = _list(calendar_tools(Runner(), ek, "auto"), start="2026-10-06")
    assert ek.requested == 1 and "via EventKit" in res.display


def test_fallback_to_applescript_with_note_when_denied():
    runner = Runner()
    res = _list(calendar_tools(runner, FakeEventKit(status="denied"), "auto"))
    assert runner.calls == ["calendar_list"] and "via AppleScript" in res.display
    assert APPLESCRIPT_NOTE in res.content


def test_forced_eventkit_denied_raises_help():
    try:
        _list(calendar_tools(Runner(), FakeEventKit(status="denied"), "eventkit"))
    except ToolError as exc:
        assert "Privacy & Security" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def test_forced_applescript_and_no_eventkit():
    runner = Runner()
    _list(calendar_tools(runner, FakeEventKit(), "applescript"))
    _list(calendar_tools(runner, None, "auto"))
    assert runner.calls == ["calendar_list", "calendar_list"]


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
    assert "via AppleScript" in res.display and runner.calls == ["calendar_list"]
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
