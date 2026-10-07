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
    code = client.post("/api/signin-code").json()["code"]             # what `localagent open` asks for
    token = client.headers.pop("Authorization").split()[1]
    assert client.get("/auth", params={"c": "wrong"}, follow_redirects=False).status_code == 403
    assert client.get("/auth", params={"t": token}, follow_redirects=False).status_code == 403  # never the secret
    r = client.get("/auth", params={"c": code, "next": "//evil.example/x"}, follow_redirects=False)
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


def test_sensitive_settings_need_confirmation_and_are_audited(client):
    r = client.put("/api/settings", json={"browser_executable": "/tmp/evil", "agent_name": "Juno"})
    assert r.status_code == 428
    keys = [c["key"] for c in r.json()["detail"]["confirm"]]
    assert keys == ["browser_executable"]
    assert client.get("/api/settings").json()["agent_name"] != "Juno"      # nothing half-applied
    ok = client.put("/api/settings", json={"browser_executable": "/tmp/evil", "agent_name": "Juno"},
                    headers={"X-Confirm": "browser_executable"})
    assert ok.status_code == 200 and ok.json()["browser_executable"] == "/tmp/evil"
    audit = client.get("/api/audit").json()
    changed = {a["tool"]: a for a in audit if a["kind"] == "settings_changed"}
    assert changed["browser_executable"]["outcome"] == "sensitive" and "/tmp/evil" in changed["browser_executable"]["detail"]
    assert changed["agent_name"]["outcome"] == "ok"
    nudges = client.get("/api/nudges").json()
    assert any(n["kind"] == "security" for n in nudges["items"])
    # Pointing Ollama back at this computer, or switching a feature off, needs no confirmation.
    assert client.put("/api/settings", json={"ollama_url": "http://127.0.0.1:11434"}).status_code == 200
    assert client.put("/api/settings", json={"cloud_enabled": False}).status_code == 200
    assert client.put("/api/settings", json={"ollama_url": "http://10.0.0.5:11434"}).status_code == 428


def test_rejected_update_leaves_settings_untouched():
    from localagent.config import Settings

    s = Settings()
    with pytest.raises(ValueError):
        s.update({"agent_name": "Juno", "max_tool_steps": 99})
    assert s.agent_name != "Juno"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_data_folder_is_private(tmp_path, settings, home):
    from localagent.runtime import Runtime
    import asyncio

    (home / "server.log").write_text("x")
    os.chmod(home, 0o755)
    os.chmod(home / "server.log", 0o644)
    rt = Runtime(settings, home)
    asyncio.run(rt.aclose())
    assert oct(os.stat(home).st_mode & 0o777) == "0o700"
    for f in ("localagent.db", "server.log"):
        assert oct(os.stat(home / f).st_mode & 0o777) == "0o600", f


def test_disk_encryption_check_never_raises():
    on, detail = security.disk_encryption()
    assert on in (True, False, None) and isinstance(detail, str)


def test_new_install_starts_with_personal_connectors_off(tmp_path):
    from localagent.config import FIRST_RUN_OFF, Settings, load_settings, save_settings

    fresh = load_settings(tmp_path)
    assert not any(getattr(fresh, k) for k in FIRST_RUN_OFF) and fresh.enable_calendar
    old = Settings(enable_mail=True, enable_messages=True, agent_name="Juno")     # an upgrade keeps choices
    save_settings(old, tmp_path)
    cfg = tmp_path / "config.json"
    cfg.write_text(cfg.read_text().replace('"max_tool_steps": 5', '"max_tool_steps": 99'))
    assert '"max_tool_steps": 99' in cfg.read_text()
    kept = load_settings(tmp_path)
    assert kept.max_tool_steps == 5
    assert kept.enable_mail and kept.enable_messages and kept.agent_name == "Juno"   # one bad value isn't fatal


def test_signin_codes_are_single_use_short_lived_and_need_the_secret(client, monkeypatch):
    code = client.post("/api/signin-code").json()["code"]
    token = client.headers.pop("Authorization").split()[1]
    assert token not in code
    assert client.get("/auth", params={"c": code}, follow_redirects=False).status_code == 303
    client.cookies.clear()
    assert client.get("/auth", params={"c": code}, follow_redirects=False).status_code == 403   # used up
    # a signed-in browser (cookie only) can't mint codes for itself
    client.cookies.set(security.cookie_name(8765), token)
    assert client.post("/api/signin-code").status_code == 403
    client.cookies.clear()
    # expired after 60 s
    codes = security.SignInCodes()
    c = codes.issue()
    import time as _t
    real = _t.monotonic
    monkeypatch.setattr(_t, "monotonic", lambda: real() + 61)
    assert not codes.redeem(c)


def test_old_secret_is_replaced_once(tmp_path):
    """Up to 0.16 the secret was in sign-in links (browser history, sync): replace it on upgrade, once."""
    old = security.api_token(tmp_path)
    security.rotate_legacy_token(tmp_path)
    new = security.api_token(tmp_path)
    assert new != old and len(new) >= 32
    security.rotate_legacy_token(tmp_path)
    assert security.api_token(tmp_path) == new
