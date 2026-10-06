"""Which tool calls can carry data off this computer, where to, and when that needs a person.

Used by the tool loop (agent/actions.py) to gate egress, and by the Trust center to build the
"what left this computer" ledger.

The danger (the "lethal trifecta") is one run that has private data, has read text written by
someone else, and can send things out: hidden instructions in that text can make the model
send the private data away. Pattern scanning can't catch every phrasing, so once a run has
read untrusted content:
- sends (email, iMessage, friend's agent, cloud, network skills) always need a fresh approval,
  even if a standing permission exists;
- opening a web address runs by itself only if that exact address was already in front of the
  agent (a link on a page or in your message): such a link can't carry new data;
- text typed into a web page or a search runs by itself only if every word came from your own
  message in this request.
Before any untrusted content is read, only an unusually long query string needs approval.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..tools.base import Tool

MAX_QUERY = 120
WORD = re.compile(r"[\w@.+-]+", re.UNICODE)
STOP = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "for", "to", "near", "me", "my", "is",
        "what", "how", "much", "price", "prices", "best", "open", "now", "today"}


def domain(url: str) -> str:
    try:
        return (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    except ValueError:
        return ""


def _send(to_key: str, what: str):
    return lambda a: {"to": str(a.get(to_key, "")), "kind": "send", "text": f"{a.get('subject', '')}\n{a.get('body') or a.get('text') or ''}".strip(), "what": what}


EGRESS = {
    "web_search": lambda a: {"to": "DuckDuckGo", "kind": "search", "text": str(a.get("query", "")), "what": "search query"},
    "browser_open": lambda a: {"to": domain(str(a.get("url", ""))), "kind": "url", "url": str(a.get("url", "")), "what": "web address"},
    "browser_type": lambda a: {"to": "the open web page", "kind": "type", "text": str(a.get("text", "")), "what": "typed text"},
    "browser_fill_form": lambda a: {"to": "the open web page", "kind": "form", "text": None, "what": "form values from memory"},
    "gmail_send": _send("to", "email (Gmail)"),
    "mail_send": _send("to", "email (Mail)"),
    "imessage_send": _send("thread", "iMessage"),
    "peer_ask": lambda a: {"to": f"{a.get('peer', '')}'s agent", "kind": "send", "text": str(a.get("text", "")), "what": "message to a friend's agent"},
    "cloud_ask": lambda a: {"to": "Anthropic (cloud model)", "kind": "send", "text": str(a.get("question", "")), "what": "question to the cloud model"},
}


def describe(tool: Tool, args: dict) -> dict | None:
    """Where this call would send data, or None if it can't send anything out."""
    if tool.egress is not None:
        return tool.egress(args)
    fn = EGRESS.get(tool.name)
    return fn(args) if fn else None


def words(text: str) -> set[str]:
    return {w.lower().strip(".") for w in WORD.findall(text or "")} - STOP - {""}


def risky(tool: Tool, args: dict, tier: str, read_untrusted: bool, user_text: str, seen_text: str) -> str | None:
    """A reason this egress needs a person's approval, or None if it may run under the normal rules."""
    e = describe(tool, args)
    if e is None:
        return None
    if tier in ("write", "danger"):
        return ("It sends data out after reading content written by others, so standing permissions "
                "don't apply.") if read_untrusted else None
    if e["kind"] == "url":
        url = e["url"].strip()
        query = urlsplit(url).query if "://" in url else ""
        if read_untrusted and url.rstrip("/") not in seen_text and url not in seen_text:
            return (f"It opens {e['to'] or 'a web address'} that wasn't a link the agent had seen, after "
                    "reading content written by others; check the full address.")
        if len(query) > MAX_QUERY and url not in user_text:
            return f"The address carries {len(query)} characters of data to {e['to']}; check it."
        return None
    if e["kind"] == "form":
        return ("It types details about you into a web page after reading that page; check the values."
                if read_untrusted else None)
    if e["kind"] in ("type", "search") and read_untrusted:
        extra = words(e.get("text") or "") - words(user_text)
        if extra:
            return (f"It sends words that weren't in your request ({', '.join(sorted(extra)[:5])}) to "
                    f"{e['to']} after reading content written by others.")
    return None
