"""Ask about privacy & security in plain language: "what can you read?", "what did you send last
week?", "who can text you?", "is screen context on?".

Answers come from the agent's own records (settings, the Trust center's checks, the audit log),
never from the model's imagination:
1. Common questions are answered directly from those records, with no model at all.
2. Anything else goes to the local model with a compact facts sheet and the instruction to answer
   only from it. The facts never include text written by other people (no message bodies, page
   text or URLs), so nothing in your mail or the web can steer the answer.
Every answer lists the facts it used, so you can check it.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from . import trust

if TYPE_CHECKING:
    from .runtime import Runtime

TRUST_WORDS = re.compile(
    r"\b(privacy|private|security|secure|safe|trust|permission|permissions|access|"
    r"what (did|have) you (send|sent|share|shared|upload)|"
    r"(what|which) (data|information|info)|who can|"
    r"left (this|my) (computer|mac|laptop)|leak|encrypt|keychain|"
    r"(can|do) you (see|read|access|reach|hear|listen))\b", re.I)


# In chat, only clear questions about the agent itself: "can you read my email?" is usually a task.
CHAT_TRUST = re.compile(
    r"\b(privacy|security|permissions?|trust (tab|center)|what (did|have) you (send|sent|share|shared|upload)|"
    r"what (data|information|info) (do|did|can) you|who can (control|text|call|message|reach|access)|"
    r"left (this|my) (computer|mac|laptop)|leak(ed|ing)?|encrypt(ed|ion)?|what can you (access|see|reach)|"
    r"(is|are) (my|your) data (safe|private|stored)|is it safe)\b", re.I)


def is_chat_trust_question(text: str) -> bool:
    return bool(CHAT_TRUST.search(text)) and is_trust_question(text)


def is_trust_question(text: str) -> bool:
    """A question about the agent's own access, data and safety (not a task)."""
    t = text.strip()
    return bool(TRUST_WORDS.search(t)) and ("?" in t or re.match(
        r"^(what|which|who|is|are|can|do|does|did|have|has|how|tell me|show me|list)\b", t, re.I) is not None)


def facts(rt: "Runtime", days: int = 7) -> dict:
    """What the agent can do and did, as plain data. No content written by others."""
    now = time.time()
    caps = trust.capabilities(rt)
    ledger = trust.egress_ledger(rt, now - days * 86400, now)
    by = Counter((e["what"], e["to"]) for e in ledger)
    rows = rt.store.query("SELECT kind, tool, tier, outcome, ts, detail FROM audit WHERE ts >= ? ORDER BY id",
                          (now - days * 86400,))
    actions = Counter(r["tool"] for r in rows if r["kind"] == "tool_call" and r["tier"] in ("write", "danger"))
    sensitive = [{"setting": r["tool"], "when": datetime.fromtimestamp(r["ts"]).strftime("%a %d %b %H:%M")}
                 for r in rows if r["kind"] == "settings_changed" and r["outcome"] == "sensitive"]
    blocked = Counter(r["kind"] for r in rows if r["kind"] in
                      ("phone_rejected", "peer_rejected", "channel_ignored", "phone_pin_wrong", "injection_flagged"))
    return {
        "days": days,
        "paused": rt.settings.paused,
        "preset": rt.settings.autonomy,
        "capabilities_on": [{"name": c["name"], "id": c["id"], "risk": c["risk"], "reads": c["reads"],
                             "can_leave": c["leaves"], "permission": [p["name"] for p in c["permissions"]]}
                            for c in caps if c["enabled"]],
        "capabilities_off": [c["name"] for c in caps if c["available"] and not c["enabled"]],
        "left_this_computer": [{"what": w, "to": to, "times": n} for (w, to), n in by.most_common(20)],
        "left_total": len(ledger),
        "actions_done": dict(actions.most_common(15)),
        "standing_permissions": [{"tool": g["tool"], "scope": g["scope"], "target": g.get("target")}
                                 for g in rt.policy.active_grants()],
        "sensitive_setting_changes": sensitive[-10:],
        "blocked_attempts": dict(blocked),
        "safety_checks": [{"check": p["name"], "ok": p["ok"], "detail": p["detail"]} for p in trust.posture(rt)],
        "secrets_kept_in": rt.vault.backend,
        "data_folder": str(rt.base),
    }


