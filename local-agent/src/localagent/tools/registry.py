"""Which tools exist right now, given settings and platform."""
from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..connectors.documents import document_tools
from ..connectors.files import FileSpace, file_tools, parse_roots
from ..connectors.mac import calendar_tools, contacts_tools, mail_tools, notes_tools, reminder_tools
from ..connectors.apps import apps_tools
from ..connectors.browser import browser_tools
from ..connectors.screen import screen_tools
from ..connectors.websearch import ddg_fetch, web_tools
from ..connectors.messages import ContactNames, IMessages, WhatsApp, messages_tools, present
from ..skills import skill_tools
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
    {"id": "apps", "name": "Mac apps & Shortcuts", "mac": True, "setting": "enable_apps",
     "about": "Open apps, read and press buttons in their windows, type, and run your Shortcuts. Pressing and "
              "typing ask first. Needs Accessibility permission for Terminal."},
    {"id": "screen", "name": "Screen context", "mac": True, "setting": "screen_context_enabled",
     "about": "Off unless you turn it on. Reads the text on your screen every few minutes with on-device OCR "
              "(the picture is deleted at once), skips private apps, and forgets it after a couple of hours."},
    {"id": "files", "name": "Files", "mac": False, "setting": "enable_files",
     "about": "Find, list, move, open and trash files in the allowed folders."},
    {"id": "gmail", "name": "Gmail", "mac": False, "setting": "enable_gmail",
     "about": "Your Gmail directly (sign in with Google): search, read, find threads waiting on your reply, "
              "save drafts, and send (send asks first). Works without Apple Mail."},
    {"id": "web", "name": "Web search", "mac": False, "setting": "enable_web_search",
     "about": "Looks things up on the web (DuckDuckGo) for prices, shops, restaurants, hours and news, then "
              "reads the best page. Only the search words leave this Mac."},
    {"id": "browser", "name": "Browser", "mac": False, "setting": "enable_browser",
     "about": "Open web pages, read them, click links and fill in fields in the agent's own browser window. "
              "Anything that submits, sends, books or pays asks you every time; it never types passwords."},
    {"id": "skills", "name": "Custom skills", "mac": False, "setting": "enable_skills",
     "about": "Your own abilities: folders in the skills folder with a SKILL.md (create one with "
              "`localagent skill new NAME`). Scripts run sandboxed: no network unless the skill says so."},
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
    "apps": ("apps_list", {}),
    "gmail": ("gmail_search", {"limit": 1}),
    "web": ("web_search", {"query": "weather Seattle", "limit": 1}),
    "screen": ("screen_now", {}),
    "files": ("files_list", {"folder": "~/Downloads", "limit": 3}),
    "documents": None,
}


def build_tools(settings: Settings, runner, mac_available: bool, eventkit=None, browser=None,
                skills_dir: Path | None = None, screen=None, web_fetch=None) -> dict[str, Tool]:
    tools: list[Tool] = []
    if mac_available:
        if settings.enable_calendar:
            tools += calendar_tools(runner, eventkit, settings.calendar_backend)
        if settings.enable_reminders:
            tools += reminder_tools(runner)
        if settings.enable_notes:
            tools += notes_tools(runner)
        if settings.enable_mail:
            from ..connectors.mailindex import MailIndex

            tools += mail_tools(runner, MailIndex(Path(settings.mail_dir).expanduser()))
        if settings.enable_contacts:
            tools += contacts_tools(runner)
        if settings.enable_messages:
            tools += messages_tools(runner, *message_sources(settings), settings.messages_include_groups)
        if settings.enable_apps:
            tools += apps_tools(runner)
        if settings.screen_context_enabled and screen is not None:
            tools += screen_tools(screen)
    if settings.enable_files:
        tools += file_tools(FileSpace(parse_roots(settings.file_roots)))
    if settings.enable_documents:
        tools += document_tools(Path(settings.documents_dir).expanduser())
    if settings.enable_web_search:
        tools += web_tools(web_fetch or ddg_fetch)
    if settings.enable_browser and browser is not None:
        tools += browser_tools(browser)
    if settings.enable_skills and skills_dir is not None:
        tools += skill_tools(skills_dir, settings.skills_require_sandbox)
    return {t.name: t for t in tools}


def message_sources(settings: Settings) -> tuple[IMessages | None, WhatsApp | None]:
    names = ContactNames(Path(settings.addressbook_dir).expanduser())
    wa_path = Path(settings.whatsapp_db).expanduser()
    imessage = IMessages(Path(settings.imessage_db).expanduser(), names)
    whatsapp = WhatsApp(wa_path, names) if settings.enable_whatsapp and present(wa_path) else None
    return imessage, whatsapp


def connector_status(settings: Settings, mac_available: bool, tools: dict[str, Tool],
                     notes: dict[str, str] | None = None) -> list[dict]:
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
            "note": (notes or {}).get(c["id"]) if available else "Needs macOS",
        })
    return out


def candidates(tools: dict[str, Tool], intent: str) -> list[Tool]:
    return [t for t in tools.values() if intent in t.intents]
