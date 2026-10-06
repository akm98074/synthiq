"""Which tools exist right now, given settings and platform."""
from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..connectors.documents import document_tools
from ..connectors.files import FileSpace, file_tools, parse_roots
from ..connectors.mac import calendar_tools, contacts_tools, mail_tools, notes_tools, reminder_tools
from ..connectors.messages import ContactNames, IMessages, WhatsApp, messages_tools, present
from .base import Tool

CONNECTORS = [
    {"id": "calendar", "name": "Calendar", "mac": True, "setting": "enable_calendar",
     "about": "Read events and add new ones (Apple Calendar, including Google/iCloud/Exchange accounts added to it)."},
    {"id": "reminders", "name": "Reminders", "mac": True, "setting": "enable_reminders",
     "about": "Read open reminders and create new ones."},
    {"id": "notes", "name": "Notes", "mac": True, "setting": "enable_notes",
     "about": "Search Apple Notes and create notes."},
    {"id": "mail", "name": "Mail", "mac": True, "setting": "enable_mail",
     "about": "Search the inbox, read messages, open drafts, and send (send always asks first)."},
    {"id": "contacts", "name": "Contacts", "mac": True, "setting": "enable_contacts",
     "about": "Look up email addresses and phone numbers."},
    {"id": "messages", "name": "Messages & WhatsApp", "mac": True, "setting": "enable_messages",
     "about": "Read iMessage/SMS and WhatsApp chats, find ones waiting on your reply, and reply "
              "(iMessage sends after you approve; WhatsApp opens with the reply typed for you to send). "
              "Needs Full Disk Access for Terminal."},
    {"id": "files", "name": "Files", "mac": False, "setting": "enable_files",
     "about": "Find, list, move, open and trash files in the allowed folders."},
    {"id": "documents", "name": "Documents", "mac": False, "setting": "enable_documents",
     "about": "Create PDFs and Excel spreadsheets in ~/Documents/LocalAIAgent."},
]

# A cheap read call per connector, used by the "Test" button (it also triggers
# the macOS permission prompt so the user can answer it up front).
TEST_CALLS = {
    "calendar": ("calendar_list_events", {}),
    "reminders": ("reminders_list", {"limit": 3}),
    "notes": ("notes_search", {"query": "a", "limit": 1}),
    "mail": ("mail_list", {"limit": 1}),
    "contacts": ("contacts_find", {"name": "a", "limit": 1}),
    "messages": ("messages_list", {"limit": 3}),
    "files": ("files_list", {"folder": "~/Downloads", "limit": 3}),
    "documents": None,
}


def build_tools(settings: Settings, runner, mac_available: bool, eventkit=None) -> dict[str, Tool]:
    tools: list[Tool] = []
    if mac_available:
        if settings.enable_calendar:
            tools += calendar_tools(runner, eventkit, settings.calendar_backend)
        if settings.enable_reminders:
            tools += reminder_tools(runner)
        if settings.enable_notes:
            tools += notes_tools(runner)
        if settings.enable_mail:
            tools += mail_tools(runner)
        if settings.enable_contacts:
            tools += contacts_tools(runner)
        if settings.enable_messages:
            tools += messages_tools(runner, *message_sources(settings), settings.messages_include_groups)
    if settings.enable_files:
        tools += file_tools(FileSpace(parse_roots(settings.file_roots)))
    if settings.enable_documents:
        tools += document_tools(Path(settings.documents_dir).expanduser())
    return {t.name: t for t in tools}


def message_sources(settings: Settings) -> tuple[IMessages | None, WhatsApp | None]:
    names = ContactNames(Path(settings.addressbook_dir).expanduser())
    wa_path = Path(settings.whatsapp_db).expanduser()
    imessage = IMessages(Path(settings.imessage_db).expanduser(), names)
    whatsapp = WhatsApp(wa_path, names) if settings.enable_whatsapp and present(wa_path) else None
    return imessage, whatsapp


def connector_status(settings: Settings, mac_available: bool, tools: dict[str, Tool]) -> list[dict]:
    out = []
    for c in CONNECTORS:
        available = mac_available or not c["mac"]
        enabled = getattr(settings, c["setting"])
        out.append({
            **{k: c[k] for k in ("id", "name", "about", "setting")},
            "available": available,
            "enabled": enabled,
            "active": available and enabled,
            "tools": [{"name": t.name, "tier": t.tier} for t in tools.values() if t.connector == c["id"]],
            "testable": TEST_CALLS.get(c["id"]) is not None,
            "note": None if available else "Needs macOS",
        })
    return out


def candidates(tools: dict[str, Tool], intent: str) -> list[Tool]:
    return [t for t in tools.values() if intent in t.intents]