# ── direct answers from the records ─────────────────────────────────────────
def _cap_mentioned(question: str, f: dict, caps: list[dict]) -> list[dict]:
    q = question.lower()
    words = {
        "screen": "screen", "messages": "messages", "imessage": "messages", "whatsapp": "messages",
        "mail": "mail", "email": "mail", "gmail": "gmail", "calendar": "calendar", "contacts": "contacts",
        "browser": "browser", "web": "web", "cloud": "cloud", "claude": "cloud", "phone": "phone",
        "call": "phone", "wake": "wake", "hey ": "wake", "microphone": "wake", "mic": "wake", "skill": "skills",
        "files": "files", "notes": "notes", "reminders": "reminders", "friend": "peers", "agents": "peers",
        "nudge": "proactive", "brief": "proactive", "text you": "imessage_channel", "texting": "imessage_channel",
        "apps": "apps", "shortcut": "apps",
    }
    ids = []
    for w, cid in words.items():
        if w in q and cid not in ids:
            ids.append(cid)
    return [c for c in caps if c["id"] in ids]


def _answer_from_records(rt: "Runtime", question: str, f: dict) -> dict | None:
    q = question.lower()
    caps = trust.capabilities(rt)
    mentioned = _cap_mentioned(question, f, caps)
    on = f["capabilities_on"]

    def done(text: str, used: list[str], actions: list[dict] | None = None) -> dict:
        return {"answer": text, "facts": used, "actions": actions or [], "source": "records"}

    def toggles(cs: list[dict]) -> list[dict]:
        return [{"label": f"Turn {'off' if c['enabled'] else 'on'} {c['name']}", "capability": c["id"],
                 "enabled": not c["enabled"]} for c in cs if c["available"]]

    if re.search(r"\b(sen[dt]\w*|shar\w*|upload\w*|left|leav\w*|leak\w*|went out|outgoing|internet)\b", q):
        if not f["left_this_computer"]:
            return done(f"Nothing left this computer in the last {f['days']} days.",
                        [f"Outgoing items in the last {f['days']} days: 0"])
        lines = [f"- {x['what']} → {x['to']} ({x['times']}×)" for x in f["left_this_computer"]]
        return done(f"In the last {f['days']} days, {f['left_total']} thing(s) left this computer:\n" + "\n".join(lines)
                    + "\nEach one is listed with its content under Trust → Activity.",
                    [f"Audit log, last {f['days']} days: {f['left_total']} outgoing item(s)"])
    if mentioned and re.search(r"\b(is|are|on|off|enabled|using|use)\b", q):
        lines = [f"- {c['name']}: {'ON' if c['enabled'] else 'off'}" + (f" (reads: {c['reads']})" if c["enabled"] else "")
                 + ("" if c["available"] else " (needs a Mac)") for c in mentioned]
        return done("\n".join(lines), [f"Setting {c['setting']} = {c['enabled']}" for c in mentioned], toggles(mentioned))
    if re.search(r"\bwho\b.*\b(control\w*|text\w*|call\w*|message\w*|reach|contact|talk|command\w*|access)\b", q):
        ch = {c["id"]: c for c in caps}
        parts = []
        for cid, what in (("imessage_channel", "by iMessage"), ("phone", "by phone"), ("peers", "friends' agents")):
            c = ch.get(cid)
            if c:
                parts.append(f"- {what}: {'allowed' if c['enabled'] else 'off'}")
        s = rt.settings
        detail = []
        if s.enable_imessage_channel:
            detail.append(f"iMessage: only {s.imessage_owner_handles or 'your own handles'}")
        if s.phone_enabled:
            detail.append(f"Phone: only {s.phone_owner_numbers or 'your numbers'}, with your PIN on every call")
        text = ("Only you, in this app (it needs this computer's secret). Other ways in:\n" + "\n".join(parts)
                + ("\n" + "\n".join(detail) if detail else ""))
        return done(text, ["Settings: enable_imessage_channel, phone_enabled, a2a_enabled",
                           "App sign-in: per-install secret, 127.0.0.1 only"])
    if re.search(r"\b(encrypt\w*|stor(e|ed|age)|where.*(data|kept)|keychain|passwords?|secrets?|disk)\b", q):
        enc = next((p for p in f["safety_checks"] if p["check"] == "Disk encryption"), None)
        text = (f"Your agent's data is in {f['data_folder']}, readable only by you. Passwords, tokens and keys are "
                f"in {f['secrets_kept_in']}, never in that folder, the log or what the model sees."
                + (f"\nDisk encryption: {enc['detail']}." if enc else ""))
        return done(text, ["Data folder permissions check", "Vault backend", "Disk encryption check"])
    if re.search(r"\b(safe|risk|risky|secure|attention|problem|worr|ok\b|okay)", q):
        bad = [p for p in f["safety_checks"] if p["ok"] is False]
        high = [c for c in on if c["risk"] == "high"]
        lines = ([f"- ⚠ {p['check']}: {p['detail']}" for p in bad] or ["- All safety checks pass."])
        if high:
            lines.append("High-risk capabilities that are on: " + ", ".join(c["name"] for c in high))
        if f["blocked_attempts"]:
            lines.append("Blocked attempts this week: " + ", ".join(f"{k} ×{v}" for k, v in f["blocked_attempts"].items()))
        return done("\n".join(lines), ["Trust safety checks", "Capabilities that are on", "Audit log: blocked attempts"],
                    toggles([c for c in caps if c["enabled"] and c["risk"] == "high"]))
    if re.search(r"\b(what did you do|did you do|actions?|activity|changed)\b", q):
        if not f["actions_done"]:
            return done(f"No actions that send or change anything in the last {f['days']} days.",
                        ["Audit log: write/danger tool calls"])
        lines = [f"- {k}: {v}×" for k, v in f["actions_done"].items()]
        return done(f"Actions in the last {f['days']} days:\n" + "\n".join(lines), ["Audit log: write/danger tool calls"])
    if re.search(r"\b(access|read|see|reach|hear|listen|permission|permissions|what can you|capabilit)", q):
        if mentioned:
            return done("\n".join(f"- {c['name']}: {'ON — ' + c['reads'] if c['enabled'] else 'off'}" for c in mentioned),
                        [f"Setting {c['setting']}" for c in mentioned], toggles(mentioned))
        lines = [f"- {c['name']} ({c['risk']} risk): {c['reads']}" + (f" [system permission: {', '.join(c['permission'])}]"
                 if c["permission"] else "") for c in on]
        tail = f"\nOff: {', '.join(f['capabilities_off'])}." if f["capabilities_off"] else ""
        return done("What I can reach right now:\n" + "\n".join(lines) + tail, ["Capabilities that are on (settings)"])
    if re.search(r"\b(pause|stop everything|turn (you|it) off)\b", q):
        return done("Press ⏸ Pause at the top (or run `localagent pause`, or text “pause”). While paused I only answer "
                    "you in the app, read-only: no actions, no background checks, no calls or texts.", ["Pause feature"])
    return None


