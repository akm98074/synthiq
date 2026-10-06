import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from localagent.channels.phone import PIN, TOKEN, digits_of, phone_app, signature

PUBLIC = "https://abc.trycloudflare.com"
TOK = "0123456789abcdef0123456789abcdef"
OWNER = "+14255550100"


@pytest.fixture
def phone(fake_ollama, home, files_home, fake_runner):
    from localagent.config import Settings
    from localagent.runtime import Runtime

    s = Settings(ollama_url=fake_ollama.url, confidence_threshold=1.0, enable_messages=False,
                 enable_web_search=False, file_roots=str(files_home / "Downloads"), phone_enabled=True,
                 phone_owner_numbers=OWNER, phone_public_url=PUBLIC)
    rt = Runtime(s, home, runner=fake_runner)
    rt.vault.set(TOKEN, TOK)
    rt.vault.set(PIN, "2468")
    with TestClient(phone_app(rt)) as c:
        c.rt = rt
        yield c


def post(c, path, params, token=TOK, sign=True):
    url = PUBLIC + path
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if sign:
        headers["X-Twilio-Signature"] = signature(token, url, params)
    return c.post(path, content=urlencode(params), headers=headers)


def test_signature_matches_twilio_example():
    # Twilio's documented example: token 12345, this URL and params give this signature.
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234",
              "From": "+12349013030", "To": "+18005551212"}
    assert signature("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params) == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


def test_rejects_unsigned_forged_and_strangers(phone):
    c = phone
    assert post(c, "/twilio/voice", {"From": OWNER}, sign=False).status_code == 403
    assert post(c, "/twilio/voice", {"From": OWNER}, token="f" * 32).status_code == 403
    r = post(c, "/twilio/voice", {"From": "+15550001111"})
    assert r.status_code == 200 and "this number is private" in r.text and "<Hangup/>" in r.text
    c.rt.settings.phone_enabled = False
    assert post(c, "/twilio/voice", {"From": OWNER}).status_code == 403
    kinds = [a["kind"] for a in c.rt.audit.list()]
    assert kinds.count("phone_rejected") == 4


def sign_in(c, sid="CA1"):
    r = post(c, "/twilio/voice", {"From": OWNER, "CallSid": sid})
    assert 'action="pin"' in r.text and "PIN" in r.text
    r = post(c, "/twilio/pin", {"From": OWNER, "CallSid": sid, "Digits": "2468"})
    assert '<Gather input="speech" action="gather"' in r.text


def test_pin_is_required_and_limited(phone):
    c = phone
    r = post(c, "/twilio/gather", {"From": OWNER, "CallSid": "CA9", "SpeechResult": "read my email"})
    assert r.text.endswith("<Hangup/></Response>") and "One moment" not in r.text   # no PIN yet: nothing
    post(c, "/twilio/voice", {"From": OWNER, "CallSid": "CA9"})
    for i in range(3):
        r = post(c, "/twilio/pin", {"From": OWNER, "CallSid": "CA9", "Digits": "1111"})
    assert "Goodbye" in r.text and "<Hangup/>" in r.text
    assert post(c, "/twilio/pin", {"From": OWNER, "CallSid": "CA8", "SpeechResult": "two four six eight"}
                ).text.count("What can I do") == 1                                    # spoken PIN works
    r = post(c, "/twilio/voice", {"From": OWNER, "CallSid": "CA7", "StirVerstat": "TN-Validation-Failed-C"})
    assert "private" in r.text                                                         # spoofed caller ID
    c.rt.vault.delete(PIN)
    assert "needs a PIN" in post(c, "/twilio/voice", {"From": OWNER, "CallSid": "CA6"}).text
    kinds = [a["kind"] for a in c.rt.audit.list()]
    assert kinds.count("phone_pin_wrong") == 3
    assert digits_of("1-2 three, four") == "1234"


def test_call_flow(phone):
    c = phone
    sign_in(c)
    r = post(c, "/twilio/gather", {"From": OWNER, "CallSid": "CA1", "SpeechResult": "what's on my calendar tomorrow?"})
    assert "One moment." in r.text and 'Redirect method="POST">result?id=' in r.text
    job = r.text.split("result?id=")[1].split("<")[0]
    for _ in range(100):
        r = post(c, f"/twilio/result?id={job}", {"From": OWNER, "CallSid": "CA1"})
        if "<Pause" not in r.text:
            break
        time.sleep(0.1)
    assert "Done:" in r.text and "Anything else?" in r.text
    assert "<" not in r.text.split("<Say")[1].split(">", 1)[1].split("</Say>")[0]   # spoken text is escaped
    assert "Bye!" in post(c, "/twilio/gather", {"From": OWNER, "CallSid": "CA1", "SpeechResult": "goodbye"}).text


def test_no_sending_by_phone(phone):
    c = phone
    sign_in(c, "CA2")
    r = post(c, "/twilio/gather", {"From": OWNER, "CallSid": "CA2", "SpeechResult": "send an email to sam saying hi"})
    job = r.text.split("result?id=")[1].split("<")[0]
    for _ in range(100):
        r = post(c, f"/twilio/result?id={job}", {"From": OWNER, "CallSid": "CA2"})
        if "<Pause" not in r.text:
            break
        time.sleep(0.1)
    assert not any(name == "mail_compose" for name, _ in c.rt.runner.calls)
    assert c.rt.policy.list(status="pending") == []                        # no approval card created by phone


def test_phone_api(messages_client):
    c = messages_client
    assert c.put("/api/phone/token", json={"token": "abc"}).status_code == 400
    st = c.put("/api/phone/token", json={"token": TOK}).json()
    assert st["has_token"] and st["port"] == 8767 and not st["has_pin"]
    assert c.put("/api/phone/pin", json={"pin": "12"}).status_code == 400
    assert c.put("/api/phone/pin", json={"pin": "1357"}).json()["has_pin"]
    c.put("/api/settings", json={"phone_public_url": PUBLIC}, headers={"X-Confirm": "phone_public_url"})
    assert c.get("/api/phone").json()["webhook"] == PUBLIC + "/twilio/voice"
