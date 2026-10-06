# LocalAIAgent

A personal AI agent in the spirit of Meta Muse and Instinct that runs **entirely on your Mac**: local small language models through [Ollama](https://ollama.com), local memory in SQLite, and a fast **Jev-style decision layer** that makes the first call on every message.

The research, feasibility matrix and roadmap are in [`docs/PLAN.md`](docs/PLAN.md). Product-level documents (also as PDFs in `docs/pdf/`): [design overview and Muse/Instinct comparison](docs/OVERVIEW.md), [trust and control UX](docs/TRUST_UX.md), [security and privacy review](docs/SECURITY_REVIEW.md), [product roadmap](docs/PRODUCT_ROADMAP.md). How the system works, including which models produce the decision probabilities, is in [`docs/DESIGN.md`](docs/DESIGN.md). How to test this step: [`TESTING.md`](TESTING.md). Upgrading: [`UPGRADING.md`](UPGRADING.md).

## Status: Step 7g (v0.15.0) — Windows and Linux

| Included | Comes later |
|---|---|
| Chat with streaming replies | Further work: see `docs/PLAN.md` |
| Decision layer (intent, memorable?, complexity; should-nudge, urgency) with probabilities and an eval harness | |
| Persistent memory, `about-me.md` identity file, edit and forget | |
| **Connectors**: Calendar, Reminders, Notes, Mail, Contacts, Files, Documents (PDF/Excel) | |
| **Approvals** with risk tiers and scopes; hash-chained **Activity** log | |
| **Proactivity**: morning brief, nudges (events, reminders, unreplied mail), quiet hours, overnight memory review | |
| **Voice**: push-to-talk, conversation mode, on-device Whisper, spoken replies | |
| **Messages**: read iMessage/SMS and WhatsApp, chats waiting on your reply, iMessage replies (approved), WhatsApp replies typed in for you | |
| **Phone line** (Twilio, optional): call your agent; look-ups and drafts by voice, nothing sent by phone | |
| **Trusted agents**: pair with a friend's agent by invite code; end-to-end encrypted; free/busy (if allowed), messages, questions you answer | |
| **Avatar**: a face that speaks the replies, mouth in sync with the voice; 🔊 read-aloud on any reply | |
| **Optional cloud model** (your own Anthropic key): "think harder" sends one question to Claude after you approve exactly what's sent | |
| **Gmail** directly (sign in with Google): search, read, follow-ups, drafts, send; secrets in the Keychain | |
| **Wake word**: say "Hey Ari, …" while the app is open | |
| **iMessage channel**: text the agent from your iPhone, approve actions by replying "yes", get nudges and the brief as texts | |
| **Prompt-injection guard** on mail, chat and web content | |
| **Web look-ups**: prices, shops, restaurants, hours and news are searched (DuckDuckGo) and read from the source page, never answered from memory | |
| **Browser**: the agent's own Chrome window; read pages, click, fill in, search. Submitting, booking or paying asks every time | |
| **Custom skills**: your own SKILL.md folders, scripts sandboxed (`localagent skill new NAME`) | |
| **Mac apps & Shortcuts**: open apps, read and press their buttons, type, run your Shortcuts (pressing asks first) | |
| **Form filling from memory** in the agent's browser; you review, nothing is submitted for you | |
| **Screen context** (opt-in): on-device OCR of your screen, private apps skipped, forgotten after 2 hours | |
| Learning from your corrections; model manager; persona settings | |
| **Windows and Linux**: everything except the Apple apps (Calendar, Contacts, Messages, Mail, Notes, Reminders, Mac apps, screen context) | |

## Install (Apple Silicon Mac, 16 GB+; Windows and Linux below)

```bash
bash install.sh localaiagent-0.15.0-py3-none-any.whl
localagent start
```

The installer adds pipx and Ollama with Homebrew and downloads the models. The app opens at http://127.0.0.1:8765.

Manual install:

```bash
brew install pipx ollama
brew services start ollama
pipx install ./localaiagent-0.15.0-py3-none-any.whl
localagent setup
localagent start
```

### Windows 10/11 and Linux

Windows, in a normal (not Administrator) PowerShell window, in the folder with the files:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 localaiagent-0.15.0-py3-none-any.whl
localagent start
```

It installs Python, pipx and Ollama with winget. Linux (Ubuntu, Debian, Fedora) uses the same `install.sh` as the Mac; it installs pipx with apt/dnf and Ollama with its official installer.

Available there: chat, memory, decisions, Files, Documents, Gmail, web look-ups, the browser (your Chrome), custom skills (Linux: sandboxed with bubblewrap; Windows: not yet), cloud model, avatar, trusted agents, phone line, voice (faster-whisper; speech via Windows voices or eSpeak) and desktop notifications. The Apple apps (Calendar, Contacts, Mail, Notes, Reminders, Messages, Mac apps & Shortcuts, screen context) need a Mac. Data lives in `%LOCALAPPDATA%\LocalAIAgent` (Windows) or `~/.local/share/LocalAIAgent` (Linux).

## Commands

| Command | What it does |
|---|---|
| `localagent setup [--agent-name Ari] [--chat-model qwen3:8b]` | Write config, pull models |
| `localagent start [-f] [--no-open]` | Start in the background (or foreground) and open the UI |
| `localagent stop` / `status` | Manage the background server |
| `localagent doctor` | Check Ollama, models, RAM, data directory |
| `localagent setup --voice` | Download the speech-recognition model |
| `localagent setup --browser` | Start the agent's Chrome once and report whether it works |
| `localagent phone setup` | Save your Twilio auth token and print the steps to connect a number |
| `localagent cloud-key` | Save your Anthropic API key (Keychain) for the optional cloud model |
| `localagent gmail-login` | Connect Gmail (asks for your Google OAuth client, then opens Google's sign-in) |
| `localagent channel test` | Send a test iMessage from the agent to your phone |
| `localagent screen-access` | Ask macOS for Screen Recording permission (for screen context) |
| `localagent skill new NAME` / `skill list` | Create a custom skill from a template / list skills and problems |
| `localagent autostart on\|off\|status` | Start the agent at login (optional) |
| `localagent eval decision [--file my.jsonl] [--backend hybrid\|prototype\|slm\|systemone]` | Phase-0 gate: accuracy, macro-F1, calibration (ECE), latency |

Data lives in `~/Library/Application Support/LocalAIAgent/` (database, `identity/about-me.md`, config, logs, eval reports). The server binds to `127.0.0.1` only.

## How the decision layer works

Every message is turned into typed questions — `choice` (intent), `noul` (does it contain something to remember?), `score` (complexity 1–5) — answered with probabilities in one pass:

1. **Prototype classifier** (default, ~5–30 ms): the message is embedded with a small embedding model and compared to labelled examples; a temperature-scaled softmax gives probabilities. Your corrections in the Decisions tab become new examples immediately.
2. **SLM judge** (escalation): if a gating answer is below the confidence threshold, `qwen3:1.7b` answers the same questions with JSON-schema-constrained output.
3. **System-One server** (experimental): point it at a local Jev-style decision server (e.g. Ollaya or `von serve`) in Settings. Falls back to the built-in path on any error.

The router then picks the model (fast model for chit-chat, main model for real work), saves memories when needed, recalls relevant ones, and streams the reply.

## How actions work

`schedule` and `computer_action` messages, and `task` messages that mention something a connector can touch, go through a tool loop. The model calls tools through Ollama's native tool calling, and arguments are validated against each tool's schema. The **policy engine** (not the model) checks the tool's risk tier:

| Tier | Examples | Behaviour |
|---|---|---|
| read | list calendar, search mail/files/notes | runs automatically |
| draft | open a Mail draft, create a note/PDF/spreadsheet | runs automatically, logged |
| write | create event/reminder, send mail, move files | asks; you choose once / this request / until restart / 1 h / 24 h / always |
| danger | move to Trash | asks every time |

Apple apps are driven with bundled AppleScripts run through `osascript`. Arguments go in as argv, never spliced into script text. Every call, approval and refusal is appended to a SHA-256 hash-chained audit log (`/api/audit/verify`).

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
python tests/fake_ollama.py --port 11500 # run the fake server for UI work
python -m build
```