SYSTEM = ("You answer the user's questions about their own AI agent's privacy and security. Use ONLY the facts "
          "below (JSON from the agent's settings and logs). If the facts don't answer it, say you don't know from "
          "your records and suggest where in the Trust tab to look. Be short and plain. Never invent capabilities, "
          "destinations or numbers.")


async def ask(rt: "Runtime", question: str) -> dict:
    question = (question or "").strip()[:500]
    if not question:
        return {"answer": "Ask me anything about what I can access, what I did, or what left this computer.",
                "facts": [], "actions": [], "source": "records"}
    f = facts(rt)
    direct = _answer_from_records(rt, question, f)
    if direct:
        rt.audit.append("trust_question", "trust", outcome="records", detail=question[:200])
        return direct
    try:
        text = await rt.ollama.chat_text(rt.settings.fast_model, [
            {"role": "system", "content": SYSTEM + "\n\nFACTS:\n" + json.dumps(f, ensure_ascii=False)},
            {"role": "user", "content": question}], temperature=0.1)
    except Exception as exc:  # noqa: BLE001 - the model may be down; say so instead of failing
        text = f"I couldn't reach the local model ({exc.__class__.__name__}). The Trust tab shows the same records."
    rt.audit.append("trust_question", "trust", outcome="model", detail=question[:200])
    return {"answer": text.strip(), "facts": ["Settings, capabilities, safety checks, standing permissions and the "
                                              f"audit log summary for the last {f['days']} days"],
            "actions": [], "source": "model"}
