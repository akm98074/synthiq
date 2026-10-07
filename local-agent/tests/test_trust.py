"""Trust & Transparency center: what's on, what left, automated checks, pause/presets, export."""
import hashlib
import io
import json
import time
import zipfile

import pytest

from localagent.agent.actions import ActionRun
from localagent.safety import pii
from test_redteam import Scripted, tools


def rt_of(c):
    return c.app.state.rt


def seed_activity(rt):
    """An approved email with personal data, a log line with a leaked key, and an unapproved write."""
    t = rt.tools.get("mail_send")
    ap = rt.policy.request(t, {"to": "sam@example.com", "subject": "Hi", "body": "Call me on 425-555-0100"}, 1, {})
    rt.policy.decide(ap["id"], True, "once")
    rt.audit.append("tool_call", "mail_send", "write",
                    {"to": "sam@example.com", "subject": "Hi", "body": "Call me on 425-555-0100"}, "ok",
                    "Sent to sam@example.com", ap["id"], 1)
    rt.audit.append("tool_call", "web_search", "read", {"query": "onion price safeway"}, "ok", "Found 3", None, 2)
    rt.audit.append("tool_call", "calendar_create_event", "write", {"title": "x"}, "ok", "Created", None, 3)
    rt.audit.append("connector_test", "gmail", "read", {}, "error", "token sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA")


def test_overview_lists_capabilities_risks_and_posture(action_client):
    c = action_client
    o = c.get("/api/trust").json()
    caps = {x["id"]: x for x in o["capabilities"]}
    assert {"calendar", "messages", "screen", "cloud", "phone", "peers", "browser"} <= set(caps)
    assert caps["messages"]["risk"] == "high" and caps["messages"]["permissions"][0]["name"] == "Full Disk Access"
    assert caps["screen"]["enabled"] is False
    for k in ("reads", "leaves", "risk_text", "safeguards"):
        assert caps["mail"][k]
    posture = {p["id"]: p for p in o["posture"]}
    assert posture["api"]["ok"] and posture["audit"]["ok"] and posture["models"]["ok"]
    assert o["paused"] is False and o["autonomy"] == "agent" and o["secrets"]["anthropic_api_key"] is False


def test_egress_ledger_and_automated_checks(action_client):
    c = action_client
    seed_activity(rt_of(c))
    ledger = c.get("/api/trust/egress").json()
    whats = {(e["tool"], e["to"]) for e in ledger}
    assert ("mail_send", "sam@example.com") in whats and ("web_search", "DuckDuckGo") in whats
    assert not any(e["tool"] == "calendar_create_event" for e in ledger)     # nothing leaves for that
    rep = c.get("/api/trust/checks").json()
    by = {f["title"]: f for f in rep["findings"]}
    assert by["Secrets appear in the activity log"]["severity"] == "critical"
    assert by["Actions ran without your approval"]["severity"] == "critical"
    assert any("calendar_create_event" in i for i in by["Actions ran without your approval"]["items"])
    left = by["Personal data left this computer"]
    assert "EMAIL" in left["detail"] and "PHONE" in left["detail"]
    assert by["Activity log integrity"]["severity"] == "ok"
    assert rep["findings"][0]["severity"] == "critical"                      # worst first


