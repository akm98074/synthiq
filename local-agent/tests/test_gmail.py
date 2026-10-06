import asyncio
import json
import os
from urllib.parse import parse_qs, urlparse

import pytest

from fake_google import FakeGoogle, parse_raw
from localagent.tools.base import ToolError

CLIENT = "1234-abc.apps.googleusercontent.com"


@pytest.fixture
def google():
    with FakeGoogle() as g:
        yield g


@pytest.fixture
def gmail_client(fake_ollama, home, files_home, fake_runner, google):
    from fastapi.testclient import TestClient

    from localagent.config import Settings, save_settings
    from localagent.server import create_app

    s = Settings(ollama_url=fake_ollama.url, confidence_threshold=1.0, enable_messages=False,
                 quiet_start="00:00", quiet_end="00:00", file_roots=str(files_home / "Downloads"))
    save_settings(s, home)
    with TestClient(create_app(s, home, runner=fake_runner, scheduler=False, google=google.endpoints())) as c:
        c.google, c.home = google, home
        yield c


def connect(c):
    assert c.put("/api/gmail/client", json={"client_id": "nope"}).status_code == 400
    st = c.put("/api/gmail/client", json={"client_id": CLIENT, "client_secret": "shh"}).json()
    assert st["has_secret"] and not st["connected"]
    r = c.get("/api/gmail/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == [CLIENT] and q["code_challenge_method"] == ["S256"] and "gmail.compose" in q["scope"][0]
    assert q["redirect_uri"][0].endswith("/api/gmail/callback") and q["access_type"] == ["offline"]
    c.google.state["codes"]["c1"] = q["code_challenge"][0]
    return q["state"][0]


def test_sign_in_flow_and_secret_storage(gmail_client):
    c = gmail_client
    state = connect(c)
    assert c.get("/api/gmail/callback", params={"code": "c1", "state": "forged"}).status_code == 400
    state = connect(c)
    r = c.get("/api/gmail/callback", params={"code": "c1", "state": state})
    assert r.status_code == 200 and "Connected as me@gmail.com" in r.text
    st = c.get("/api/gmail").json()
    assert st["connected"] and st["account"] == "me@gmail.com"
    secrets = c.home / "secrets.json"
    assert oct(os.stat(secrets).st_mode & 0o777) == "0o600"
    assert json.loads(secrets.read_text())["gmail_refresh_token"] == "rt-1"
    assert "shh" not in (c.home / "config.json").read_text() and "rt-1" not in (c.home / "config.json").read_text()
    conns = {x["id"]: x for x in c.get("/api/connectors").json()}
    assert {t["name"]: t["tier"] for t in conns["gmail"]["tools"]} == {
        "gmail_search": "read", "gmail_read": "read", "gmail_followups": "read", "gmail_draft": "draft",
        "gmail_send": "write"}
    assert c.post("/api/gmail/disconnect").json()["connected"] is False
    assert "gmail_search" not in [t["name"] for t in c.get("/api/tools").json()]


def run(coro):
    return asyncio.run(coro)


def test_gmail_tools(gmail_client):
    c = gmail_client
    c.get("/api/gmail/callback", params={"code": "c1", "state": connect(c)})
    tools = c.app.state.rt.tools
    res = run(tools["gmail_search"].run({"query": "is:unread"}))
    assert res.untrusted and "[id m2]" in res.content and "(unread)" in res.content
    assert c.google.state["queries"][-1] == "is:unread"
    body = run(tools["gmail_read"].run({"id": "m2"})).content
    assert "Top stories & more" in body and "x()" not in body
    fu = run(tools["gmail_followups"].run({}))
    assert [m["id"] for m in fu.data] == ["m1", "m2"]                     # t3: you replied last
    run(tools["gmail_draft"].run({"to": "priya@acme.com", "subject": "Re: deck", "body": "Will do",
                                  "reply_to": "m1"}))
    d = c.google.state["drafts"][0]
    mime = parse_raw(d["raw"])
    assert d["threadId"] == "t1" and mime["To"] == "priya@acme.com" and mime["In-Reply-To"] == "<m1@mail.gmail.com>"
    assert mime.get_payload().strip() == "Will do"
    with pytest.raises(ToolError, match="email address"):
        run(tools["gmail_send"].run({"to": "Priya", "subject": "x", "body": "y"}))
    # an expired access token is refreshed once, transparently
    before = int(c.google.state["access"][3:])
    c.google.state["fail_next"] = 1
    run(tools["gmail_send"].run({"to": "sam@example.com", "subject": "Hi", "body": "Hello"}))
    assert c.google.state["access"] == f"at-{before + 1}" and parse_raw(c.google.state["sent"][0]["raw"])["To"] == "sam@example.com"
    # a revoked sign-in is reported and forgotten
    c.google.state["revoked"] = True
    c.google.state["fail_next"] = 1
    with pytest.raises(ToolError, match="revoked"):
        run(tools["gmail_search"].run({}))
    assert c.get("/api/gmail").json()["connected"] is False


def test_send_needs_approval_and_nudges_dedupe(gmail_client):
    from test_actions import chat

    c = gmail_client
    c.get("/api/gmail/callback", params={"code": "c1", "state": connect(c)})
    ev = chat(c, "send an email to sam saying hi")
    ap = [e for e in ev if e["type"] == "approval_required"]
    assert ap and ap[0]["approval"]["tool"] in ("mail_send", "gmail_send")
    assert c.post("/api/jobs/checks/run").json()["status"] == "ok"
    titles = [n["title"] for n in c.get("/api/nudges").json()["items"] if n["kind"] == "followup"]
    assert titles.count("Reply to Priya") == 1                    # in Apple Mail and Gmail: one nudge
