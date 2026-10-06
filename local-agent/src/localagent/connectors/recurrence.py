"""Expand repeating calendar events from their RRULE.

AppleScript's Calendar dictionary only matches a repeating series by its first
start date, so occurrences inside the requested window are missing. The series'
iCalendar RRULE (e.g. FREQ=WEEKLY;BYDAY=TU,FR) is expanded here instead.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from dateutil.rrule import rrulestr

log = logging.getLogger(__name__)

MAX_PER_SERIES = 500
_UNTIL_UTC = re.compile(r"UNTIL=(\d{8}T\d{6})Z", re.IGNORECASE)


def parse_local(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def _local_until(rule: str) -> str:
    """dateutil refuses a UTC UNTIL with a naive DTSTART; convert UNTIL to local time."""
    def repl(m: re.Match) -> str:
        utc = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return "UNTIL=" + utc.astimezone().replace(tzinfo=None).strftime("%Y%m%dT%H%M%S")
    return _UNTIL_UTC.sub(repl, rule)


def expand(series: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Occurrences of each series overlapping [start, end)."""
    out: list[dict] = []
    for s in series:
        try:
            dtstart = parse_local(s["start"])
            duration = parse_local(s["end"]) - dtstart
            rule_text = s["rrule"].strip()
            if rule_text.upper().startswith("RRULE:"):
                rule_text = rule_text[6:]
            rule = rrulestr(_local_until(rule_text), dtstart=dtstart)
            excluded = {parse_local(x) for x in s.get("excluded", []) if x.strip()}
        except (ValueError, KeyError, TypeError) as exc:
            log.info("skipping repeating event %r: %s", s.get("title"), exc)
            continue
        excluded_days = {x.date() for x in excluded}
        count = 0
        for occ in rule.between(start - max(duration, timedelta(0)), end, inc=True):
            if count >= MAX_PER_SERIES:
                break
            if occ in excluded or (s.get("all_day") and occ.date() in excluded_days):
                continue
            if occ + duration <= start or occ >= end:
                continue
            count += 1
            out.append({
                "title": s["title"], "start": occ.isoformat(timespec="minutes"),
                "end": (occ + duration).isoformat(timespec="minutes"),
                "location": s.get("location", ""), "calendar": s.get("calendar", ""),
                "account": "", "all_day": bool(s.get("all_day")), "recurring": True, "status": None,
            })
    return out


def merge(base: list[dict], expanded: list[dict]) -> list[dict]:
    """Base events win; expanded occurrences fill the gaps (dedupe by title, start, calendar)."""
    seen = {(e["title"], e["start"][:16], e.get("calendar", "")) for e in base}
    merged = list(base)
    for e in expanded:
        key = (e["title"], e["start"][:16], e.get("calendar", ""))
        if key not in seen:
            seen.add(key)
            merged.append(e)
    return merged
