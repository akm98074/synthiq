"""The local API guard (security.py): Host allowlist, per-install secret, same-origin writes."""
import json
import os
import sys

import pytest

from localagent import security


def test_foreign_host_is_refused_dns_rebinding(client):
    r = client.get("/api/memories", headers={"Host": "attacker.example:8765"})
    assert r.status_code == 421
    assert client.get("/api/memories").status_code == 200


def test_no_secret_no_access(client):
    client.headers.pop("Authorization")
    assert client.get("/api/memories").status_code == 401
    assert client.get("/api/settings").status_code == 401
    assert client.post("/api/peers/invite").status_code == 401           # body-less POSTs too
    assert client.post("/api/channels/imessage/test").status_code == 401
    assert client.get("/api/health").status_code == 200                  # version only
    page = client.get("/")
    assert page.status_code == 401 and "localagent open" in page.text
    assert client.get("/ui/app.js").status_code == 401


def test_cross_origin_writes_refused(client):
    r = client.put("/api/settings", content=json.dumps({"agent_name": "Pwn"}),
                   headers={"Origin": "https://evil.example", "Content-Type": "application/json"})
    assert r.status_code == 403
    r = client.post("/api/jobs/brief/run", headers={"Origin": "http://localhost:8765"})
    assert r.status_code != 403                                          # our own origin is fine


def test_auth_link_sets_session_cookie(client):
    token = client.headers.pop("Authorization").split()[1]
    assert client.get("/auth", params={"t": "wrong"}, follow_redirects=False).status_code == 403
    r = client.get("/auth", params={"t": token, "next": "//evil.example/x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"         # no open redirect
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/memories").status_code == 200               # cookie now carried
    ui = client.get("/")
    assert ui.status_code == 200 and "default-src 'self'" in ui.headers["content-security-policy"]


def test_token_file_is_private_and_stable(tmp_path):
    t1 = security.api_token(tmp_path)
    assert len(t1) >= 32 and security.api_token(tmp_path) == t1
    if sys.platform != "win32":
        assert oct(os.stat(tmp_path / security.TOKEN_FILE).st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("host,ok", [("127.0.0.1:8765", True), ("localhost:8765", True),
                                     ("127.0.0.1:9999", False), ("evil.example:8765", False), (None, False)])
def test_host_allowlist(host, ok):
    res = security.check("GET", "/api/x", host, None, "tok" * 11, None, 8765, "tok" * 11)
    assert (res is None) == ok
