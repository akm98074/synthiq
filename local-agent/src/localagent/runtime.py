"""Wires settings, storage, the model client and the decision layer together."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .config import Settings, data_dir, save_settings
from .decide.prototype import PrototypeClassifier, seed_store
from .decide.router import DecisionRouter
from .decide.slm_judge import SLMJudge
from .decide.systemone import SystemOneClient
from .llm.ollama import OllamaClient
from .memory import identity
from .memory.store import Store
from .connectors.applescript import AppleScriptRunner
from .connectors.browser import PlaywrightBrowser, find_chrome
from .connectors.eventkit import EventKitCalendar
from .connectors.forms import form_tools
from .connectors.gmail import GmailAuth, GmailClient, GoogleEndpoints, gmail_tools
from .vault import Vault
from .connectors.screen import ScreenContext
from .policy.engine import Audit, Policy
from .tools.registry import build_tools, connector_status
from .proactive.nudges import Nudges
from .proactive.scheduler import Scheduler
from .voice.stt import MLXWhisper
from .voice.tts import SayTTS


class Runtime:
    def __init__(self, settings: Settings, base: Path | None = None, runner=None,
                 stt=None, tts=None, clock: Callable[[], float] = time.time, eventkit=None, browser=None,
                 screen_capture=None, screen_ocr=None, screen_permission=None, web_fetch=None, wake_stt=None,
                 vault=None, google=None, cloud_base_url=None):
        self.base = base or data_dir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.store = Store(self.base / "localagent.db")
        seed_store(self.store)
        self.runner = runner or AppleScriptRunner()
        self.mac_available = runner is not None or AppleScriptRunner.available()
        # Real EventKit only when the real AppleScript runner is in use (never in tests
        # that inject a fake runner, which would otherwise read the machine's calendars).
        self.eventkit = eventkit if eventkit is not None else (
            EventKitCalendar() if runner is None and AppleScriptRunner.available() else None)
        self.browser = browser if browser is not None else PlaywrightBrowser(
            self.base / "browser-profile", settings.browser_headless, settings.browser_executable,
            settings.browser_show_actions, settings.browser_action_delay_ms, settings.agent_name)
        self.skills_dir = self.base / "skills"
        self.web_fetch = web_fetch
        self.vault = vault if vault is not None else Vault(self.base)
        self.google = google or GoogleEndpoints()
        self.cloud_base_url = cloud_base_url      # tests point this at a fake API
        self.gmail = GmailClient(self.vault, self.google, settings.gmail_client_id)
        self.gmail_auth = GmailAuth(self.vault, self.google, settings.gmail_client_id)
        extra = {k: v for k, v in (("capture", screen_capture), ("ocr", screen_ocr),
                                   ("permission", screen_permission)) if v is not None}
        self.screen = ScreenContext(self.store, self.runner, settings.screen_blocklist,
                                    settings.screen_retention_minutes, clock=clock, **extra)
        from .connectors.peers import Peers

        self.peers = Peers(self)
        self._a2a = None
        self._a2a_lifecycle = False   # set by the server: only then does a settings change (re)start it
        self.policy = Policy(self.store)
        self.audit = Audit(self.store)
        self.build_tools()
        self.clock = clock
        self.nudges = Nudges(self.store, settings,
                             notifier=self.notify if self.mac_available else None, clock=clock)
        self.scheduler = Scheduler(self.store, clock)
        from .channels.imessage import IMessageChannel
        from .tools.registry import message_sources

        self.imessage_channel = IMessageChannel(self, message_sources(settings)[0], self.runner)
        if self.mac_available:
            self.nudges.forwarders.append(self.imessage_channel.forward)
        self.stt = stt or MLXWhisper(settings.stt_model)
        self.wake_stt = wake_stt or (stt if stt is not None else MLXWhisper(settings.wake_model))
        self.tts = tts or SayTTS(settings.tts_voice, settings.tts_rate)
        self.identity_path = self.base / "identity" / "about-me.md"
        self.ollama = OllamaClient(settings.ollama_url)
        self._build_decision_layer()
        if not self.identity_path.exists():
            self.write_identity()
        self.register_jobs()

    def register_jobs(self) -> None:
        from .proactive.jobs import job_specs  # local import: jobs imports the chat agent

        self.scheduler.register(job_specs(self))
        self.scheduler.enabled = self.settings.proactive_enabled

    async def notify(self, title: str, subtitle: str, body: str) -> None:
        await self.runner.run("notify", [title, body, subtitle])

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
        tools = build_tools(self.settings, self.runner, self.mac_available, self.eventkit,
                            self.browser, self.skills_dir, self.screen, self.web_fetch)
        if self.settings.enable_browser:
            tools.update({t.name: t for t in form_tools(self)})
        if self.settings.a2a_enabled:
            from .connectors.peers import peer_tools

            tools.update({t.name: t for t in peer_tools(self.peers)})
        if self.settings.enable_gmail and self.gmail.connected():
            tools.update({t.name: t for t in gmail_tools(self.gmail)})
        self.tools = tools

    def connectors(self) -> list[dict]:
        self.build_tools()   # picks up skills added or edited since the last look
        notes = {}
        if isinstance(self.browser, PlaywrightBrowser):
            if not self.browser.installed():
                notes["browser"] = "Needs the browser add-on: pipx inject localaiagent playwright"
            elif find_chrome(self.settings.browser_executable) is None:
                notes["browser"] = "Google Chrome not found: install it from google.com/chrome"
        if self.settings.enable_gmail and not self.gmail.connected():
            notes["gmail"] = "Not connected: Settings → Gmail → Connect Gmail"
        if self.settings.enable_skills and not any(t.connector == "skills" for t in self.tools.values()):
            notes["skills"] = f"No skills yet. Folder: {self.skills_dir}"
        return connector_status(self.settings, self.mac_available, self.tools, notes)

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
        self.register_jobs()
        from .tools.registry import message_sources

        self.imessage_channel.store = message_sources(self.settings)[0]
        if hasattr(self.stt, "model"):
            self.stt.model = self.settings.stt_model
        if isinstance(self.wake_stt, MLXWhisper) and self.wake_stt is not self.stt:
            self.wake_stt.model = self.settings.wake_model
        self.gmail.client_id = self.gmail_auth.client_id = self.settings.gmail_client_id
        if self._a2a_lifecycle and (self.settings.a2a_enabled != (self._a2a is not None)
                                    or self.settings.a2a_enabled):
            await self.start_a2a()
        if self._a2a_lifecycle:
            await self.start_phone()
        self.screen.blocklist = {x.strip().lower() for x in self.settings.screen_blocklist.split(",") if x.strip()}
        self.screen.retention = self.settings.screen_retention_minutes * 60
        if not self.settings.screen_context_enabled:
            self.screen.forget_all()
        if isinstance(self.browser, PlaywrightBrowser):
            self.browser.headless = self.settings.browser_headless
            self.browser.executable = self.settings.browser_executable
            self.browser.show_actions = self.settings.browser_show_actions
            self.browser.action_delay_ms = self.settings.browser_action_delay_ms
            self.browser.agent_name = self.settings.agent_name
        if isinstance(self.tts, SayTTS):
            self.tts.voice, self.tts.rate = self.settings.tts_voice, self.settings.tts_rate
        return self.settings

    async def start_a2a(self) -> None:
        """Run the agent-to-agent listener (only while trusted agents are switched on)."""
        await self.stop_a2a()
        if not self.settings.a2a_enabled:
            return
        import asyncio

        import uvicorn

        from .connectors.peers_server import a2a_app

        server = uvicorn.Server(uvicorn.Config(a2a_app(self), host=self.settings.a2a_host,
                                               port=self.settings.a2a_port, log_level="warning"))
        server.install_signal_handlers = lambda: None
        self._a2a = (server, asyncio.create_task(server.serve()))

    async def start_phone(self) -> None:
        """The phone webhook listener: 127.0.0.1 only; your tunnel forwards Twilio to it."""
        await self.stop_phone()
        if not self.settings.phone_enabled:
            return
        import asyncio

        import uvicorn

        from .channels.phone import phone_app

        server = uvicorn.Server(uvicorn.Config(phone_app(self), host="127.0.0.1", port=self.settings.phone_port,
                                               log_level="warning", proxy_headers=False))
        server.install_signal_handlers = lambda: None
        self._phone = (server, asyncio.create_task(server.serve()))

    async def stop_phone(self) -> None:
        if getattr(self, "_phone", None) is not None:
            server, task = self._phone
            server.should_exit = True
            try:
                await task
            except Exception:  # noqa: BLE001
                pass
        self._phone = None

    async def stop_a2a(self) -> None:
        if self._a2a is not None:
            server, task = self._a2a
            server.should_exit = True
            try:
                await task
            except Exception:  # noqa: BLE001
                pass
            self._a2a = None

    async def aclose(self) -> None:
        await self.stop_a2a()
        await self.stop_phone()
        try:
            await self.browser.close()
        except Exception:  # noqa: BLE001 - closing a browser that already went away
            pass
        await self.ollama.aclose()
        self.store.close()
