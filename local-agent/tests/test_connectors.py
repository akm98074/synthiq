import asyncio
from datetime import datetime

import pytest

from localagent.connectors.applescript import explain_error, parse_records, script_text
from localagent.connectors.files import FileSpace
from localagent.connectors.mac import calendar_tools, mail_tools
from localagent.tools.base import ToolError, parse_when, validate_args


def test_validate_args_coerces_and_requires():
    schema = {"properties": {"n": {"type": "integer"}, "tags": {"type": "array"},
                             "mode": {"type": "string", "enum": ["a", "b"]}}, "required": ["n"]}
    assert validate_args(schema, {"n": "3", "tags": "x, y", "extra": 1}) == {"n": 3, "tags": ["x", "y"]}
    with pytest.raises(ToolError):
        validate_args(schema, {})
    with pytest.raises(ToolError):
        validate_args(schema, {"n": 1, "mode": "c"})


def test_parse_when():
    assert parse_when("2026-10-06T15:30") == datetime(2026, 10, 6, 15, 30)
    assert parse_when("2026-10-06 15:30") == datetime(2026, 10, 6, 15, 30)
    assert parse_when("2026-10-06", end_of_day=True).hour == 23
    with pytest.raises(ToolError):
        parse_when("next tuesday")


def test_all_scripts_ship_and_take_argv():
    for name in ("calendar_list", "calendar_create", "reminders_list", "reminders_create", "notes_search",
                 "notes_create", "mail_list", "mail_read", "mail_compose", "contacts_find"):
        text = script_text(name)
        assert "on run argv" in text and "end run" in text


def test_parse_records_and_errors():
    assert parse_records("a\x1fb\x1ec\x1fd\x1e") == [["a", "b"], ["c", "d"]]
    assert "Automation" in explain_error("execution error: Not authorized to send Apple events to Calendar. (-1743)", "Calendar")


def test_calendar_create_passes_offsets(fake_runner):
    tool = {t.name: t for t in calendar_tools(fake_runner)}["calendar_create_event"]
    res = asyncio.run(tool.run({"title": "Lunch", "start": "2099-01-01T12:00", "duration_minutes": 30}))
    name, args = fake_runner.calls[-1]
    assert name == "calendar_create" and args[0] == "Lunch"
    assert int(args[2]) - int(args[1]) == 1800
    assert res.ok and "Home" in res.display


def test_mail_requires_real_addresses(fake_runner):
    tool = {t.name: t for t in mail_tools(fake_runner)}["mail_draft"]
    with pytest.raises(ToolError):
        asyncio.run(tool.run({"to": "Sam", "subject": "x", "body": "y"}))
    asyncio.run(tool.run({"to": "a@x.com; b@y.com", "subject": "x", "body": "y"}))
    assert fake_runner.calls[-1][1][0] == "a@x.com,b@y.com"


def test_filespace_stays_inside_roots(tmp_path):
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "report final.pdf").write_text("x")
    (tmp_path / "secret.txt").write_text("x")
    fs = FileSpace([root], trash_dir=tmp_path / "Trash")
    assert fs.search("report", None, "pdf", 10)[0]["name"] == "report final.pdf"
    with pytest.raises(ToolError):
        fs.resolve(str(tmp_path / "secret.txt"))
    with pytest.raises(ToolError):
        fs.resolve("../secret.txt")
    with pytest.raises(ToolError):
        fs.trash([str(root)])
    moved = fs.move(["report final.pdf"], str(root / "Archive"))
    assert (root / "Archive" / "report final.pdf").exists() and moved
