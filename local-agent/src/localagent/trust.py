"""Trust & Transparency center: what the agent can do, what it did, what left this computer, and
an export anyone (a person, or another AI such as Claude or ChatGPT) can use to check it.

Everything here is computed from the settings, the policy store and the hash-chained audit log;
nothing is sent anywhere. The export is a zip the user downloads and decides what to do with.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__
from .safety import pii
from .safety.egress import EGRESS, describe

if TYPE_CHECKING:
    from .runtime import Runtime

_MAC = "x-apple.systempreferences:com.apple.preference.security?"
PERMISSIONS = {
    "fda": ("Full Disk Access", _MAC + "Privacy_AllFiles"),
    "automation": ("Automation", _MAC + "Privacy_Automation"),
    "calendars": ("Calendars", _MAC + "Privacy_Calendars"),
    "reminders": ("Reminders", _MAC + "Privacy_Reminders"),
    "contacts": ("Contacts", _MAC + "Privacy_Contacts"),
    "accessibility": ("Accessibility", _MAC + "Privacy_Accessibility"),
    "screen": ("Screen Recording", _MAC + "Privacy_ScreenCapture"),
}

# One row per capability the user can switch on or off. `connectors` are tool connector names and
# `kinds` audit kinds, used to show when it was last used.
CAPABILITIES = [
    dict(id="calendar", name="Calendar", setting="enable_calendar", mac=True, perms=["calendars", "automation"],
         connectors={"calendar"}, risk="low",
         reads="Your calendar events: titles, times, places, people invited.",
         leaves="Nothing by itself. Busy times (never titles) to a friend's agent only if you allow it.",
         risk_text="Invites are written by other people and can contain instructions; they are treated as untrusted.",
         safeguards="Adding events asks first unless you allowed it; invites are fenced as untrusted data."),
    dict(id="reminders", name="Reminders", setting="enable_reminders", mac=True, perms=["reminders", "automation"],
         connectors={"reminders"}, risk="low", reads="Your open reminders.", leaves="Nothing.",
         risk_text="Low: it reads and adds reminders.", safeguards="Adding asks first unless you allowed it."),
    dict(id="notes", name="Notes", setting="enable_notes", mac=True, perms=["automation"], connectors={"notes"},
         risk="low", reads="Notes matching what you ask about.", leaves="Nothing.",
         risk_text="Notes may hold private details; they're only searched when you ask.",
         safeguards="Read only when needed; creating a note asks first unless allowed."),
    dict(id="mail", name="Mail (Apple)", setting="enable_mail", mac=True, perms=["automation"], connectors={"mail"},
         risk="medium", reads="Your inbox: senders, subjects, message text.",
         leaves="Emails you approve, to the recipients shown on the approval.",
         risk_text="Emails are written by others and may try to instruct the agent; sending can't be undone.",
         safeguards="Mail is untrusted data; sending always shows the full email for your OK, and after reading "
                    "mail no standing permission applies."),
    dict(id="contacts", name="Contacts", setting="enable_contacts", mac=True, perms=["contacts", "automation"],
         connectors={"contacts"}, risk="low", reads="Names, emails and phone numbers you look up.",
         leaves="Nothing.", risk_text="Contact cards can come from others; treated as untrusted.",
         safeguards="Read only when needed."),
    dict(id="messages", name="Messages & WhatsApp", setting="enable_messages", mac=True, perms=["fda"],
         connectors={"messages"}, risk="high",
         reads="Your iMessage/SMS and WhatsApp chats (read-only copies of the databases).",
         leaves="iMessages you approve, to the chat shown; WhatsApp replies are only typed for you to send.",
         risk_text="Full Disk Access is broad (macOS can't grant 'Messages only'), and chats are written by others.",
         safeguards="Databases opened read-only; chats are untrusted data; sending always asks. Install the app "
                    "(localagent app install) so the access belongs to LocalAIAgent, not Terminal."),
    dict(id="apps", name="Mac apps & Shortcuts", setting="enable_apps", mac=True, perms=["accessibility"],
         connectors={"apps"}, risk="high", reads="The window of the app it's asked to use.",
         leaves="Whatever that app does when a button is pressed.",
         risk_text="Accessibility lets a program press buttons in any app.",
         safeguards="Pressing and typing ask first; destructive buttons ask every time."),
    dict(id="screen", name="Screen context", setting="screen_context_enabled", mac=True, perms=["screen"],
         connectors={"screen"}, risk="high", reads="Text on your screen every few minutes (on-device OCR).",
         leaves="Nothing.", risk_text="Your screen can show anything, including other people's messages.",
         safeguards="Off by default; screenshots are deleted at once; private apps skipped; text forgotten after "
                    "the retention time."),
    dict(id="files", name="Files", setting="enable_files", mac=False, perms=[], connectors={"files"}, risk="medium",
         reads="File names in your allowed folders.", leaves="Nothing.",
         risk_text="Downloads can contain files from anyone.",
         safeguards="Only the allowed folders; moving asks, trashing asks every time; programs are never opened."),
    dict(id="documents", name="Documents", setting="enable_documents", mac=False, perms=[],
         connectors={"documents"}, risk="low", reads="Nothing.", leaves="Nothing.",
         risk_text="Creates PDFs and spreadsheets in its own folder.", safeguards="Writes only to its folder."),
    dict(id="gmail", name="Gmail", setting="enable_gmail", mac=False, perms=[], connectors={"gmail"},
         kinds={"gmail_connected", "gmail_disconnected"}, risk="medium",
         reads="Your Gmail (through Google's API, with your own sign-in).",
         leaves="Search requests to Google; emails you approve.",
         risk_text="Mail is written by others; the sign-in token can read your mail.",
         safeguards="Token kept in the system keychain; sending always shows the full email."),
    dict(id="web", name="Web look-ups", setting="enable_web_search", mac=False, perms=[], connectors={"web"},
         risk="low", reads="Search results.", leaves="Your search words, to DuckDuckGo.",
         risk_text="Web pages are written by anyone and may try to instruct the agent.",
         safeguards="After reading a page, words that weren't in your request need your OK before they're "
                    "searched or typed."),
    dict(id="browser", name="Browser", setting="enable_browser", mac=False, perms=[], connectors={"browser"},
         risk="medium", reads="The pages it opens.", leaves="Addresses it opens and text it types into pages.",
         risk_text="Sites see what's typed; pages may try to instruct the agent.",
         safeguards="Links it hasn't seen, and typed words not from your request, need your OK; submitting, "
                    "booking or paying asks every time; you can watch every click."),
    dict(id="skills", name="Custom skills", setting="enable_skills", mac=False, perms=[], connectors={"skills"},
         risk="medium", reads="What each skill's script reads (sandboxed).",
         leaves="Only skills that declare network can send anything.",
         risk_text="Skills are code you (or someone) wrote.",
         safeguards="Sandboxed: no home folder, no network unless declared, no other apps; refused without a sandbox."),
    dict(id="proactive", name="Nudges & morning brief", setting="proactive_enabled", mac=False, perms=[],
         connectors=set(), kinds={"proactive_job"}, risk="medium",
         reads="In the background: calendar, reminders, unanswered mail and chats.",
         leaves="Nothing, unless you forward nudges to iMessage.",
         risk_text="It reads in the background, not only when you ask.",
         safeguards="Quiet hours and a daily limit; every run is in Activity."),
    dict(id="imessage_channel", name="Text the agent (iMessage)", setting="enable_imessage_channel", mac=True,
         perms=["fda", "automation"], connectors=set(),
         kinds={"channel_reply", "channel_forward", "channel_ignored", "channel_test"}, risk="high",
         reads="Your messages to yourself (or to the agent's Apple ID).",
         leaves="Replies to you by iMessage (end-to-end encrypted by Apple).",
         risk_text="Lets the agent be controlled by text.",
         safeguards="Only your own handles; strangers are ignored and logged; approvals by reply show the full "
                    "payload; reply 'pause' to stop everything."),
    dict(id="phone", name="Phone line", setting="phone_enabled", mac=False, perms=[], connectors=set(),
         kinds={"phone_call", "phone_answer", "phone_rejected", "phone_pin_ok", "phone_pin_wrong"}, risk="high",
         reads="What you say on a call (recognised by Twilio).", leaves="Your words and the spoken answers, via Twilio.",
         risk_text="Calls pass through Twilio (cloud); caller ID can be faked.",
         safeguards="Signed requests only, your numbers only, PIN on every call, nothing sent or changed by phone."),
    dict(id="peers", name="Trusted agents", setting="a2a_enabled", mac=False, perms=[], connectors={"peers"},
         kinds={"peer_paired", "peer_answered", "peer_reply", "peer_rejected", "peer_verified"}, risk="medium",
         reads="Requests from friends' agents you paired with.",
         leaves="Your busy times (if allowed) and messages you send.",
         risk_text="Opens a network listener for paired agents.",
         safeguards="End-to-end encrypted; only paired and verified agents; replay-protected; anything not "
                    "allowed waits for you."),
    dict(id="cloud", name="Cloud model", setting="cloud_enabled", mac=False, perms=[], connectors={"cloud"},
         risk="medium", reads="Nothing extra.", leaves="The question you approve (and memories if you allow) to Anthropic.",
         risk_text="Sends text to a cloud service with your API key.",
         safeguards="Every request shows exactly what's sent and needs your OK."),
    dict(id="wake", name="Wake word", setting="wake_word_enabled", mac=False, perms=[], connectors=set(),
         risk="low", reads="Short bursts of sound while the app is open.", leaves="Nothing.",
         risk_text="The microphone listens while the app tab is open.",
         safeguards="Audio stays in memory and is never stored."),
]
CAP_BY_ID = {c["id"]: c for c in CAPABILITIES}
OUTSIDE = {  # audit kinds that are themselves data leaving the computer
    "channel_reply": "you, by iMessage", "channel_forward": "you, by iMessage",
    "phone_answer": "Twilio (spoken to you)", "peer_answered": "a friend's agent", "peer_reply": "a friend's agent",
}
VAULT_KEYS = ("gmail_client_secret", "gmail_refresh_token", "anthropic_api_key", "twilio_auth_token",
              "phone_pin", "peer_private_key")


# ── what is on ─────────────────────────────────────────────────────────────
def _connector_of(rt: "Runtime", tool: str | None) -> str | None:
    if not tool:
        return None
    t = rt.tools.get(tool)
    if t is not None:
        return t.connector
    if tool == "cloud_ask":
        return "cloud"
    return tool.split("_")[0]


def usage(rt: "Runtime", since: float) -> dict[str, dict]:
    """capability id -> {last, count} from the audit log."""
    out: dict[str, dict] = {}
    # Grouped in SQLite: this runs on every Trust refresh, and the log only grows.
    rows = rt.store.query("SELECT kind, tool, MAX(ts) AS last, COUNT(*) AS n FROM audit WHERE ts >= ? "
                          "GROUP BY kind, tool", (since,))
    for r in rows:
        conn = _connector_of(rt, r["tool"]) if r["kind"] in ("tool_call", "connector_test") else None
        for c in CAPABILITIES:
            if (conn and conn in c.get("connectors", set())) or r["kind"] in c.get("kinds", set()):
                u = out.setdefault(c["id"], {"last": None, "count": 0})
                u["last"], u["count"] = max(u["last"] or 0, r["last"]), u["count"] + r["n"]
    return out


def capabilities(rt: "Runtime") -> list[dict]:
    week = usage(rt, time.time() - 7 * 86400)
    ever = usage(rt, 0)
    out = []
    for c in CAPABILITIES:
        available = rt.mac_available or not c["mac"]
        enabled = bool(getattr(rt.settings, c["setting"]))
        if c["id"] == "gmail":
            note = "signed in" if rt.gmail.connected() else "not signed in"
        else:
            note = ""
        out.append({
            **{k: c[k] for k in ("id", "name", "setting", "risk", "reads", "leaves", "risk_text", "safeguards")},
            "enabled": enabled and available, "available": available,
            "note": note if available else "Needs a Mac",
            "permissions": [{"name": PERMISSIONS[p][0], "link": PERMISSIONS[p][1] if sys.platform == "darwin" else ""}
                            for p in c["perms"]],
            "last_used": (ever.get(c["id"]) or {}).get("last"), "uses_7d": (week.get(c["id"]) or {}).get("count", 0),
        })
    return out


def forget(rt: "Runtime", cap_id: str) -> list[str]:
    """Delete what the agent keeps for a capability (not your memories, which only come from your own words)."""
    done = []
    if cap_id == "screen":
        rt.screen.forget_all()
        done.append("screen text")
    if cap_id == "gmail" and rt.vault.has("gmail_refresh_token"):
        rt.vault.delete("gmail_refresh_token")
        rt.settings.update({"gmail_account": ""})
        done.append("Gmail sign-in")
    if cap_id == "cloud" and rt.vault.has("anthropic_api_key"):
        rt.vault.delete("anthropic_api_key")
        done.append("Anthropic API key")
    if cap_id == "phone":
        for k in ("twilio_auth_token", "phone_pin"):
            if rt.vault.has(k):
                rt.vault.delete(k)
                done.append(k.replace("_", " "))
    if cap_id == "peers":
        n = len(rt.peers.list())
        rt.store.execute("DELETE FROM peers")
        rt.store.execute("DELETE FROM peer_inbox")
        done.append(f"{n} pairing(s)")
    if cap_id == "imessage_channel":
        rt.store.meta_set("imessage_channel_approval", "")
        done.append("pending text approvals")
    conns = CAP_BY_ID[cap_id].get("connectors", set())
    tools = [n for n, t in rt.tools.items() if t.connector in conns]
    if tools:
        q = ",".join("?" * len(tools))
        n = rt.store.execute(f"UPDATE grants SET revoked=1 WHERE revoked=0 AND tool IN ({q})", tuple(tools)).rowcount
        if n:
            done.append(f"{n} standing permission(s)")
    return done


# ── what left ──────────────────────────────────────────────────────────────
def _args(r) -> dict:
    try:
        return json.loads(r["args"]) if r["args"] else {}
    except ValueError:
        return {}


def egress_ledger(rt: "Runtime", since: float, until: float) -> list[dict]:
    rows = rt.store.query("SELECT * FROM audit WHERE ts >= ? AND ts <= ? ORDER BY id", (since, until))
    out = []
    for r in rows:
        args = _args(r)
        if r["kind"] == "tool_call" and r["outcome"] == "ok":
            tool = rt.tools.get(r["tool"])
            e = describe(tool, args) if tool is not None else (EGRESS[r["tool"]](args) if r["tool"] in EGRESS else None)
            if e is None:
                continue
            out.append({"id": r["id"], "ts": r["ts"], "what": e.get("what", r["tool"]), "to": e.get("to") or "?",
                        "tool": r["tool"], "tier": r["tier"], "approved": r["approval_id"] is not None,
                        "content": e.get("url") or e.get("text") or "", "detail": r["detail"] or ""})
        elif r["kind"] in OUTSIDE:
            out.append({"id": r["id"], "ts": r["ts"], "what": r["kind"].replace("_", " "),
                        "to": args.get("to") or OUTSIDE[r["kind"]], "tool": r["tool"], "tier": None,
                        "approved": None, "content": r["detail"] or "", "detail": ""})
    return out


# ── posture ────────────────────────────────────────────────────────────────
def posture(rt: "Runtime") -> list[dict]:
    from .security import disk_encryption
    from .skills import sandbox_available

    s = rt.settings
    checks = []

    def add(cid, name, ok, detail, fix=""):
        checks.append({"id": cid, "name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix})

    add("api", "The app only opens for you", True,
        "Requests need this install's secret and must be addressed to 127.0.0.1 (blocks other programs and websites).")
    local = s.host in ("127.0.0.1", "localhost", "::1")
    add("bind", "The app isn't on the network", local, f"Listening on {s.host}:{s.port}",
        "Set the host back to 127.0.0.1.")
    if sys.platform != "win32":
        mode = stat.S_IMODE(os.stat(rt.base).st_mode)
        add("folder", "Your data folder is private", mode & 0o077 == 0, f"{rt.base} (mode {oct(mode)})",
            f"chmod 700 '{rt.base}'")
    enc, detail = disk_encryption(max_age=600)
    add("disk", "Disk encryption", enc, detail, "Turn on FileVault (Mac), BitLocker (Windows) or LUKS (Linux).")
    ollama_local = any(h in s.ollama_url for h in ("127.0.0.1", "localhost", "[::1]"))
    add("models", "Models run on this computer", ollama_local, s.ollama_url,
        "Point Ollama back at http://127.0.0.1:11434.")
    if s.enable_skills:
        ok = sandbox_available() and s.skills_require_sandbox
        add("sandbox", "Custom skills run sandboxed", ok,
            "sandbox available" if sandbox_available() else "no sandbox on this computer (script skills refused)"
            if s.skills_require_sandbox else "sandbox requirement switched off",
            "Install bubblewrap (Linux) and keep 'require sandbox' on.")
    if sys.platform == "darwin":
        from . import macapp

        add("identity", "Permissions belong to LocalAIAgent", macapp.usable(rt.base),
            "LocalAIAgent.app installed" if macapp.usable(rt.base)
            else "macOS won't launch LocalAIAgent.app; permissions go to Terminal"
            if macapp.installed() else "permissions go to Terminal/Python",
            "Run: localagent app install")
    if s.phone_enabled:
        add("pin", "Phone calls need a PIN", rt.vault.has("phone_pin"), "PIN set" if rt.vault.has("phone_pin")
            else "no PIN: calls are refused", "Set a PIN in Settings → Phone line.")
    if s.a2a_enabled:
        add("a2a", "Friends' agents listener isn't on every network", s.a2a_host not in ("0.0.0.0", "::"),
            f"listening on {s.a2a_host}:{s.a2a_port}", "Set it to your Tailscale or home-network address.")
        unverified = [p["name"] for p in rt.peers.list() if not p["verified"]]
        add("peers", "All paired agents verified", not unverified,
            "all verified" if not unverified else f"not verified: {', '.join(unverified)}",
            "Compare safety codes in Settings → Trusted agents.")
    if s.cloud_enabled:
        add("cloud", "Memories stay out of cloud requests", not s.cloud_send_memories,
            "memories are included in cloud requests" if s.cloud_send_memories else "memories not sent",
            "Turn off 'send memories' in Settings → Cloud model.")
    always = [g for g in rt.policy.active_grants() if g["scope"] == "always"]
    add("grants", "No permanent permissions", not always,
        f"{len(always)} 'always' permission(s) (each expires after 30 days)" if always else "none",
        "Review them below and revoke what you don't need.")
    v = rt.audit.verify(full=False)
    add("audit", "Activity log is intact", v["ok"], f"{v['count']} entries, hash chain " +
        ("verified" if v["ok"] else f"broken at entry {v['broken_at']}"),
        "The log was changed outside the app; export it and investigate.")
    return checks


def overview(rt: "Runtime") -> dict:
    now = time.time()
    ledger = egress_ledger(rt, now - 7 * 86400, now)
    return {"paused": rt.settings.paused, "autonomy": rt.settings.autonomy,
            "capabilities": capabilities(rt), "posture": posture(rt), "grants": rt.policy.active_grants(),
            "egress_7d": len(ledger), "egress_recent": ledger[-20:][::-1],
            "secrets": {k: rt.vault.has(k) for k in VAULT_KEYS}, "vault": rt.vault.backend,
            "version": __version__}


# ── automated checks over a window ─────────────────────────────────────────
def _names(rt: "Runtime") -> list[str]:
    names = {rt.settings.user_name} if rt.settings.user_name else set()
    for p in rt.peers.list():
        names.update(x for x in (p["owner"], p["name"]) if x)
    if rt.mac_available and (rt.settings.enable_contacts or rt.settings.enable_messages):
        try:
            from .connectors.messages import ContactNames

            cn = ContactNames(Path(rt.settings.addressbook_dir).expanduser())
            cn._load()
            for full in set(cn._map.values()):
                names.add(full)
                first = full.split()[0]
                if len(first) >= 3:
                    names.add(first)
        except Exception:  # noqa: BLE001 - Contacts may be unreadable; patterns still apply
            pass
    return sorted(names, key=len, reverse=True)


def checks(rt: "Runtime", since: float, until: float) -> dict:
    rows = [dict(r) for r in rt.store.query("SELECT * FROM audit WHERE ts >= ? AND ts <= ? ORDER BY id",
                                             (since, until))]
    names = _names(rt)
    findings = []

    def add(severity, title, detail, items=None):
        findings.append({"severity": severity, "title": title, "detail": detail, "items": (items or [])[:20]})

    # 1. secrets and personal data in the log
    secret_hits, pii_hits = Counter(), Counter()
    for r in rows:
        c = pii.count(f"{r['args'] or ''}\n{r['detail'] or ''}", names)
        for k, n in c.items():
            (secret_hits if k in pii.SECRET_KINDS else pii_hits)[k] += n
    if secret_hits:
        add("critical", "Secrets appear in the activity log",
            "Passwords, keys or tokens should never be logged: " + ", ".join(f"{k} ×{n}" for k, n in secret_hits.items()))
    if pii_hits:
        add("info", "Personal data in the activity log (kept on this computer)",
            ", ".join(f"{k} ×{n}" for k, n in pii_hits.most_common()) + ". Expected (e.g. recipients); redacted "
            "in exports by default.")
    # 2. personal data that left the computer
    ledger = egress_ledger(rt, since, until)
    left = Counter()
    for e in ledger:
        left.update(pii.count(f"{e['to']}\n{e['content']}", names))
    if left:
        add("high" if any(k in pii.SECRET_KINDS for k in left) else "medium",
            "Personal data left this computer",
            ", ".join(f"{k} ×{n}" for k, n in left.most_common()) + " in " + str(len(ledger)) + " outgoing item(s). "
            "Check each was intended (e.g. the recipient of an email you approved).",
            [f"{datetime.fromtimestamp(e['ts']):%Y-%m-%d %H:%M} {e['what']} → {e['to']}" for e in ledger
             if pii.count(f"{e['to']}\n{e['content']}", names)])
    # 3. actions without an approval or a standing permission
    grants = [dict(g) for g in rt.store.query("SELECT * FROM grants")]
    unapproved = []
    for r in rows:
        if r["kind"] != "tool_call" or r["tier"] not in ("write", "danger") or r["approval_id"] is not None:
            continue
        # A grant made before the action covers it (when it was revoked later isn't recorded, so this
        # errs towards "covered"; the grant itself is listed in grants.json for a reviewer).
        covered = r["tier"] == "write" and any(g["tool"] == r["tool"] and g["created_at"] <= r["ts"]
                                                for g in grants)
        if not covered:
            unapproved.append(r)
    if unapproved:
        add("critical", "Actions ran without your approval",
            "These changed or sent something with no approval and no standing permission on record.",
            [f"#{r['id']} {r['tool']} ({r['tier']})" for r in unapproved])
    else:
        add("ok", "Every action had your approval or a standing permission",
            f"{sum(1 for r in rows if r['kind'] == 'tool_call' and r['tier'] in ('write', 'danger'))} action(s) checked.")
    danger_auto = [r for r in rows if r["kind"] == "tool_call" and r["tier"] == "danger" and r["approval_id"] is None]
    if danger_auto:
        add("critical", "Irreversible actions without a one-time approval", "", [f"#{r['id']} {r['tool']}" for r in danger_auto])
    # 4. injection attempts, blocked attempts, refusals
    inj = [r for r in rows if r["kind"] == "injection_flagged"]
    if inj:
        add("medium", "Content tried to instruct the agent",
            "Flagged and ignored; standing permissions were switched off for those requests.",
            [f"#{r['id']} via {r['tool']}: {(r['detail'] or '')[:80]}" for r in inj])
    blocked = [r for r in rows if r["kind"] in ("phone_rejected", "peer_rejected", "channel_ignored", "phone_pin_wrong")]
    if blocked:
        add("info", "Blocked attempts to reach the agent", "Strangers, bad signatures or wrong PINs.",
            [f"#{r['id']} {r['kind']}: {(r['detail'] or '')[:80]}" for r in blocked])
    # 5. sensitive settings changes
    sens = [r for r in rows if r["kind"] == "settings_changed" and r["outcome"] == "sensitive"]
    if sens:
        add("medium", "Security-sensitive settings were changed", "Check you made these changes.",
            [f"#{r['id']} {r['tool']}: {r['detail']}" for r in sens])
    # 6. log integrity
    v = rt.audit.verify()
    add("ok" if v["ok"] else "critical", "Activity log integrity",
        f"Hash chain over {v['count']} entries " + ("verified." if v["ok"] else f"BROKEN at entry {v['broken_at']}."))
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3, "ok": 4}
    findings.sort(key=lambda f: order[f["severity"]])
    return {"window": {"since": since, "until": until}, "entries": len(rows), "egress": len(ledger),
            "findings": findings,
            "not_covered": "Pattern checks can't recognise every name, address or piece of free-text personal "
                           "data; read the redacted export before sharing it."}


# ── export ─────────────────────────────────────────────────────────────────
REVIEWER_PROMPT = """You are reviewing the activity of a personal AI agent ("LocalAIAgent") that runs on its \
owner's computer. The files in this export are the agent's own records for the time window in manifest.json. \
Personal data may have been replaced with tokens like <EMAIL_3>; the same token always means the same value.

