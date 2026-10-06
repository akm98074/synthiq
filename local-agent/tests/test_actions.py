import json

from test_chat_flow import read_events


def chat(client, text):
    r = client.post("/api/chat", json={"text": text})
    assert r.status_code == 200, r.text
    return read_events(r)


def decide(client, approval_id, approve=True, scope="once"):
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"approve": approve, "scope": scope})
    return r, (read_events(r) if r.status_code == 200 else [])


def types(events):
    return [e["type"] for e in events]


def test_read_tool_runs_automatically(action_client):
    ev = chat(action_client, "what's on my calendar tomorrow?")
    assert ev[0]["decision"]["answers"]["intent"]["label"] == "schedule"
    res = [e for e in ev if e["type"] == "tool_result"]
    assert res and res[0]["tool"] == "calendar_list_events" and res[0]["ok"]
    assert res[0]["data"][0]["title"] == "Dentist"
    assert "approval_required" not in types(ev)
    assert "".join(e["text"] for e in ev if e["type"] == "token").startswith("Done:")
    name, args = action_client.runner.calls[-1]
    assert name == "calendar_list" and int(args[1]) > int(args[0])
    audit = action_client.get("/api/audit").json()
    assert audit[0]["kind"] == "tool_call" and audit[0]["tool"] == "calendar_list_events"


def test_write_tool_needs_approval_then_resumes(action_client):
    ev = chat(action_client, "remind me to call mom tomorrow at 6pm")
    ap = [e for e in ev if e["type"] == "approval_required"]
    assert ap, types(ev)
    ap = ap[0]["approval"]
    assert ap["tool"] == "reminders_create" and ap["status"] == "pending"
    assert {s["id"] for s in ap["allowed_scopes"]} >= {"once", "session", "always"}
    assert ev[-1]["type"] == "done" and ev[-1]["paused"]
    assert not any(c[0] == "reminders_create" for c in action_client.runner.calls)
    assert action_client.get("/api/approvals?status=pending").json()[0]["id"] == ap["id"]

    r, ev2 = decide(action_client, ap["id"], True, "session")
    assert r.status_code == 200
    assert types(ev2)[0] == "approval_decided"
    res = [e for e in ev2 if e["type"] == "tool_result"][0]
    assert res["ok"] and "call mom" in res["display"]
    assert any(c[0] == "reminders_create" for c in action_client.runner.calls)
    assert ev2[-1]["type"] == "done" and not ev2[-1]["paused"]

    # deciding twice is rejected
    r, _ = decide(action_client, ap["id"], True)
    assert r.status_code == 409

    # the session grant lets the next reminder run without asking
    grants = action_client.get("/api/grants").json()
    assert grants[0]["tool"] == "reminders_create" and grants[0]["scope"] == "session"
    ev3 = chat(action_client, "remind me to water plants")
    assert "approval_required" not in types(ev3)
    assert any(e["type"] == "tool_result" and e["tool"] == "reminders_create" for e in ev3)

    # revoke -> asks again
    assert action_client.delete(f"/api/grants/{grants[0]['id']}").json() == {"ok": True}
    ev4 = chat(action_client, "remind me to stretch")
    assert "approval_required" in types(ev4)


def test_deny_does_not_run(action_client):
    ev = chat(action_client, "send Sam an email saying hi")
    ap = [e for e in ev if e["type"] == "approval_required"][0]["approval"]
    assert ap["tool"] == "mail_send"
    _, ev2 = decide(action_client, ap["id"], approve=False)
    assert not any(c[0] == "mail_compose" for c in action_client.runner.calls)
    res = [e for e in ev2 if e["type"] == "tool_result"][0]
    assert not res["ok"] and res["display"] == "Declined by you"
    kinds = [a["kind"] for a in action_client.get("/api/audit").json()]
    assert "approval_denied" in kinds and "approval_requested" in kinds


