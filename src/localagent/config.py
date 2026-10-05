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
        return self

    def to_dict(self) -> dict:
        return asdict(self)


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
