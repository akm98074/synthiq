"""Wires settings, storage, the model client and the decision layer together."""
from __future__ import annotations

from pathlib import Path

from .config import Settings, data_dir, save_settings
from .decide.prototype import PrototypeClassifier, seed_store
from .decide.router import DecisionRouter
from .decide.slm_judge import SLMJudge
from .decide.systemone import SystemOneClient
from .llm.ollama import OllamaClient
from .memory import identity
from .memory.store import Store
from .connectors.applescript import AppleScriptRunner
from .policy.engine import Audit, Policy
from .tools.registry import build_tools, connector_status


class Runtime:
    def __init__(self, settings: Settings, base: Path | None = None, runner=None):
        self.base = base or data_dir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.store = Store(self.base / "localagent.db")
        seed_store(self.store)
        self.runner = runner or AppleScriptRunner()
        self.mac_available = runner is not None or AppleScriptRunner.available()
        self.policy = Policy(self.store)
        self.audit = Audit(self.store)
        self.build_tools()
        self.identity_path = self.base / "identity" / "about-me.md"
        self.ollama = OllamaClient(settings.ollama_url)
        self._build_decision_layer()
        if not self.identity_path.exists():
            self.write_identity()

    def _build_decision_layer(self) -> None:
        s = self.settings
        self.prototype = PrototypeClassifier(
            self.store, self.embed, s.embed_model, temperature=s.prototype_temperature
        )
        self.judge = SLMJudge(self.ollama, s.fast_model)
        self.systemone = SystemOneClient(s.systemone_url)
        self.router = DecisionRouter(
            self.store, self.prototype, self.judge, self.systemone,
            backend=s.decision_backend, threshold=s.confidence_threshold,
        )

    def build_tools(self) -> None:
        self.tools = build_tools(self.settings, self.runner, self.mac_available)

    def connectors(self) -> list[dict]:
        return connector_status(self.settings, self.mac_available, self.tools)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.ollama.embed(self.settings.embed_model, texts)

    async def reembed_memories(self) -> int:
        missing = self.store.memories_missing_embedding(self.settings.embed_model)
        if not missing:
            return 0
        vecs = await self.embed([m["text"] for m in missing])
        for row, vec in zip(missing, vecs):
            self.store.update_memory(row["id"], embedding=vec, embed_model=self.settings.embed_model)
        return len(missing)

    def write_identity(self) -> str:
        return identity.write(self.store, self.identity_path, self.settings.agent_name)

    async def apply_settings(self, values: dict) -> Settings:
        old_url = self.settings.ollama_url
        self.settings.update(values)
        save_settings(self.settings, self.base)
        if self.settings.ollama_url != old_url:
            await self.ollama.aclose()
            self.ollama = OllamaClient(self.settings.ollama_url)
        self._build_decision_layer()
        self.build_tools()
        return self.settings

    async def aclose(self) -> None:
        await self.ollama.aclose()
        self.store.close()
