"""Fill in a web form from what the agent remembers about you, then stop for your review.

The model proposes a value for each field it can answer from memory (with the memory it
used), the agent types those values into the agent's browser window, and nothing is
submitted: sending the form is `browser_submit`, which asks you every time.
Passwords, card numbers, security codes and government ID numbers are never filled.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..tools.base import Tool, ToolError, ToolResult, obj, s

if TYPE_CHECKING:
    from ..runtime import Runtime

SENSITIVE = re.compile(r"\b(password|passcode|pin|card ?number|credit card|debit card|cvv|cvc|security code|"
                       r"expir\w*|iban|routing|account number|sort code|ssn|social security|national insurance|"
                       r"tax id|one[- ]time|otp|verification code)\b", re.IGNORECASE)
FILL_SCHEMA = {
    "type": "object",
    "properties": {"fields": {"type": "array", "items": {
        "type": "object",
        "properties": {"ref": {"type": "integer"}, "value": {"type": "string"}, "source": {"type": "string"}},
        "required": ["ref", "value", "source"]}}},
    "required": ["fields"],
}
PROMPT = """Fill in a web form for the user, using ONLY the facts below. For each field you can answer
from the facts, give its number, the value to type, and the fact you used. Skip any field the facts
don't answer: never guess or invent. For a dropdown, the value must be one of its options.
{extra}
FACTS ABOUT THE USER:
{facts}

FORM FIELDS ON "{title}":
{fields}

Reply with JSON."""


def fillable(e: dict) -> bool:
    return (e["tag"] in ("input", "textarea", "select") and not e.get("password") and not e.get("submits")
            and e.get("type") not in ("checkbox", "radio", "file", "button", "reset", "image", "hidden"))


def form_tools(rt: "Runtime") -> list[Tool]:
    def snapshot() -> dict:
        snap = (getattr(rt.browser, "la_state", None) or {}).get("snap")
        if not snap:
            raise ToolError("Open the page with the form first (browser_open).")
        return snap

    async def fill(a: dict) -> ToolResult:
        snap = snapshot()
        fields = [e for e in snap["elements"] if fillable(e)]
        safe = [e for e in fields if not SENSITIVE.search(e.get("label") or "")]
        if not safe:
            raise ToolError("There are no fields on this page the agent may fill in.")
        mems = rt.store.list_memories()[:80]
        if not mems:
            raise ToolError("The agent doesn't know anything about you yet. Tell it in chat first "
                            "(e.g. “my address is …”), or add facts in the Memory tab.")
        facts = "\n".join(f"- ({m.kind}) {m.text}" for m in mems)
        flines = "\n".join(
            f"[{e['ref']}] {e['label'] or '(no label)'} ({e['type'] or e['tag']})"
            + (f" options: {', '.join(e['options'][:15])}" if e.get("options") else "") for e in safe)
        extra = f"Extra instructions from the user: {a['notes']}\n" if a.get("notes") else ""
        out = await rt.ollama.chat_json(rt.settings.chat_model, [{"role": "user", "content": PROMPT.format(
            extra=extra, facts=facts, fields=flines, title=snap["title"])}], FILL_SCHEMA)
        by_ref = {e["ref"]: e for e in safe}
        filled, rows = [], []
        for item in out.get("fields") or []:
            try:
                ref = int(item.get("ref"))
            except (TypeError, ValueError):
                continue
            value = str(item.get("value") or "").strip()
            e = by_ref.get(ref)
            if e is None or not value or ref in filled:
                continue
            if e.get("options") and value not in e["options"]:
                continue
            await rt.browser.fill(ref, value)
            filled.append(ref)
            rows.append({"field": e["label"] or f"[{ref}]", "value": value, "from": str(item.get("source", ""))[:120]})
        snap = await rt.browser.snapshot()
        rt.browser.la_state["snap"] = snap
        left = [e["label"] or f"[{e['ref']}]" for e in fields if e["ref"] not in filled]
        lines = [f"- {r['field']}: “{r['value']}” (from: {r['from']})" for r in rows]
        text = (f"Filled {len(rows)} field(s) on “{snap['title']}” from memory. Nothing was submitted.\n"
                + ("\n".join(lines) or "(nothing could be filled from memory)")
                + (f"\nLeft for the user: {', '.join(left[:20])}" if left else "")
                + "\nAsk the user to check the browser window before anything is submitted.")
        return ToolResult(text, f"Filled {len(rows)} field(s) — please review", rows)

    return [Tool("browser_fill_form",
                 "Fill in the form on the current browser page from what the agent remembers about the user. "
                 "Never submits; the user reviews first.",
                 obj({"notes": s("Optional extra instructions, e.g. 'use my work email'")}),
                 "draft", "browser", fill, lambda a: "Fill in the form from memory", ("task", "computer_action"))]
