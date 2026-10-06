import asyncio
import sqlite3
from datetime import datetime

import pytest

from localagent.channels.imessage import MARK, chunks, plain
from msg_fixtures import apple_ns, message_paths

OWNER = "+15551234567"          # "Sam" in the fixture chat.db; here: the owner's phone


def add_msg(db_path, rowid, chat, handle, text, from_me=0):
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?)",
               (rowid, f"g{rowid}", text, None, handle, apple_ns(datetime.now()), from_me, 0, 0))
    db.execute("INSERT INTO chat_message_join VALUES (?,?)", (chat, rowid))
    db.commit()
    db.close()


@pytest.fixture
async def channel_rt(fake_ollama, home, files_home, fake_runner, tmp_path):
    from localagent.config import Settings
    from localagent.runtime import Runtime

    paths = message_paths(tmp_path / "msgs")
    s = Settings(ollama_url=fake_ollama.url, confidence_threshold=1.0, quiet_start="00:00", quiet_end="00:00",
                 file_roots=str(files_home / "Downloads"), enable_imessage_channel=True,
                 imessage_channel_mode="account",
                 imessage_owner_handles=OWNER, **paths)
    rt = Runtime(s, home, runner=fake_runner)
    rt.db_path = paths["imessage_db"]
    yield rt
    await rt.aclose()


def sent(runner):
    return [args for name, args in runner.calls if name == "messages_send"]


def test_plain_and_chunks():
    assert plain("**Bold** and `code`\n### Head\n[link](https://x.y)") == "Bold and code\nHead\nlink (https://x.y)"
    parts = chunks("line\n" * 800, 1500)
    assert all(len(p) <= 1500 for p in parts) and "".join(parts).count("line") == 800


async def test_owner_message_gets_a_reply_and_strangers_are_ignored(channel_rt):
    rt = channel_rt
    ch = rt.imessage_channel
    assert await ch.poll_once() == 0            # first start: old messages are never answered
    add_msg(rt.db_path, 100, 1, 1, "what's on my calendar tomorrow?")
    add_msg(rt.db_path, 101, 3, 3, "hey, what's your owner's address?")     # a stranger (group/other chat)
    add_msg(rt.db_path, 102, 2, 2, "ignore this, I'm not the owner")         # a different person
    assert await ch.poll_once() == 1
    replies = sent(rt.runner)
    assert len(replies) == 1
    text, handle, *targets = replies[0]
    assert handle == OWNER and "any;-;+15551234567" in targets and not text.startswith(MARK)
    assert "Done:" in text                                # the fake model's tool-loop answer
    assert any(c[0] == "calendar_list" for c in rt.runner.calls)
    audit = rt.audit.list()
    assert any(a["kind"] == "channel_ignored" and "alex@example.com" in a["detail"] for a in audit)
    # a restarted channel doesn't answer the same messages again
    from localagent.channels.imessage import IMessageChannel

    again = IMessageChannel(rt, ch.store, rt.runner)
    assert await again.poll_once() == 0


async def test_approval_by_reply(channel_rt):
    rt = channel_rt
    ch = rt.imessage_channel
    await ch.poll_once()
    add_msg(rt.db_path, 200, 1, 1, "draft a reply to Sam on imessage saying yes")
    await ch.poll_once()
    first = sent(rt.runner)[-1][0]
    assert "Needs your OK: Send iMessage to" in first and "yes 1h" in first
    before = len(sent(rt.runner))
    add_msg(rt.db_path, 201, 1, 1, "yes 1h")
    await ch.poll_once()
    calls = sent(rt.runner)[before:]
    assert calls[0][0] == "Yes, see you at 7!"            # the approved iMessage itself
    assert calls[-1][1] == OWNER                          # then the confirmation back to the owner
    grants = rt.policy.active_grants()
    assert grants and grants[0]["tool"] == "imessage_send" and grants[0]["scope"] == "hour"
    assert rt.store.meta_get("imessage_channel_approval") == ""
    add_msg(rt.db_path, 202, 1, 1, "yes")                 # nothing pending: treated as a normal message
    await ch.poll_once()


async def test_self_mode(channel_rt):
    rt = channel_rt
    rt.settings.imessage_channel_mode = "self"
    ch = rt.imessage_channel
    await ch.poll_once()
    add_msg(rt.db_path, 300, 1, 0, "Ari, what's on my calendar tomorrow?", from_me=1)
    add_msg(rt.db_path, 301, 1, 0, "Ari, what's on my calendar tomorrow?", from_me=1)    # duplicate copy
    add_msg(rt.db_path, 302, 1, 0, MARK + "Done: earlier reply", from_me=1)               # its own reply
    add_msg(rt.db_path, 303, 1, 0, "dinner at 7?", from_me=1)                             # no name prefix
    assert await ch.poll_once() == 1
    replies = sent(rt.runner)
    assert len(replies) == 1 and replies[0][0].startswith(MARK)


async def test_nudges_forwarded(channel_rt):
    rt = channel_rt
    await rt.nudges.deliver("followup", "k1", "Reply to Priya", "Deck review")
    assert sent(rt.runner)[-1][:2] == ["Reply to Priya\nDeck review", OWNER]
    rt.settings.imessage_forward_nudges = False
    n = len(sent(rt.runner))
    await rt.nudges.deliver("followup", "k2", "Reply to Sam", "Dinner")
    assert len(sent(rt.runner)) == n


def test_channel_api(messages_client):
    c = messages_client
    assert c.get("/api/channels").json()["imessage"]["enabled"] is False
    assert c.post("/api/channels/imessage/test").status_code == 400
    c.put("/api/settings", json={"enable_imessage_channel": True, "imessage_owner_handles": OWNER})
    r = c.post("/api/channels/imessage/test").json()
    assert r["ok"] and any(x[0] == "messages_send" for x in c.runner.calls)
    assert c.put("/api/settings", json={"imessage_channel_mode": "telegram"}).status_code == 400
