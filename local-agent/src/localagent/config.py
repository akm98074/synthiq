"""Settings, persisted as JSON in the per-user data directory.

macOS: ~/Library/Application Support/LocalAIAgent
Override with the LOCALAGENT_HOME environment variable (used by tests).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

import platformdirs

DECISION_BACKENDS = ("hybrid", "prototype", "slm", "systemone")
# Highest tool tier each trust preset allows (tools above it are refused, whatever is approved).
AUTONOMY = {"observer": "read", "assistant": "draft", "agent": "danger"}


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

    # Gmail (Step 7b): your own Google OAuth client; tokens live in the Keychain
    enable_gmail: bool = True
    gmail_client_id: str = ""
    gmail_account: str = ""

    # Cloud escalation (Step 7c): off unless you add your own Anthropic API key and turn it on
    cloud_enabled: bool = False
    cloud_model: str = "claude-opus-5-5"
    cloud_effort: str = "high"          # low | medium | high | xhigh | max
    cloud_auto_hard: bool = False       # also offer it for the hardest questions (complexity 5)
    cloud_send_memories: bool = True

    # Trusted agents (Step 7e): off unless you turn it on
    a2a_enabled: bool = False
    a2a_host: str = "0.0.0.0"           # where the agent-to-agent listener listens (e.g. a Tailscale IP)
    a2a_port: int = 8766
    a2a_public_addr: str = ""           # how friends reach you; empty: http://<this Mac's LAN address>:port

    # Phone line (Step 7f): call your agent through Twilio (off unless set up)
    phone_enabled: bool = False
    phone_owner_numbers: str = ""       # your phone number(s), E.164, comma-separated
    phone_public_url: str = ""          # the public https URL your tunnel gives (Twilio calls it)
    phone_port: int = 8767              # local port the tunnel points at (127.0.0.1 only)

    # iMessage channel (Step 6): talk to the agent from your phone
    enable_imessage_channel: bool = False
    imessage_channel_mode: str = "self"        # self (text yourself) | account (agent's own Apple ID)
    imessage_owner_handles: str = ""           # your phone number(s) / Apple ID email(s), comma-separated
    imessage_forward_nudges: bool = True

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
    avatar_enabled: bool = False        # a face that talks: replies play in the browser with lip-sync
    wake_word_enabled: bool = False     # "Hey <agent name>" while the app is open
    wake_phrases: str = ""              # extra phrases, comma-separated
    wake_model: str = "mlx-community/whisper-tiny.en-mlx"
    # Trust center
    paused: bool = False                # everything stops except answering you in the app (read-only)
    autonomy: str = "agent"             # observer: look only · assistant: + drafts · agent: + actions you approve

    def update(self, values: dict) -> "Settings":
        """Apply and validate on a copy first, so a rejected update leaves nothing half-applied."""
        trial = replace(self)
        trial._apply(values)
        trial._validate()
        for f in fields(self):
            setattr(self, f.name, getattr(trial, f.name))
        return self

    def _apply(self, values: dict) -> None:
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

    def _validate(self) -> None:
        if self.decision_backend not in DECISION_BACKENDS:
            raise ValueError(f"decision_backend must be one of {DECISION_BACKENDS}")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if not 1 <= self.max_tool_steps <= 20:
            raise ValueError("max_tool_steps must be between 1 and 20")
        for name in ("brief_time", "dream_time", "quiet_start", "quiet_end"):
            if not _valid_hhmm(getattr(self, name)):
                raise ValueError(f"{name} must be a time like 08:00")
        if self.cloud_effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ValueError("cloud_effort must be low, medium, high, xhigh or max")
        if self.autonomy not in AUTONOMY:
            raise ValueError(f"autonomy must be one of {', '.join(AUTONOMY)}")
        if self.imessage_channel_mode not in ("account", "self"):
            raise ValueError("imessage_channel_mode must be account or self")
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

    def to_dict(self) -> dict:
        return asdict(self)


# Changing these can expose your data or let someone else act through the agent, so the app
# asks you to confirm each change (with this text) and records it in Activity.
SENSITIVE_SETTINGS = {
    "browser_executable": "The browser program the agent starts. Any program set here will be run.",
    "ollama_url": "Where every prompt goes, including your memories and messages. Anything other than "
                  "this computer sends them over the network.",
    "host": "Which network address the app listens on. Anything other than 127.0.0.1 exposes it to your network.",
    "skills_require_sandbox": "Turning this off lets custom skill scripts run without a sandbox, with "
                              "full access to your files.",
    "imessage_owner_handles": "Who may give the agent orders by iMessage.",
    "enable_imessage_channel": "Lets the agent be controlled by iMessage.",
    "phone_enabled": "Lets the agent answer phone calls (speech passes through Twilio).",
    "phone_owner_numbers": "Which phone numbers may call the agent.",
    "phone_public_url": "The public address calls arrive at.",
    "a2a_enabled": "Lets friends' agents contact this computer over the network.",
    "a2a_host": "Which network address friends' agents connect to.",
    "a2a_public_addr": "The address friends' agents are told to use.",
    "cloud_enabled": "Lets questions be sent to the cloud model (each still needs your OK).",
    "cloud_auto_hard": "Offers the cloud model for every hard question.",
    "cloud_send_memories": "Includes your memories in what's sent to the cloud model.",
    "screen_context_enabled": "Lets the agent read your screen every few minutes.",
}
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def sensitive_changes(old: "Settings", values: dict) -> dict:
    """{key: (old, new)} for sensitive settings this update would actually change (and make riskier)."""
    out = {}
    for key, new in values.items():
        if key not in SENSITIVE_SETTINGS or not hasattr(old, key):
            continue
        before = getattr(old, key)
        trial = replace(old)
        trial._apply({key: new})
        after = getattr(trial, key)
        if after == before:
            continue
        if key == "ollama_url" and any(f"//{h}" in str(after) for h in LOCAL_HOSTS):
            continue                                   # pointing back at this computer is never riskier
        if key == "skills_require_sandbox" and after:
            continue
        if isinstance(after, bool) and not after:
            continue                                   # switching something off is never riskier
        out[key] = (before, after)
    return out


def _valid_hhmm(value: str) -> bool:
    try:
        h, m = value.split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except ValueError:
        return False


def config_path(base: Path | None = None) -> Path:
    return (base or data_dir()) / "config.json"


# A new install starts with the connectors that read other people's words or act in your apps
# switched off; you turn them on in the Trust center when you want them. Upgrades keep your
# saved choices (config.json stores every setting).
FIRST_RUN_OFF = ("enable_messages", "enable_whatsapp", "enable_mail", "enable_contacts", "enable_apps")


def load_settings(base: Path | None = None) -> Settings:
    path = config_path(base)
    settings = Settings()
    if not path.exists():
        settings.update({k: False for k in FIRST_RUN_OFF})
        return settings
    try:
        saved = json.loads(path.read_text())
    except (ValueError, json.JSONDecodeError):
        return settings
    try:
        settings.update(saved)
    except ValueError:
        for key, value in saved.items():        # keep every valid saved value, drop only the bad one
            try:
                settings.update({key: value})
            except (ValueError, TypeError):
                pass
    return settings


def save_settings(settings: Settings, base: Path | None = None) -> Path:
    path = config_path(base)
    path.write_text(json.dumps(settings.to_dict(), indent=2))
    return path
