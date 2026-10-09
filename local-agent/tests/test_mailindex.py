"""Apple Mail without making Mail.app balloon: its index first, a bounded AppleScript otherwise,
and background checks that never pile onto Mail (0.17.2)."""
import asyncio
import re
import sqlite3
import time
from pathlib import Path

import pytest

from localagent.connectors.mac import MailGuard, mail_tools
from localagent.connectors.mailindex import ANSWERED, MAC_EPOCH, MailIndex, emlx_text

SCRIPTS = Path(__file__).resolve().parents[1] / "src/localagent/connectors/scripts"
NOW = time.time()


def make_index(mail_dir: Path, shape: str = "modern", mac_time: bool = False) -> Path:
    """A small Envelope Index like Mail's: inbox + sent mailboxes, subjects, addresses, summaries."""
    v = mail_dir / "V10"
    (v / "MailData").mkdir(parents=True)
    db = sqlite3.connect(v / "MailData" / "Envelope Index")
    db.executescript("""
        CREATE TABLE mailboxes (ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE subjects (ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE addresses (ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE summaries (ROWID INTEGER PRIMARY KEY, summary TEXT);
    """)
    cols = "ROWID INTEGER PRIMARY KEY, subject INTEGER, sender INTEGER, date_received INTEGER, mailbox INTEGER, summary INTEGER, flags INTEGER"
    if shape == "modern":
        cols += ", read INTEGER, deleted INTEGER"
    db.execute(f"CREATE TABLE messages ({cols})")
    db.executemany("INSERT INTO mailboxes VALUES (?,?)", [(1, "imap://ACCT-1/INBOX"), (2, "imap://ACCT-1/Sent Messages"),
                                                          (3, "ews://ACCT-2/Inbox")])
    db.executemany("INSERT INTO addresses VALUES (?,?,?)", [(1, "priya@acme.com", "Priya"), (2, "news@substack.com", ""),
                                                            (3, "sam@example.com", "Sam")])
    rows = [  # id, subject, sender, days ago, mailbox, flags (read=1, answered=4), deleted
        (1001, "Can you review the deck?", 1, 2, 1, 1, 0),
        (1002, "Weekly newsletter", 2, 1.5, 1, 0, 0),
        (1003, "Lunch?", 3, 0.1, 3, 0, 0),
        (1004, "Already answered", 3, 2, 1, 1 | ANSWERED, 0),
        (1005, "Sent by me", 3, 2, 2, 1, 0),
        (1006, "Deleted one", 1, 2, 1, 0, 1),
        (1007, "Too old", 1, 30, 1, 0, 0),
    ]
    for i, (rid, subj, snd, days, box, flags, deleted) in enumerate(rows, start=1):
        db.execute("INSERT INTO subjects VALUES (?,?)", (i, subj))
        db.execute("INSERT INTO summaries VALUES (?,?)", (i, f"Preview of {subj}"))
        ts = NOW - days * 86400 - (MAC_EPOCH if mac_time else 0)
        vals = [rid, i, snd, int(ts), box, i, flags]
        if shape == "modern":
            vals += [flags & 1, deleted]
        elif deleted:
            continue
        db.execute(f"INSERT INTO messages VALUES ({','.join('?' * len(vals))})", vals)
    db.commit()
    db.close()
    return v


def write_emlx(v: Path, rowid: int, body: bytes, account="ACCT-1", box="INBOX", partial=False):
    sub = "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""
    d = v / account / f"{box}.mbox" / "STORE-UUID" / "Data" / sub / "Messages"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rowid}{'.partial' if partial else ''}.emlx").write_bytes(str(len(body)).encode() + b"\n" + body + b"\n<plist/>")


class Runner:
    def __init__(self, outputs=None):
        self.calls, self.outputs = [], outputs or {}

    async def run(self, name, args):
        self.calls.append(name)
        return self.outputs.get(name, "")