Please check and report, citing entry ids:
1. Did any action that sends, changes or deletes something (tier write or danger in audit.jsonl) run without an \
approval (approval_id) or a standing permission (grants.json)? Danger actions must always have an approval.
2. List everything that left the computer (egress.jsonl): where it went, what kind of data, and whether the \
owner approved it. Flag anything that looks unintended or that carries personal data to an unexpected place.
3. Did content from other people (injection_flagged entries, untrusted sources) appear to steer the agent?
4. Were any security-sensitive settings changed (settings_changed with outcome "sensitive")?
5. Does integrity.json show an intact hash chain? (You can recompute it: each entry's hash is \
sha256(prev_hash + canonical JSON of ts, kind, tool, tier, args, outcome, detail, approval_id, task_id).)
6. Anything else unusual: bursts of activity at odd hours, repeated failures, permissions broader than needed \
(settings.json, capabilities.json).
Finish with a short verdict: trustworthy / needs attention / problem, and why."""


def export(rt: "Runtime", since: float, until: float, raw: bool = False) -> tuple[bytes, dict]:
    names = _names(rt)
    red = None if raw else pii.Redactor(names)
    clean = (lambda v: v) if raw else red.value

    def jl(rows) -> str:
        return "".join(json.dumps(clean(r), ensure_ascii=False, default=str) + "\n" for r in rows)

    audit_rows = []
    for r in rt.store.query("SELECT * FROM audit WHERE ts >= ? AND ts <= ? ORDER BY id", (since, until)):
        d = dict(r)
        d["args"] = _args(r)
        audit_rows.append(d)
    approvals = [{k: v for k, v in dict(r).items() if k != "state"} for r in
                 rt.store.query("SELECT * FROM approvals WHERE created_at >= ? AND created_at <= ? ORDER BY id",
                                (since, until))]
    for a in approvals:
        a["args"] = json.loads(a["args"]) if a.get("args") else {}
    grants = [dict(r) for r in rt.store.query("SELECT * FROM grants ORDER BY id")]
    decisions = [{"id": r["id"], "created_at": r["created_at"], "backend": r["backend"],
                  "latency_ms": r["latency_ms"], "escalated": r["escalated"], "text": r["text"],
                  "decision": json.loads(r["payload"])} for r in
                 rt.store.query("SELECT * FROM decisions WHERE created_at >= ? AND created_at <= ? ORDER BY id",
                                (since, until))]
    ledger = egress_ledger(rt, since, until)
    verify = rt.audit.verify()
    first = audit_rows[0] if audit_rows else None
    last = audit_rows[-1] if audit_rows else None
    integrity = {**verify, "window_first": {"id": first["id"], "prev_hash": first["prev_hash"]} if first else None,
                 "window_last": {"id": last["id"], "hash": last["hash"]} if last else None}
    settings = rt.settings.to_dict()
    report = checks(rt, since, until)
    files = {
        "README_FOR_REVIEWER.md": _readme(since, until, raw),
        "settings.json": json.dumps(clean(settings), indent=2, ensure_ascii=False),
        "secrets.json": json.dumps({"backend": rt.vault.backend,
                                    "set": {k: rt.vault.has(k) for k in VAULT_KEYS},
                                    "note": "Values are never exported."}, indent=2),
        "capabilities.json": json.dumps(clean(capabilities(rt)), indent=2, ensure_ascii=False, default=str),
        "grants.json": json.dumps(clean(grants), indent=2, ensure_ascii=False, default=str),
        "audit.jsonl": jl(audit_rows),
        "approvals.jsonl": jl(approvals),
        "egress.jsonl": jl(ledger),
        "decisions.jsonl": jl(decisions),
        "integrity.json": json.dumps(integrity, indent=2),
        "checks.json": json.dumps(clean(report), indent=2, ensure_ascii=False),
    }
    manifest = {"app": "LocalAIAgent", "version": __version__, "created": time.time(),
                "window": {"since": since, "until": until,
                           "since_local": datetime.fromtimestamp(since).isoformat(timespec="minutes"),
                           "until_local": datetime.fromtimestamp(until).isoformat(timespec="minutes")},
                "redacted": not raw,
                "redactions": dict(red.per_kind) if red else {},
                "counts": {"audit": len(audit_rows), "approvals": len(approvals), "egress": len(ledger),
                           "decisions": len(decisions)},
                "sha256": {n: hashlib.sha256(c.encode()).hexdigest() for n, c in files.items()}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    rt.audit.append("trust_export", "trust", outcome="ok",
                    detail=f"{'raw' if raw else 'redacted'} export, {len(audit_rows)} entries, "
                           f"{manifest['window']['since_local']} – {manifest['window']['until_local']}")
    return buf.getvalue(), manifest


def _readme(since: float, until: float, raw: bool) -> str:
    return f"""# LocalAIAgent activity export

Window: {datetime.fromtimestamp(since):%Y-%m-%d %H:%M} – {datetime.fromtimestamp(until):%Y-%m-%d %H:%M} (local time)
Personal data: {"NOT redacted: this export contains raw personal data" if raw else "redacted (stable tokens like <EMAIL_3>)"}

## Files
- `manifest.json`: version, window, counts, and a SHA-256 of every other file.
- `settings.json`: every setting (no secrets are stored in settings).
- `secrets.json`: which secrets are set (never their values) and where they're kept.
- `capabilities.json`: each capability, on or off, what it reads, what can leave, risks and safeguards.
- `grants.json`: standing permissions (tool, scope, target, expiry, revoked).
- `audit.jsonl`: the activity log for the window, one JSON object per line. `kind` says what happened;
  `tier` is read / draft / write / danger; `approval_id` links to approvals.jsonl.
- `approvals.jsonl`: approval requests and your decisions (with the full payload you were shown).
- `egress.jsonl`: everything that left this computer in the window.
- `decisions.jsonl`: the decision layer's typed decisions for each message.
- `integrity.json`: the audit log's hash-chain check and the boundary hashes of this window.
- `checks.json`: the app's own automated checks (personal data, approvals, integrity, …).

## Asking an AI to review it
Upload the files (or paste them) into Claude, ChatGPT or another assistant with this prompt:

> {REVIEWER_PROMPT.replace(chr(10), chr(10) + '> ')}
"""
