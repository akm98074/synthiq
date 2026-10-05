"""Calendar via Apple's EventKit framework (pyobjc).

EventKit reads the same calendar store that Calendar.app shows (iCloud, Google,
Outlook/Exchange, subscribed calendars). Unlike AppleScript it expands repeating
events into their individual occurrences. It needs "Full Access" to calendars,
which macOS asks for once and attributes to the app that started the agent
(usually Terminal).
"""
from __future__ import annotations

import asyncio
import sys
import threading
from datetime import datetime
from typing import Any

# EKAuthorizationStatus
_STATUS = {0: "not_determined", 1: "restricted", 2: "denied", 3: "authorized", 4: "write_only"}
# EKParticipantStatus
_PARTICIPATION = {1: "pending", 2: "accepted", 3: "declined", 4: "tentative"}

DENIED_HELP = ("macOS hasn't given the agent access to your calendars. Open System Settings → "
               "Privacy & Security → Calendars, set Terminal to 'Full Access', then restart the agent "
               "from Terminal.")


def _call(obj: Any, name: str, default=None):
    try:
        value = getattr(obj, name)()
    except Exception:  # noqa: BLE001 - optional ObjC properties may be missing or raise
        return default
    return default if value is None else value


def event_to_dict(e: Any) -> dict:
    """Convert an EKEvent (or a test double with the same selectors) to plain data."""
    start = datetime.fromtimestamp(_call(e, "startDate").timeIntervalSince1970())
    end = datetime.fromtimestamp(_call(e, "endDate").timeIntervalSince1970())
    cal = _call(e, "calendar")
    source = _call(cal, "source") if cal is not None else None
    status = None
    for att in _call(e, "attendees", []) or []:
        if _call(att, "isCurrentUser", False):
            status = _PARTICIPATION.get(int(_call(att, "participantStatus", 0)))
            break
    return {
        "title": str(_call(e, "title", "") or "(no title)"),
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
        "location": str(_call(e, "location", "") or ""),
        "calendar": str(_call(cal, "title", "") or "") if cal is not None else "",
        "account": str(_call(source, "title", "") or "") if source is not None else "",
        "all_day": bool(_call(e, "isAllDay", False)),
        "recurring": bool(_call(e, "hasRecurrenceRules", False)),
        "status": status,
    }


class EventKitCalendar:
    name = "EventKit"

    def __init__(self, ek: Any = None, foundation: Any = None):
        self._ek = ek
        self._foundation = foundation
        self._asked = False      # ask macOS for access at most once per process

    def _modules(self):
        if self._ek is None:
            import EventKit  # type: ignore[import-not-found]
            import Foundation  # type: ignore[import-not-found]

            self._ek, self._foundation = EventKit, Foundation
        return self._ek, self._foundation

    def installed(self) -> bool:
        if self._ek is not None:
            return True
        if sys.platform != "darwin":
            return False
        try:
            self._modules()
            return True
        except Exception:  # noqa: BLE001 - pyobjc missing or broken
            return False

    def authorization(self) -> str:
        if not self.installed():
            return "unavailable"
        ek, _ = self._modules()
        code = int(ek.EKEventStore.authorizationStatusForEntityType_(ek.EKEntityTypeEvent))
        return _STATUS.get(code, "unknown")

    def _request_sync(self, timeout: float) -> bool:
        ek, _ = self._modules()
        store = ek.EKEventStore.alloc().init()
        done = threading.Event()
        result = {"granted": False}

        def handler(granted, _error):
            result["granted"] = bool(granted)
            done.set()

        if hasattr(store, "requestFullAccessToEventsWithCompletion_"):   # macOS 14+
            store.requestFullAccessToEventsWithCompletion_(handler)
        else:
            store.requestAccessToEntityType_completion_(ek.EKEntityTypeEvent, handler)
        done.wait(timeout)
        return result["granted"]

    async def request_access(self, timeout: float = 60) -> bool:
        """Show the macOS prompt once. If it's dismissed or never answered, later calls
        return immediately so calendar look-ups (and the 30-minute checks) never stall."""
        if self._asked:
            return False
        self._asked = True
        try:
            return await asyncio.to_thread(self._request_sync, timeout)
        except Exception:  # noqa: BLE001 - treat any bridge failure as "not granted"
            return False

    def _list_sync(self, start: datetime, end: datetime) -> list[dict]:
        ek, foundation = self._modules()
        store = ek.EKEventStore.alloc().init()
        ns_start = foundation.NSDate.dateWithTimeIntervalSince1970_(start.timestamp())
        ns_end = foundation.NSDate.dateWithTimeIntervalSince1970_(end.timestamp())
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(ns_start, ns_end, None)
        events = [event_to_dict(e) for e in (store.eventsMatchingPredicate_(predicate) or [])]
        return sorted(events, key=lambda e: (e["start"], e["title"]))

    async def list(self, start: datetime, end: datetime) -> list[dict]:
        return await asyncio.to_thread(self._list_sync, start, end)