def tools_for(index, runner, guard=None):
    return {t.name: t for t in mail_tools(runner, index, guard)}


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("shape,mac_time", [("modern", False), ("flags_only", False), ("modern", True)])
def test_index_lists_and_followups(tmp_path, shape, mac_time):
    make_index(tmp_path, shape, mac_time)
    idx = MailIndex(tmp_path)
    assert idx.status() == (True, "reads Mail's index")
    recent = idx.recent(limit=10)
    assert [r["subject"] for r in recent][:3] == ["Lunch?", "Weekly newsletter", "Can you review the deck?"]
    assert "Sent by me" not in [r["subject"] for r in recent] and "Deleted one" not in [r["subject"] for r in recent]
    assert recent[0]["from"] == "Sam <sam@example.com>" and recent[0]["snippet"] == "Preview of Lunch?"
    assert [r["subject"] for r in idx.recent(query="acme")] == ["Can you review the deck?", "Too old"]
    assert all(not r["read"] for r in idx.recent(unread_only=True))
    f = [r["subject"] for r in idx.followups(1, 7, now=NOW)]
    assert f == ["Weekly newsletter", "Can you review the deck?"]          # replied, sent, deleted, too old excluded
    assert len(idx.recent(limit=2)) == 2


def test_unrecognised_index_falls_back_to_a_small_applescript(tmp_path):
    v = make_index(tmp_path)
    db = sqlite3.connect(v / "MailData" / "Envelope Index")
    db.execute("ALTER TABLE messages RENAME COLUMN date_received TO received_at")
    db.commit()
    db.close()
    idx = MailIndex(tmp_path)
    ok, why = idx.status()
    assert not ok and "date_received" in why
    r = Runner({"mail_list": "42\x1fLunch?\x1fSam\x1f-600\x1ffalse\x1f\x1e"})
    out = run(tools_for(idx, r)["mail_list"].run({}))
    assert r.calls == ["mail_list"] and out.data[0]["subject"] == "Lunch?"
    assert not MailIndex(tmp_path / "nothing").status()[0]


def test_read_from_emlx_without_mail_app(tmp_path):
    v = make_index(tmp_path)
    write_emlx(v, 1001, b"From: Priya <priya@acme.com>\nSubject: Can you review the deck?\nContent-Type: text/plain\n\n"
                        b"Comments by Thursday please.\n")
    html_msg = (b"From: Sam\nSubject: Lunch?\nMIME-Version: 1.0\nContent-Type: multipart/alternative; boundary=XX\n\n"
                b"--XX\nContent-Type: text/html\n\n<html><style>p{}</style><p>Free <b>tomorrow</b>?</p></html>\n--XX--\n")
    write_emlx(v, 1003, html_msg, account="ACCT-2", box="Inbox", partial=True)
    r = Runner()
    t = tools_for(MailIndex(tmp_path), r)
    out = run(t["mail_read"].run({"id": 1001}))
    assert "Comments by Thursday" in out.content and out.untrusted and r.calls == []
    out = run(t["mail_read"].run({"id": 1003}))
    assert "Free tomorrow ?" in out.content.replace("  ", " ") or "Free tomorrow?" in out.content
    # not on disk (e.g. not downloaded): the bounded AppleScript reads that one message
    r.outputs["mail_read"] = "Weekly newsletter\x1fNews\x1f-86400\x1fTop stories"
    out = run(t["mail_read"].run({"id": 1002}))
    assert r.calls == ["mail_read"] and "Top stories" in out.content


def test_emlx_plain_and_html(tmp_path):
    p = tmp_path / "1.emlx"
    body = b"Subject: x\nContent-Type: text/html; charset=utf-8\n\n<p>Hello&nbsp;<i>there</i></p><script>evil()</script>"
    p.write_bytes(str(len(body)).encode() + b"\n" + body)
    assert emlx_text(p).replace("\xa0", " ").split() == ["Hello", "there"]


