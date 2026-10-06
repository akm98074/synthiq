"""Secrets (OAuth tokens, API keys) kept out of the config file and away from the model.

macOS: the login Keychain (via `keyring`), service "LocalAIAgent". You can see and delete
the items in Keychain Access. Elsewhere, when no system keyring is available, a file in
the data folder readable only by you (mode 0600) is used, and `backend` says so.

Tools and the model only ever see "connected / not connected", never the values.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "LocalAIAgent"


class Vault:
    def __init__(self, base: Path, use_keyring: bool = True):
        self.file = base / "secrets.json"
        self._kr = None
        if use_keyring and not os.environ.get("LOCALAGENT_NO_KEYRING"):
            try:
                import keyring
                from keyring.backends import fail

                if not isinstance(keyring.get_keyring(), fail.Keyring):
                    self._kr = keyring
            except Exception:  # noqa: BLE001 - no usable keyring: fall back to the file
                self._kr = None

    @property
    def backend(self) -> str:
        return "Keychain" if self._kr is not None else f"file ({self.file})"

    def _read(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        tmp.replace(self.file)

    def get(self, name: str) -> str | None:
        if self._kr is not None:
            try:
                return self._kr.get_password(SERVICE, name)
            except Exception as exc:  # noqa: BLE001
                log.warning("Keychain read failed for %s: %s", name, exc)
                return None
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        if self._kr is not None:
            self._kr.set_password(SERVICE, name, value)
            return
        data = self._read()
        data[name] = value
        self._write(data)

    def delete(self, name: str) -> None:
        if self._kr is not None:
            try:
                self._kr.delete_password(SERVICE, name)
            except Exception:  # noqa: BLE001 - already gone
                pass
            return
        data = self._read()
        if data.pop(name, None) is not None:
            self._write(data)

    def has(self, name: str) -> bool:
        return bool(self.get(name))