def test_danger_tier_only_allows_once(action_client):
    ev = chat(action_client, "trash old.dmg from my downloads")
    ap = [e for e in ev if e["type"] == "approval_required"][0]["approval"]
    assert ap["tool"] == "files_trash" and ap["tier"] == "danger"
    assert [s["id"] for s in ap["allowed_scopes"]] == ["once"]
    r, _ = decide(action_client, ap["id"], True, "always")
    assert r.status_code == 409
    r, ev2 = decide(action_client, ap["id"], True, "once")
    assert r.status_code == 200
    assert not (action_client.files_home / "Downloads" / "old.dmg").exists()
    assert list((action_client.files_home / ".local/share/Trash/files").iterdir())


def test_draft_tier_runs_and_creates_files(action_client):
    ev = chat(action_client, "make a pdf packing list for my trip")
    res = [e for e in ev if e["type"] == "tool_result"]
    assert res and res[0]["tool"] == "documents_create_pdf" and res[0]["ok"], res
    out = action_client.files_home / "Documents" / "LocalAIAgent" / "Packing list.pdf"
    assert out.exists() and out.read_bytes()[:4] == b"%PDF"
    ev = chat(action_client, "make a spreadsheet of my budget")
    res = [e for e in ev if e["type"] == "tool_result"][0]
    assert res["ok"] and res["data"]["rows"] == 2


def test_audit_chain_verifies_and_detects_tampering(action_client):
    chat(action_client, "what's on my calendar tomorrow?")
    chat(action_client, "remind me to call mom")
    v = action_client.get("/api/audit/verify").json()
    assert v["ok"] and v["count"] == 2  # tool_call + approval_requested
    rt = action_client.app.state.rt
    rt.store.execute("UPDATE audit SET outcome='forged' WHERE id=1")
    v = action_client.get("/api/audit/verify").json()
    assert not v["ok"] and v["broken_at"] == 1


def test_connectors_endpoint_and_test_button(action_client):
    cons = {c["id"]: c for c in action_client.get("/api/connectors").json()}
    assert cons["calendar"]["active"] and cons["files"]["active"]
    assert {t["name"] for t in cons["mail"]["tools"]} == {"mail_list", "mail_followups", "mail_read", "mail_draft", "mail_send"}
    r = action_client.post("/api/connectors/calendar/test").json()
    assert r["ok"] and "event" in r["message"]
    action_client.put("/api/settings", json={"enable_mail": False})
    cons = {c["id"]: c for c in action_client.get("/api/connectors").json()}
    assert not cons["mail"]["enabled"] and cons["mail"]["tools"] == []
    assert action_client.post("/api/connectors/mail/test").status_code == 400


def test_plain_writing_task_streams_without_tools(action_client, fake_ollama):
    before = len([c for c in fake_ollama.app.state.calls if c[0] == "tools"])
    ev = chat(action_client, "write a haiku about autumn")
    assert ev[0]["decision"]["answers"]["intent"]["label"] == "task"
    after = len([c for c in fake_ollama.app.state.calls if c[0] == "tools"])
    assert after == before
    assert "".join(e["text"] for e in ev if e["type"] == "token").startswith("Fake reply")


def test_mac_connectors_hidden_without_macos(client):
    cons = {c["id"]: c for c in client.get("/api/connectors").json()}
    import sys
    if sys.platform != "darwin":
        assert not cons["calendar"]["available"] and cons["calendar"]["note"] == "Needs macOS"
    assert cons["files"]["available"]


def test_wants_tools_gate():
    from localagent.agent.chat import wants_tools
    assert wants_tools("schedule", "am I free friday")
    assert wants_tools("computer_action", "lock my screen")
    assert wants_tools("quick_answer", "any unread email?")
    assert wants_tools("task", "save this as a pdf")
    assert not wants_tools("task", "write a haiku about autumn")
    assert not wants_tools("quick_answer", "why is the sky blue?")
    assert not wants_tools("memory_query", "what's my email address?")