def test_export_is_redacted_hashed_and_self_describing(action_client):
    c = action_client
    seed_activity(rt_of(c))
    r = c.get("/api/trust/export", params={"since": "2000-01-01"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README_FOR_REVIEWER.md", "manifest.json", "settings.json", "secrets.json", "audit.jsonl",
            "approvals.jsonl", "egress.jsonl", "grants.json", "integrity.json", "checks.json"} <= names
    manifest = json.loads(z.read("manifest.json"))
    for name, digest in manifest["sha256"].items():                          # every file verifiable
        assert hashlib.sha256(z.read(name)).hexdigest() == digest
    assert manifest["redacted"] and manifest["redactions"]["EMAIL"] >= 1
    blob = "".join(z.read(n).decode() for n in names)
    assert "sam@example.com" not in blob and "425-555-0100" not in blob and "sk-ant-api03" not in blob
    audit = [json.loads(line) for line in z.read("audit.jsonl").decode().splitlines()]
    sends = [a for a in audit if a["tool"] == "mail_send"]
    assert sends[0]["args"]["to"] == "<EMAIL_1>"                             # stable tokens keep flows traceable
    assert "Claude" in z.read("README_FOR_REVIEWER.md").decode()
    assert json.loads(z.read("integrity.json"))["ok"] is True
    assert "approval_id" in audit[0] and "state" not in z.read("approvals.jsonl").decode()
    # raw needs an explicit confirmation, and is marked
    assert c.get("/api/trust/export", params={"raw": "true"}).status_code == 400
    raw = c.get("/api/trust/export", params={"raw": "true", "confirm_raw": "yes", "since": "2000-01-01"})
    zr = zipfile.ZipFile(io.BytesIO(raw.content))
    assert "sam@example.com" in zr.read("audit.jsonl").decode() and "RAW" in raw.headers["content-disposition"]
    kinds = [a["kind"] for a in c.get("/api/audit").json()]
    assert kinds.count("trust_export") == 2                                  # exports are themselves logged


def test_capability_toggle_confirm_and_forget(action_client):
    c = action_client
    r = c.post("/api/trust/capability/screen", json={"enabled": True})
    assert r.status_code == 428                                              # sensitive: asks with the risk
    r = c.post("/api/trust/capability/screen", json={"enabled": True}, headers={"X-Confirm": "screen_context_enabled"})
    assert {x["id"]: x for x in r.json()["capabilities"]}["screen"]["enabled"]
    rt = rt_of(c)
    rt.vault.set("anthropic_api_key", "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx")
    r = c.post("/api/trust/capability/cloud", json={"enabled": False, "forget": True}).json()
    assert "Anthropic API key" in r["forgotten"] and not rt.vault.has("anthropic_api_key")
    assert c.post("/api/trust/capability/nope", json={"enabled": True}).status_code == 404


async def run_tool(rt, name, args="{}"):
    ran = []
    rt.ollama = Scripted([[(name, args)]])
    run = ActionRun(rt, 1, tools(ran), [{"role": "user", "content": "go"}], "m")
    events = [ev async for ev in run.start()]
    return ran, events


async def test_pause_and_presets_limit_what_runs(runtime):
    runtime.settings.paused = True
    ran, events = await run_tool(runtime, "browser_type", json.dumps({"ref": 1, "text": "go"}))
    assert not ran and any("paused" in (e.get("display") or "") for e in events)
    ran, _ = await run_tool(runtime, "mail_read")
    assert ran                                                               # looking still works
    runtime.settings.paused = False
    runtime.settings.autonomy = "assistant"
    ran, events = await run_tool(runtime, "gmail_send", json.dumps({"to": "a@b.c", "subject": "s", "body": "b"}))
    assert not ran and not any(e["type"] == "approval_required" for e in events)   # refused, not even asked
    ran, _ = await run_tool(runtime, "browser_type", json.dumps({"ref": 1, "text": "go"}))
    assert ran                                                               # drafts allowed
    runtime.settings.autonomy = "observer"
    ran, _ = await run_tool(runtime, "browser_type", json.dumps({"ref": 1, "text": "go"}))
    assert not ran
    assert [a["kind"] for a in runtime.audit.list()].count("tool_refused") == 3


def test_pause_endpoint_stops_scheduler(action_client):
    c = action_client
    o = c.post("/api/trust/pause", json={"paused": True}).json()
    assert o["paused"] and not rt_of(c).scheduler.enabled
    o = c.post("/api/trust/pause", json={"paused": False}).json()
    assert not o["paused"] and rt_of(c).scheduler.enabled
    assert c.put("/api/trust/autonomy", json={"autonomy": "boss"}).status_code == 400


@pytest.mark.parametrize("text,kinds", [
    ("mail sam@example.com or +1 425 555 0100", {"EMAIL", "PHONE"}),
    ("card 4111 1111 1111 1111, not 1234 5678 9012 3456", {"CARD"}),
    ("ssn 123-45-6789", {"SSN"}),
    ("key AKIAABCDEFGHIJKLMNOP and password: hunter2", {"API_KEY", "PASSWORD"}),
    ("timestamp 1728201234 and id 42", set()),
    ("server 8.8.8.8, local 127.0.0.1", {"IP"}),
])
def test_pii_patterns(text, kinds):
    assert set(pii.count(text)) == kinds


def test_redactor_is_stable_and_handles_names():
    r = pii.Redactor(names=["Priya Raman", "Priya"])
    out = r.value({"to": "priya@acme.com", "body": "Hi Priya Raman, cc priya@acme.com"})
    assert out == {"to": "<EMAIL_1>", "body": "Hi <NAME_1>, cc <EMAIL_1>"}


def test_name_redaction_is_fast_with_a_big_address_book():
    """One regex per contact name took minutes with a real address book (Run Checks "did nothing")."""
    import random
    import string

    rnd = random.Random(1)
    names = [("".join(rnd.choices(string.ascii_lowercase, k=6)).title() + " "
              + "".join(rnd.choices(string.ascii_lowercase, k=7)).title()) for _ in range(3000)]
    names += [n.split()[0] for n in names] + ["Priya Raman", "Priya", "Will"]
    text = 'Hi Priya Raman and Priya, will you call 425-555-0100? {"to": "sam@example.com"}'
    started = time.perf_counter()
    for _ in range(2000):
        found = pii.count(text, names)
    assert time.perf_counter() - started < 5
    assert found["NAME"] == 2 and found["EMAIL"] == 1 and found["PHONE"] == 1   # "will" is a word, not Will


def test_checks_endpoint_reports_its_time(action_client):
    c = action_client
    seed_activity(rt_of(c))
    r = c.get("/api/trust/checks")
    assert r.status_code == 200 and "seconds" in r.json() and r.json()["findings"]


def test_trust_status_stays_fast_with_a_long_log(action_client, monkeypatch):
    """The header refreshes /api/trust every minute. It used to re-hash the whole log, scan it in
    Python and start the disk-encryption probe each time, all on the event loop."""
    import time as _t

    from localagent import security

    c = action_client
    rt = rt_of(c)
    rt.store.execute("PRAGMA synchronous=OFF")                   # just to seed the log quickly
    for i in range(20000):
        rt.audit.append("tool_call", "calendar_today" if i % 2 else "web_search", tier="read",
                        args={"q": f"x{i}"}, outcome="ok")
    probes = []
    monkeypatch.setattr(security, "_disk_encryption", lambda: probes.append(1) or (True, "on"))
    monkeypatch.setattr(security, "_DISK", None)
    c.get("/api/trust")                                         # first call verifies the whole chain
    t = _t.perf_counter()
    for _ in range(3):
        o = c.get("/api/trust").json()
    took = (_t.perf_counter() - t) / 3
    assert took < 0.5, f"/api/trust took {took:.2f}s"
    assert len(probes) == 1                                      # the probe is reused for 10 minutes
    audit = next(p for p in o["posture"] if p["id"] == "audit")
    assert audit["ok"] and str(rt.store.query("SELECT COUNT(*) AS n FROM audit")[0]["n"]) in audit["detail"]
    cal = next(x for x in o["capabilities"] if x["id"] == "calendar")
    assert cal["last_used"]

    # Tampering is still caught by the quick check, not only by the full one.
    assert rt.audit._verified                                    # the status call left a checkpoint
    row = dict(rt.store.query("SELECT * FROM audit WHERE id = 7")[0])
    rt.store.execute("DELETE FROM audit WHERE id = 7")
    assert not rt.audit.verify(full=False)["ok"]                 # a deleted row changes the count
    rt.store.execute(f"INSERT INTO audit({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    assert rt.audit.verify()["ok"] and rt.audit._verified
    last = rt.audit._verified[0]
    rt.store.execute("UPDATE audit SET hash='x' WHERE id = ?", (last,))
    assert not rt.audit.verify(full=False)["ok"]                 # rewriting the chain's end is seen
    rt.store.execute("UPDATE audit SET detail='edited' WHERE id = 5")
    assert not rt.audit.verify()["ok"]                           # checks and exports verify everything
