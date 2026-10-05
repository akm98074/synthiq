import json


def read_events(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def chat(client, text):
    resp = client.post("/api/chat", json={"text": text})
    assert resp.status_code == 200
    return read_events(resp)


def test_remember_recall_forget(client):
    events = chat(client, "I prefer window seats on flights")
    types = [e["type"] for e in events]
    assert types[0] == "decision"
    assert events[0]["decision"]["answers"]["intent"]["label"] == "memory_write"
    saved = [e for e in events if e["type"] == "memory_saved"]
    assert saved and "window seats" in saved[0]["memory"]["text"]
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    assert "hidden" not in reply  # <think> stripped
    assert types[-1] == "done"

    # the same fact again updates instead of duplicating
    chat(client, "I prefer window seats on flights")
    mems = client.get("/api/memories").json()
    assert len(mems) == 1

    events = chat(client, "what do you know about me?")
    assert events[0]["decision"]["answers"]["intent"]["label"] == "memory_query"
    assert any(e["type"] == "recalled" for e in events)
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    assert "window seats" in reply

    assert "window seats" in client.get("/api/identity").text
    assert client.delete(f"/api/memories/{mems[0]['id']}").json() == {"ok": True}
    assert client.get("/api/memories").json() == []
    assert "window seats" not in client.get("/api/identity").text

    msgs = client.get("/api/messages").json()
    assert len(msgs) == 6 and msgs[0]["decision_id"]


def test_decisions_log_and_correct(client):
    chat(client, "hello!")
    decisions = client.get("/api/decisions").json()
    assert decisions and decisions[0]["text"] == "hello!"
    r = client.post(f"/api/decisions/{decisions[0]['id']}/correct",
                    json={"question": "intent", "label": "chit_chat"})
    assert r.status_code == 200 and r.json()["user_examples"] == 1
    assert client.post("/api/decisions/9999/correct", json={"question": "intent", "label": "task"}).status_code == 404
    assert client.post(f"/api/decisions/{decisions[0]['id']}/correct",
                       json={"question": "intent", "label": "bogus"}).status_code == 400


def test_manual_memory_and_settings(client):
    m = client.post("/api/memories", json={"text": "Dog is named Max", "kind": "person"}).json()
    assert m["kind"] == "person"
    m2 = client.patch(f"/api/memories/{m['id']}", json={"text": "Dog is named Rex"}).json()
    assert m2["text"] == "Dog is named Rex"
    s = client.put("/api/settings", json={"agent_name": "Juno", "confidence_threshold": 0.7}).json()
    assert s["agent_name"] == "Juno" and s["confidence_threshold"] == 0.7
    assert client.put("/api/settings", json={"decision_backend": "nope"}).status_code == 400


def test_models_doctor_ui(client):
    st = client.get("/api/models").json()
    assert st["error"] is None and all(m["installed"] for m in st["configured"])
    checks = {c["name"]: c["status"] for c in client.get("/api/doctor").json()}
    assert checks["ollama"] == "ok" and checks["chat model"] == "ok"
    page = client.get("/")
    assert "LocalAIAgent" in page.text and "/ui/app.js?v=" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/ui/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/ui/app.js").status_code == 200
    assert client.post("/api/models/unload", json={"model": "qwen3:4b"}).json() == {"ok": True}


def test_ollama_down_is_reported(home):
    from fastapi.testclient import TestClient

    from localagent.config import Settings
    from localagent.server import create_app

    s = Settings(ollama_url="http://127.0.0.1:9")
    with TestClient(create_app(s, home)) as c:
        events = read_events(c.post("/api/chat", json={"text": "hi"}))
        assert events[0]["type"] == "error" and "Cannot reach Ollama" in events[0]["message"]
        assert c.get("/api/models").json()["error"]
        checks = {x["name"]: x["status"] for x in c.get("/api/doctor").json()}
        assert checks["ollama"] == "fail"
