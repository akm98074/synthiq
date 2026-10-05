# LocalAIAgent

A personal AI agent in the spirit of Meta Muse and Instinct that runs **entirely on your Mac**: local small language models through [Ollama](https://ollama.com), local memory in SQLite, and a fast **Jev-style decision layer** that makes the first call on every message.

The research, feasibility matrix and roadmap are in [`docs/PLAN.md`](docs/PLAN.md). How to test this step: [`TESTING.md`](TESTING.md). Upgrading: [`UPGRADING.md`](UPGRADING.md).

## Status: Step 2 (v0.2.0) — connectors and approvals

| Included | Comes later |
|---|---|
| Chat with streaming replies | Proactive nudges, nightly "dream" job (Step 3) |
| Decision layer (intent, memorable?, complexity) with probabilities, latency and an eval harness | Voice (Step 4) |
| Persistent memory, `about-me.md` identity file, edit and forget | Browser and Mac app actions (Step 5) |
| **Connectors**: Calendar, Reminders, Notes, Mail, Contacts, Files, Documents (PDF/Excel) | Telegram / iMessage (Step 6) |
| **Approvals** with risk tiers and scopes; hash-chained **Activity** log | |
| Learning from your corrections; model manager; persona settings | |

## Install (Apple Silicon Mac, 16 GB+)

```bash
bash install.sh localaiagent-0.2.1-py3-none-any.whl   # installs pipx + Ollama via Homebrew, pulls models
localagent start                                     # opens http://127.0.0.1:8765
```

Manual install:

```bash
brew install pipx ollama
brew services start ollama
pipx install ./localaiagent-0.2.1-py3-none-any.whl
localagent setup     # downloads qwen3:4b, qwen3:1.7b, all-minilm (~4 GB)
localagent start
```

## Commands

| Command | What it does |
|---|---|
| `localagent setup [--agent-name Ari] [--chat-model qwen3:8b]` | Write config, pull models |
| `localagent start [-f] [--no-open]` | Start in the background (or foreground) and open the UI |
| `localagent stop` / `status` | Manage the background server |
| `localagent doctor` | Check Ollama, models, RAM, data directory |
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
pytest                                   # uses a fake Ollama server, no models needed
python tests/fake_ollama.py --port 11500 # run the fake server for UI work
python -m build                          # → dist/localaiagent-*.whl
```
