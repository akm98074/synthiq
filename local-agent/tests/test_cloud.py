import pytest

from fake_anthropic import FakeAnthropic
from test_actions import chat, decide


@pytest.fixture
def cloud_client(fake_ollama, home, files_home, fake_runner):
    from fastapi.testclient import TestClient

    from localagent.config import Settings, save_settings
    from localagent.server import create_app

    with FakeAnthropic() as api:
        s = Settings(ollama_url=fake_ollama.url, confidence_threshold=1.0, enable_messages=False,
                     enable_web_search=False, file_roots=str(files_home / "Downloads"))
        save_settings(s, home)
        with TestClient(create_app(s, home, runner=fake_runner, scheduler=False, cloud_base_url=api.url)) as c:
            c.api = api
            yield c


def tokens(ev):
    return "".join(e["text"] for e in ev if e["type"] == "token")


def test_off_by_default_and_key_validation(cloud_client):
    c = cloud_client
    ev = chat(c, "think harder: is 1013 prime?")
    assert not c.api.state["requests"]                         # nothing sent: cloud is off
    assert "Fake reply" in tokens(ev)
    assert c.put("/api/cloud/key", json={"key": "hunter2"}).status_code == 400
    st = c.put("/api/cloud/key", json={"key": "sk-ant-test"}).json()
    assert st["has_key"] and st["installed"]
    assert "sk-ant-test" not in (c.app.state.rt.base / "config.json").read_text()


def test_approval_then_streamed_answer(cloud_client):
    c = cloud_client
    c.put("/api/cloud/key", json={"key": "sk-ant-test"})
    c.post("/api/memories", json={"text": "The user believes the meaning of life is family", "kind": "fact"})
    c.put("/api/settings", json={"cloud_enabled": True}, headers={"X-Confirm": "cloud_enabled"})
    ev = chat(c, "think harder: what is the meaning of life?")
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]
    assert ap["tool"] == "cloud_ask" and "claude-opus-5-5" in ap["summary"] and "meaning of life" in ap["summary"]
    assert not c.api.state["requests"]                          # nothing leaves before approval
    r, ev = decide(c, ap["id"], scope="hour")
    assert tokens(ev) == "The answer is 42."
    done = next(e for e in ev if e["type"] == "done")
    assert done["model"] == "claude-opus-5-5 (cloud)" and done["message_id"]
    req = c.api.state["requests"][0]
    body = req["body"]
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["headers"]["anthropic-beta"]
    assert body["output_config"] == {"effort": "high"} and "thinking" not in body
    assert body["messages"][-1] == {"role": "user", "content": "what is the meaning of life?"}
    assert "meaning of life is family" in str(body["system"])     # the recalled memory went along (setting on)
    # the 1-hour grant means the next one goes straight through
    ev = chat(c, "ask claude what 6 times 7 is")
    assert "approval_required" not in [e["type"] for e in ev] and tokens(ev) == "The answer is 42."
    audit = c.get("/api/audit").json()
    assert any(a["kind"] == "tool_call" and a["tool"] == "cloud_ask" and a["outcome"] == "ok" for a in audit)


def test_decline_errors_and_refusal(cloud_client):
    c = cloud_client
    c.put("/api/cloud/key", json={"key": "sk-ant-test"})
    c.put("/api/settings", json={"cloud_enabled": True, "cloud_send_memories": False},
          headers={"X-Confirm": "cloud_enabled"})
    ev = chat(c, "use the cloud: plan my week")
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]
    r, ev = decide(c, ap["id"], approve=False)
    assert "nothing was sent" in tokens(ev) and not c.api.state["requests"]
    c.app.state.rt.vault.set("anthropic_api_key", "sk-ant-wrong")
    ev = chat(c, "think harder about x")
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]
    r, ev = decide(c, ap["id"])
    assert any(e["type"] == "error" and "rejected the API key" in e["message"] for e in ev)
    c.app.state.rt.vault.set("anthropic_api_key", "sk-ant-test")
    c.api.state["stop"] = "refusal"
    c.api.state["reply"] = []
    ev = chat(c, "think harder about y")
    ap = next(e for e in ev if e["type"] == "approval_required")["approval"]
    r, ev = decide(c, ap["id"])
    assert any(e["type"] == "error" and "declined" in e["message"] for e in ev)