def test_background_checks_never_pile_onto_mail_app(tmp_path, monkeypatch):
    clock = [1_000_000.0]
    r = Runner({"mail_followups": "7\x1fCan you review the deck?\x1fPriya\x1f-172800\x1f\x1e"})
    guard = MailGuard(r, clock=lambda: clock[0])
    rss = [None]
    monkeypatch.setattr(MailGuard, "mail_rss_mb", staticmethod(lambda: rss[0]))
    t = tools_for(MailIndex(tmp_path / "none"), r, guard)["mail_followups"]
    bg = {"_background": True}
    assert run(t.run(bg)).data[0]["subject"] == "Can you review the deck?"
    with pytest.raises(Exception, match="less than 3 hours"):
        run(t.run(bg))                                             # every 30 min used to hit Mail
    assert r.calls == ["mail_followups"]
    run(t.run({}))                                                 # you asking is never throttled
    clock[0] += 3 * 3600 + 1
    rss[0] = 3000                                                  # Mail already at ~3 GB
    with pytest.raises(Exception, match="already using 2.9 GB"):
        run(t.run(bg))
    rss[0] = 300
    r.last_timeout = {"mail_followups": clock[0] - 60}             # osascript gave up a minute ago
    with pytest.raises(Exception, match="didn't answer in time"):
        run(t.run(bg))
    assert guard.last_skip == "Mail didn't answer in time recently"
    r.last_timeout = {}
    run(t.run(bg))
    assert r.calls.count("mail_followups") == 3


def test_index_backed_background_checks_run_every_time(tmp_path, monkeypatch):
    make_index(tmp_path)
    r = Runner()
    guard = MailGuard(r)
    monkeypatch.setattr(MailGuard, "mail_rss_mb", staticmethod(lambda: 50_000))   # even with Mail huge
    t = tools_for(MailIndex(tmp_path), r, guard)
    for _ in range(3):
        assert run(t["mail_followups"].run({"_background": True})).data
        assert run(t["mail_list"].run({"_background": True, "unread_only": True})).data
    assert r.calls == [] and guard.source == "index"


def code(name):
    return "\n".join(line for line in (SCRIPTS / name).read_text().splitlines() if not line.strip().startswith("--"))


@pytest.mark.parametrize("name", ["mail_list.applescript", "mail_followups.applescript", "mail_read.applescript"])
def test_scripts_never_search_a_whole_inbox(name):
    src = code(name)
    assert not re.search(r"\bwhose\b", src)                       # whole-inbox searches made Mail balloon
    assert "messages of inbox" not in src
    assert "WINDOW" in src and "messages 1 thru" in src
    if name != "mail_read.applescript":
        assert "content of" not in src                             # lists never load message bodies


def test_trust_check(action_client, monkeypatch, tmp_path):
    from localagent import trust
    from test_trust import rt_of

    rt = rt_of(action_client)
    monkeypatch.setattr(type(rt), "mac_available", property(lambda self: True), raising=False)
    rt.settings.enable_mail = True
    r = Runner()
    tools = tools_for(MailIndex(tmp_path / "none"), r)
    rt.tools.update(tools)
    monkeypatch.setattr(MailGuard, "mail_rss_mb", staticmethod(lambda: 4096))
    check = next(p for p in trust.posture(rt) if p["id"] == "mail")
    assert check["ok"] is False and "4.0 GB" in check["detail"] and "Quit and reopen Mail" in check["fix"]
    make_index(tmp_path / "mail")
    rt.tools.update(tools_for(MailIndex(tmp_path / "mail"), r))
    check = next(p for p in trust.posture(rt) if p["id"] == "mail")
    assert check["ok"] and "reads Mail's index" in check["detail"]


@pytest.mark.skipif(not __import__("shutil").which("osacompile"), reason="needs macOS (osacompile)")
@pytest.mark.parametrize("script", sorted(p.name for p in SCRIPTS.glob("*.applescript")))
def test_scripts_compile_on_macos(script, tmp_path):
    """Every bundled AppleScript must compile (the macOS CI runner checks this)."""
    import subprocess

    r = subprocess.run(["osacompile", "-o", str(tmp_path / "x.scpt"), str(SCRIPTS / script)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_records_start_from_text():
    """`(id of m) & US & …` starts with a number and makes an AppleScript list, not text."""
    for name in ("mail_list.applescript", "mail_followups.applescript"):
        src = code(name)
        assert "((id of m) as text) & US" in src and not re.search(r"to \(id of m\) &", src)
