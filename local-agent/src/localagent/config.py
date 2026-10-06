"""Settings, persisted as JSON in the per-user data directory.

macOS: ~/Library/Application Support/LocalAIAgent
Override with the LOCALAGENT_HOME environment variable (used by tests).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import platformdirs

DECISION_BACKENDS = ("hybrid", "prototype", "slm", "systemone")


def data_dir() -> Path:
    override = os.environ.get("LOCALAGENT_HOME")
    path = Path(override) if override else Path(
        platformdirs.user_data_dir("LocalAIAgent", appauthor=False)
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # Runtime
    ollama_url: str = "http://127.0.0.1:11434"
    host: str = "127.0.0.1"
    port: int = 8765

    # Models (Ollama tags)
    chat_model: str = "qwen3:4b"
    fast_model: str = "qwen3:1.7b"
    embed_model: str = "all-minilm"

    # Persona
    agent_name: str = "Ari"
    tone: str = "warm, concise and practical"
    user_name: str = ""

    # Decision layer
    decision_backend: str = "hybrid"
    confidence_threshold: float = 0.6
    prototype_temperature: float = 30.0
    systemone_url: str = "http://127.0.0.1:8000"

    # Memory
    memory_top_k: int = 5
    memory_min_similarity: float = 0.35

    # Connectors (Step 2). macOS ones use AppleScript and ask for permission on first use.
    enable_calendar: bool = True
    enable_reminders: bool = True
    enable_notes: bool = True
    enable_mail: bool = True
    enable_contacts: bool = True
    enable_files: bool = True
    enable_documents: bool = True
    file_roots: str = "~/Downloads,~/Desktop,~/Documents"
    documents_dir: str = "~/Documents/LocalAIAgent"
    max_tool_steps: int = 5
    calendar_backend: str = "auto"   # auto | eventkit | applescript

    # Messages (Step 5a). Reading needs Full Disk Access for Terminal.
    enable_messages: bool = True
    enable_whatsapp: bool = True
    messages_include_groups: bool = False
    imessage_db: str = "~/Library/Messages/chat.db"
    whatsapp_db: str = "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
    addressbook_dir: str = "~/Library/Application Support/AddressBook"

    # Browser and skills (Step 5b)
    enable_browser: bool = True
    browser_headless: bool = False     # show the window so you can watch and take over
    browser_executable: str = ""       # empty: the installed Google Chrome
    browser_show_actions: bool = True  # cursor, highlight and labels in the agent's window
    browser_action_delay_ms: int = 600
    enable_web_search: bool = True
    enable_skills: bool = True
    skills_require_sandbox: bool = True

    # Mac apps, screen context (Step 5c)
    enable_apps: bool = True
    screen_context_enabled: bool = False    # opt-in
    screen_every_minutes: int = 5
    screen_retention_minutes: int = 120
    screen_blocklist: str = ("1Password,Bitwarden,LastPass,Dashlane,Keychain Access,Passwords,Messages,"
                             "WhatsApp,Signal,FaceTime")

    # Proactivity (Step 3)
    proactive_enabled: bool = True
    brief_time: str = "08:00"
    dream_time: str = "03:00"
    check_every_minutes: int = 30
    quiet_start: str = "22:00"
    quiet_end: str = "07:30"
    max_nudges_per_day: int = 6
    followup_days: int = 7
    notify_macos: bool = True

    # Voice (Step 4)
    voice_enabled: bool = True
    stt_model: str = "mlx-community/whisper-large-v3-turbo"
    tts_voice: str = ""
    tts_rate: int = 190
    speak_replies: bool = True

    def update(self, values: dict) -> "Settings":
        known = {f.name: f.type for f in fields(self)}
        for key, value in values.items():
            if key not in known:
                continue
            current = getattr(self, key)
            if isinstance(current, bool):
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            elif isinstance(current, int):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            else:
                value = str(value)
            setattr(self, key, value)
        if self.decision_backend not in DECISION_BACKENDS:
            raise ValueError(f"decision_backend must be one of {DECISION_BACKENDS}")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if not 1 <= self.max_tool_steps <= 20:
            raise ValueError("max_tool_steps must be between 1 and 20")
        for name in ("brief_time", "dream_time", "quiet_start", "quiet_end"):
            if not _valid_hhmm(getattr(self, name)):
                raise ValueError(f"{name} must be a time like 08:00")
        if self.calendar_backend not in ("auto", "eventkit", "applescript"):
            raise ValueError("calendar_backend must be auto, eventkit or applescript")
        if not 5 <= self.check_every_minutes <= 720:
            raise ValueError("check_every_minutes must be between 5 and 720")
        if not 0 <= self.browser_action_delay_ms <= 3000:
            raise ValueError("browser_action_delay_ms must be between 0 and 3000")
        if not 1 <= self.screen_every_minutes <= 120:
            raise ValueError("screen_every_minutes must be between 1 and 120")
        if not 5 <= self.screen_retention_minutes <= 1440:
            raise ValueError("screen_retention_minutes must be between 5 and 1440")
        if not 80 <= self.tts_rate <= 400:
            raise ValueError("tts_rate must be between 80 and 400")
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def _valid_hhmm(value: str) -> bool:
    try:
        h, m = value.split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except ValueError:
        return False


def config_path(base: Path | None = None) -> Path:
    return (base or data_dir()) / "config.json"


def load_settings(base: Path | None = None) -> Settings:
    path = config_path(base)
    settings = Settings()
    if path.exists():
        try:
            settings.update(json.loads(path.read_text()))
        except (ValueError, json.JSONDecodeError):
            pass
    return settings


def save_settings(settings: Settings, base: Path | None = None) -> Path:
    path = config_path(base)
    path.write_text(json.dumps(settings.to_dict(), indent=2))
    return path
