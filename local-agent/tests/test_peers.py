import asyncio
import socket

import httpx
import pytest

from conftest import FakeRunner
from localagent.tools.base import ToolError


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_rt(base, fake_ollama, name, user, runner):
    from localagent.config import Settings
    from localagent.runtime import Runtime

    port = free_port()
    s = Settings(ollama_url=fake_ollama.url, agent_name=name, user_name=user, a2a_enabled=True,
                 a2a_host="127.0.0.1", a2a_port=port, a2a_public_addr=f"http://127.0.0.1:{port}",
                 quiet_start="00:00", quiet_end="00:00", enable_messages=False, file_roots=str(base))
    base.mkdir(parents=True, exist_ok=True)
    return Runtime(s, base, runner=runner)


@pytest.fixture
async def pair(fake_ollama, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAGENT_NO_KEYRING", "1")
    a = make_rt(tmp_path / "abhi", fake_ollama, "Ari", "Abhishek", FakeRunner())
    b = make_rt(tmp_path / "sam", fake_ollama, "Max", "Sam", FakeRunner())
    await a.start_a2a()
    await b.start_a2a()
    for _ in range(100):
        if a._a2a[0].started and b._a2a[0].started:
            break
        await asyncio.sleep(0.02)
    yield a, b
    await a.aclose()
    await b.aclose()


async def test_pair_and_encrypted_round_trips(pair):
    a, b = pair
    code = a.peers.invite()
    peer = await b.peers.accept(code)
    assert peer["name"] == "Ari" and peer["owner"] == "Abhishek"
    assert [p["name"] for p in a.peers.list()] == ["Max"]                 # the inviter learned about Sam's agent
    with pytest.raises(ToolError, match="refused"):
        await b.peers.accept(code)                                       # one-time invite
    assert [p["name"] for p in b.peers.list()] == ["Ari"]               # ...and the pairing survives
    b.build_tools()
    ask = b.tools["peer_ask"]
    assert ask.tier == "write"
    # free/busy isn't allowed until Abhishek allows it: the question waits for him
    res = await ask.run({"peer": "Abhishek", "kind": "freebusy", "start": "2030-01-01", "end": "2030-01-01"})
    assert "passed this on" in res.content and res.untrusted
    waiting = a.peers.waiting()
    assert len(waiting) == 1
    nudges = a.nudges.list()
    assert nudges[0]["kind"] == "peer" and nudges[0]["data"]["peer_inbox_id"] == waiting[0]["id"]
    # allow free/busy: answered automatically, times only, no titles
    a.peers.set_scopes(a.peers.list()[0]["id"], ["freebusy", "message"])
    res = await ask.run({"peer": "Abhishek", "kind": "freebusy", "start": "2030-01-01", "end": "2030-01-01"})
    assert res.data["answer"].startswith("Busy: ") and "Dentist" not in res.data["answer"]
    # a message is delivered as a nudge
    await ask.run({"peer": "abhishek", "kind": "message", "text": "Dinner at 7 on Friday?"})
    assert any(n["title"] == "Message from Sam's agent" and n["body"] == "Dinner at 7 on Friday?"
               for n in a.nudges.list())
    # Abhishek answers the waiting question; Sam gets it as a nudge
    await a.peers.reply(waiting[0]["id"], "Free after 3pm")
    assert any(n["title"] == "Abhishek's agent replied" and n["body"] == "Free after 3pm" for n in b.nudges.list())
    assert a.peers.waiting() == []


async def test_rejections(pair, fake_ollama):
    a, b = pair
    await b.peers.accept(a.peers.invite())
    url = a.peers.address() + "/a2a/v1/inbox"
    env = b.peers.seal(a.peers.public, {"type": "ask", "id": "x", "kind": "message", "text": "hi"})
    async with httpx.AsyncClient(trust_env=False) as c:
        ok = await c.post(url, json=env)
        assert ok.status_code == 200
        assert (await c.post(url, json=env)).status_code == 403                      # replay
        tampered = dict(env, box=env["box"][:-4] + ("AAAA" if not env["box"].endswith("AAAA") else "BBBB"))
        assert (await c.post(url, json=tampered)).status_code == 403
        stranger = make_rt(a.base.parent / "eve", fake_ollama, "Eve", "Eve", FakeRunner())
        bad = stranger.peers.seal(a.peers.public, {"type": "ask", "id": "y", "kind": "message", "text": "x"})
        r = await c.post(url, json=bad)
        assert r.status_code == 403 and "unknown agent" in r.text
        await stranger.aclose()
    kinds = [x["kind"] for x in a.audit.list()]
    assert kinds.count("peer_rejected") == 3


async def test_peer_api(pair):
    a, b = pair
    from localagent.connectors.peers import Peers

    with pytest.raises(ToolError, match="la1-"):
        Peers.decode_invite("hello")
    with pytest.raises(ToolError, match="damaged"):
        Peers.decode_invite("la1-xxxx")
    with pytest.raises(ToolError, match="own invite"):
        await a.peers.accept(a.peers.invite())
    assert a.peers.fingerprint.count(" ") == 3
