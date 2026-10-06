# LocalAIAgent: design document

**Version:** 0.6.0 (Steps 1–4 of 7) · **Platform:** Apple Silicon Mac, 16 GB+ · **Companion docs:** [`PLAN.md`](PLAN.md) (research, feasibility, roadmap), [`../UPGRADING.md`](../UPGRADING.md), [`../TESTING.md`](../TESTING.md)

---

## 1. Purpose and principles

LocalAIAgent is a personal agent in the style of Meta Muse and Instinct that runs entirely on the user's Mac. It chats, remembers, acts on Calendar, Reminders, Notes, Mail, Contacts and files, reaches out on its own, and talks.

| Principle | What it means in the code |
|---|---|
| **Local-first** | All models run on the Mac (Ollama, mlx-whisper, macOS `say`). All data is in one SQLite file plus one Markdown file. The server binds to `127.0.0.1` only. |
| **Decide first, generate second** | A fast, Jev-style decision layer (no text generation) answers typed questions about every input before any large model runs. It routes the work, picks the model size, and decides whether to interrupt. |
| **Policy over model** | The model proposes actions; a deterministic policy engine decides whether they run, from each tool's declared risk tier. A model can't approve its own action. |
| **Everything visible** | Every decision shows its probabilities; every action, approval and refusal goes into a hash-chained audit log; memory can be read, edited and forgotten as a plain file. |
| **Learn from corrections** | A corrected decision becomes a training example immediately; no retraining step. |

---

## 2. Architecture

```
 Browser UI (http://127.0.0.1:8765, vanilla JS, no build step)
   Chat · Nudges · Approvals · Activity · Connectors · Decisions · Memory · Models · Settings
   mic → Web Audio → 16 kHz WAV                     SSE (server-sent events) ← replies, tool chips, approval cards
            │  HTTP / JSON                                           ▲
            ▼                                                        │
 ┌────────────────────────── localagent daemon (Python 3.11+, FastAPI/uvicorn) ───────────────────────┐
 │ Runtime                                                                                             │
 │  ├─ DecisionRouter ── PrototypeClassifier (embeddings + kNN softmax)                                 │
 │  │                 └─ SLMJudge (qwen3:1.7b, JSON-schema output)   └─ SystemOneClient (optional)      │
 │  ├─ Chat agent ──── plain reply (streamed)  │  ActionRun tool loop (Ollama native tool calling)      │
 │  ├─ Policy (tiers, approvals, grants) ── Audit (SHA-256 hash chain)                                  │
 │  ├─ Tools: Calendar · Reminders · Notes · Mail · Contacts (AppleScript) · Files · Documents          │
 │  ├─ Memory: SQLite + numpy vector search + identity/about-me.md                                      │
 │  ├─ Scheduler ── jobs: morning brief · checks (30 min) · dream (03:00) ── Nudges (quiet hours, cap)   │
 │  └─ Voice: MLXWhisper (STT) · SayTTS (TTS)                                                           │
 └───────┬──────────────────────────────┬─────────────────────────────────┬────────────────────────────┘
         │ HTTP :11434                  │ osascript - <script> argv…      │ subprocess
         ▼                              ▼                                 ▼
   Ollama (Metal)                 Calendar, Reminders, Notes,        say (speech) · open (files)
   qwen3:4b · qwen3:1.7b ·         Mail, Contacts, Notification
   all-minilm                      Center (Apple apps)
```

- **Process model:** one daemon started with `localagent start`, from Terminal or at login via `localagent autostart on`. macOS attributes Automation permissions to the app that started it, which is why starting from Terminal matters.
- **Code map:** the package is `src/localagent/`:
  - `decide/`: decision layer;
  - `agent/`: chat turn and tool loop;
  - `connectors/` and `tools/`: actions;
  - `policy/`: approvals and audit;
  - `memory/`;
  - `proactive/`;
  - `voice/`;
  - `ui/`;
  - `cli.py`, `server.py`, `runtime.py`.

---

## 3. Model inventory

| Role | Model (default) | Size / RAM | Runtime | Used for | Loaded |
|---|---|---|---|---|---|
| **Embeddings** | `all-minilm` (MiniLM-L6, ~23M params, 384-dim) | ~50 MB | Ollama | **Decision probabilities** (prototype classifier), memory search, dedupe, memory merging | Always (tiny) |
| **Fast model / judge** | `qwen3:1.7b` (4-bit) | ~1.4 GB | Ollama | Decision **escalation** (SLM judge), chit-chat replies, fact extraction, memory-merge judgement | On demand |
| **Main model** | `qwen3:4b` (4-bit) | ~2.6 GB | Ollama | Real answers, tool calling and actions, morning brief | On demand |
| **Speech to text** | Whisper large-v3-turbo (`mlx-community/whisper-large-v3-turbo`) | ~1.6 GB | mlx-whisper (Apple Neural Engine/GPU) | Voice input | On first voice use |
| **Text to speech** | macOS system voices | built in | `say` | Spoken replies | — |
| *Optional decision model* | Laya / von / NeoHorse (Jev-style) | 0.4–4 GB | external server (`systemone` backend) | Single-pass calibrated decisions | If configured |

All are configurable in **Settings** (`chat_model`, `fast_model`, `embed_model`, `stt_model`, `tts_voice`). Ollama unloads idle models, and the **Models** tab shows what's resident and can unload them.

---

## 4. The decision layer: where the probabilities come from

### 4.1 What the chips mean

A message shows chips like **`schedule · 99%`** and **`prototype · 43 ms`**:

- **`schedule · 99%`**: the top intent label and its probability.
- **`prototype · 43 ms`**: which backend decided, and how long the decision took. `prototype` means the embedding classifier alone decided. `prototype+slm` means it wasn't confident enough and `qwen3:1.7b` was asked too.

**The 99% doesn't come from a chat model.** It comes from the **embedding model `all-minilm` plus a nearest-neighbour softmax** computed in numpy. No text is generated.

### 4.2 Typed questions

Every input is turned into typed questions, using the Jev / System-One vocabulary (`decide/types.py`, `decide/questions.py`):

| Set | Question | Type | Labels |
|---|---|---|---|
| Chat (every message) | `intent` | choice | chit_chat, quick_answer, task, schedule, memory_write, memory_query, computer_action |
| | `needs_memory_write` | noul (yes/no) | yes / no |
| | `complexity` | score | 1–5 |
| Nudges (proactive items) | `should_nudge` | noul | yes / no |
| | `urgency` | score | 1–5 |

Every answer is a probability distribution over its labels, so all backends share one representation (`Answer.probs`, `Answer.confidence` = the probability of the top label).

### 4.3 Backend 1: the prototype classifier (default, fast path)

Code: `decide/prototype.py`.

1. **Training data:**
   - `data/seed_examples.jsonl`: 144 labelled chat messages, covering intent, memory and complexity.
   - `data/nudge_seed.jsonl`: 44 labelled email, reminder and event items, covering should_nudge and urgency.
   - Every correction you save in **Decisions**.

   Each example is embedded once with `all-minilm` and cached in SQLite (`examples` table).
2. **At decision time:** the message is embedded once (one Ollama `/api/embed` call) and L2-normalised.
3. For each question and each label, the **score** is the **mean cosine similarity of the 3 nearest examples with that label** (`top_k = 3`).
4. **Probabilities** = `softmax(score × T)`, with temperature **T = 30** (`prototype_temperature`).
5. Cost: one embedding call plus a few matrix products. In the screenshot, 43 ms.

**Worked example, "What is on my calendar?":**
- Its nearest seed examples are "what's on my calendar tomorrow?", "what do I have going on this week?" and "when is my next meeting?". All are labelled `schedule`, with cosine around 0.80–0.90.
- The best label from any other intent scores around 0.45–0.60.
- A gap of ~0.3 × 30 = 9 logits gives e⁹ ≈ 8,000:1, so the softmax puts ~99% on `schedule`.

### 4.4 Backend 2: SLM judge (escalation)

Code: `decide/router.py`, `decide/slm_judge.py`.

- **Trigger:** in the default **`hybrid`** mode, if `intent` or `needs_memory_write` has confidence below **0.6** (`confidence_threshold`). For nudges, the trigger is `should_nudge`.
- **Model:** `qwen3:1.7b` gets a prompt that lists each question with its labels, plus recent conversation. Ollama constrains the output with a **JSON schema whose fields are enums of the allowed labels**, so the answer is always parseable and valid.
- **Probabilities:** the Ollama API doesn't return label likelihoods, so the judge's probabilities are a **blend**: `p(label) = 0.2 × prototype_p(label) + 0.8 × [label == judge's choice]` (`JUDGE_WEIGHT = 0.8`). After escalation, the top label usually shows 80–100%. That number reflects agreement between the two methods; it isn't the model's own likelihood.
- Cost: ~0.3–1.5 s. The chip shows `prototype+slm`.

### 4.5 Backend 3: external Jev-style model (optional, experimental)

- **Setting:** `decision_backend = systemone`.
- Sends the same typed questions to a local System-One–compatible server (e.g. Ollaya with Laya-421M, or `von serve`) at `systemone_url`.
- These models are non-autoregressive encoders trained to output **calibrated probabilities in one forward pass**, which is the closest match to the original "Jev-like" idea.
- If the server is down, or its answer is low-confidence, the router falls back to the built-in hybrid path and records a note on the decision.

### 4.6 Other modes

`prototype`: never escalates; the fastest mode. `slm`: judge only; slowest, used as an evaluation baseline. Switch modes in **Settings → Decision layer**.

### 4.7 Learning from corrections

When you pick a different label in **Decisions** and save it:
- the message text is embedded and stored as a `source='user'` example for that question and label;
- the classifier's cache is cleared, so the next similar message is classified with the correction included.

No fine-tuning is involved, and nothing leaves the Mac.

### 4.8 Calibration and its limits (read before trusting a percentage)

- With **T = 30**, the softmax is **sharp**. Messages that paraphrase a seed example routinely score 95–100%, even when a person might call them ambiguous. Take the percentage as *how strongly this resembles known examples of one label*, not a true probability.
- The real calibration is measured on held-out data: `localagent eval decision` reports accuracy, macro-F1 and **ECE** (expected calibration error) per question on `data/decision_eval.jsonl` (150 rows). The project's gate is intent accuracy ≥ 90% with ECE ≤ 0.05.
- **Planned improvements:**
  - fit T on the eval set (temperature scaling);
  - optionally replace the kNN with a small trained head;
  - or switch to an external calibrated System-One model when one proves itself on your eval.
- `all-minilm` is English-centric and small. A stronger embedding model (e.g. `nomic-embed-text`) improves separation at little cost. The examples re-embed automatically when `embed_model` changes.

### 4.9 How decisions are used

| Decision | Effect |
|---|---|
| `intent` | Picks the path: plain reply; memory write or recall; or the tool loop for `schedule` and `computer_action`, and for `task`/`quick_answer` when they mention a connector (calendar, email, file, PDF …). |
| `needs_memory_write = yes` (or intent `memory_write`) | Runs fact extraction (`qwen3:1.7b`) and saves facts. |
| `complexity` ≤ 2 with chit-chat or memory | Answered by `qwen3:1.7b`; everything else by `qwen3:4b`. |
| `should_nudge`, `urgency` | Whether a proactive item becomes a nudge, and its urgency dots. |

Every decision is logged in the `decisions` table with its probabilities, backend and latency, and shown in **Decisions**.

---

## 5. A chat turn

```
user text
  → store message
  → decide (chat questions)                       → SSE "decision"
  → if memorable: extract facts → dedupe (cos ≥ 0.92 updates) → save → identity file   → "memory_saved"
  → recall: top-5 memories (cos ≥ 0.35; top-10, any score, for memory_query)           → "recalled"
  → if the request needs tools: ActionRun
        tools offered = the enabled tools whose intents include this intent
        loop ≤ 5 steps: qwen3:4b (native tool calls) → validate args (schema) → policy
          read/draft → run → "tool_result" → feed result back
          write/danger without a grant → store paused state → "approval_required" (turn ends)
        final text → "token"
    else: stream reply from qwen3:4b or qwen3:1.7b → "token"…
  → "done"
```

Reasoning text the model leaks (`<think>…</think>`, or a stray closing `</think>` with no opening tag, which Qwen3 sometimes emits) is removed. When streamed text turns out to have been reasoning, a `reset` event clears it from the bubble. Replies are rendered with a minimal markdown renderer that escapes HTML first.

Approving or declining resumes a paused run from its saved state (`/api/approvals/{id}/decide`, streamed): the tool runs, or the model is told it was declined, and the loop continues.

---

## 6. Tools and connectors

| Connector | Tools (tier) | Mechanism |
|---|---|---|
| Calendar | `calendar_list_events` (read), `calendar_create_event` (write) | Listing: **EventKit** (pyobjc; expands repeating events, includes every account, invitation status) with an AppleScript fallback that expands repeating series from their RRULE (`connectors/recurrence.py`, python-dateutil). Creating: AppleScript |
| Reminders | `reminders_list` (read), `reminders_create` (write) | AppleScript |
| Notes | `notes_search` (read), `notes_create` (draft) | AppleScript |
| Mail | `mail_list`, `mail_followups`, `mail_read` (read), `mail_draft` (draft), `mail_send` (write) | AppleScript |
| Contacts | `contacts_find` (read) | AppleScript |
| Files | `files_search`, `files_list` (read), `files_open` (draft), `files_move` (write), `files_trash` (danger) | Python, confined to allowed folders |
| Documents | `documents_create_pdf`, `documents_create_spreadsheet` (draft) | fpdf2, openpyxl |
| Browser | `browser_open` (draft), `browser_read` (read), `browser_click`, `browser_type` (draft), `browser_submit` (danger) | Playwright on a persistent profile in the data folder; Google Chrome (`channel="chrome"`), else Playwright's Chromium |
| Custom skills | `skill_<name>` (tier from SKILL.md; at least write when `network: true`) | Folder with `SKILL.md`; scripts run under `sandbox-exec` |
| Messages | `messages_list`, `messages_read` (read), `whatsapp_open_draft` (draft), `imessage_send` (write) | Read-only SQLite on `chat.db` and WhatsApp's `ChatStorage.sqlite` (Full Disk Access); send via Messages AppleScript; WhatsApp via the `whatsapp://send` link |

- **AppleScript safety:** the scripts are bundled files in `connectors/scripts/` and run with `osascript -`. All arguments are passed as **argv**, never pasted into script text, so model or user text can't inject AppleScript.
- **EventKit:** reads the calendar store directly with `predicateForEventsWithStartDate_endDate_calendars_`, which expands repeating events. The server **only reads** the authorization status (`status_detail()`: ok, not asked yet, access denied, write-only, blocked by policy, not installed) and never prompts from the background, where macOS may not show the dialog. Access is requested in the foreground with `localagent calendar-access`. Setting: `calendar_backend` = auto, eventkit or applescript.
- **AppleScript calendar fallback:** Calendar's `whose start date …` query returns only a series' first occurrence, so repeating meetings that started before the window were missing. `calendar_recurring.applescript` returns each repeating series (start/end as exact local `YYYY-MM-DD HH:MM:SS`, the `recurrence` RRULE text and excluded dates). `recurrence.expand()` runs `rrulestr` over the window, keeps the duration, converts `UNTIL=…Z` to local time, drops excluded dates, skips invalid rules, and caps each series at 500. `merge()` dedupes against the base list by (title, start minute, calendar). The result is labelled e.g. "via AppleScript (EventKit: access denied)".
- **Results** come back as records separated by ASCII control characters, and are parsed into structured data for the UI plus text for the model.
- **Dates:** times cross the boundary as offsets in seconds from "now", which avoids locale-dependent date parsing.
- **Messages (Step 5a, `connectors/messages.py`):**
  - Databases are opened with `mode=ro`. A `PermissionError` or "unable to open" becomes the Full Disk Access instructions.
  - iMessage text on recent macOS lives only in `attributedBody` (an NSArchiver typedstream). `decode_attributed_body()` reads the NSString payload after `+` with its 1-, 2- (`0x81`) or 4-byte (`0x82`) length.
  - Dates are nanoseconds since 2001 (older: seconds). Tapback reactions (`associated_message_type ≠ 0`) aren't treated as the last message.
  - Names come from the Contacts database (`AddressBook-v22.abcddb`), matching the last 10 digits of a phone number or the lower-case email.
  - "Waiting on your reply" means the last message isn't yours. Short-code senders (fewer than 7 digits) are never in that list, and group chats are off by default.
  - WhatsApp's schema is checked before use (`ZWACHATSESSION`, `ZWAMESSAGE` columns). A mismatch reports "WhatsApp changed how it stores chats" instead of guessing.
  - Sending: `messages_send.applescript` tries the chat id (`any;-;…`, `iMessage;-;…`, `SMS;-;…`) and then the participant handle. WhatsApp has no API for personal accounts, so `whatsapp_open_draft` opens `whatsapp://send?phone=…&text=…` and the user presses Send. Groups aren't supported by that link.
- **Prompt-injection guard (`safety/injection.py`):** results marked `untrusted` (mail list/read/follow-ups, chats) are fenced as data and pattern-scanned before the model sees them. A hit adds a warning for the model, a ⚠ on the chip and an `injection_flagged` audit row. It also **taints** the run: `Policy.needs_approval(…, tainted=True)` ignores standing grants, so every write needs a fresh approval, and the card says why. The taint survives a pause for approval because it's stored in the run state. The scan is regex-based (deterministic, can't be argued with), so it reduces risk rather than eliminating it.
- **Browser (Step 5b, `connectors/browser.py`):**
  - The model never sees HTML. `SNAPSHOT_JS` returns title, URL, `innerText` (cut at 6,000 characters) and up to 120 visible interactive elements. Each one is tagged `data-la-ref=N`, and the model acts by that number.
  - `needs_submit()` decides what counts as committing: a label matching buy, pay, order, send, delete, book, subscribe, agree…, or a form-submit button that isn't plainly search/filter/next. `browser_click` refuses those and points to `browser_submit` (danger: approved every time, scope "once" only).
  - `browser_type` refuses password fields. It presses Enter only in search boxes (`type=search`, `role=search`, or a name/placeholder containing search/query/`q`).
  - Only http(s) URLs open; `javascript:`, `file:` and `data:` are rejected. Page content is `untrusted`, so it's fenced and scanned like mail.
  - The latest snapshot is stored on the browser object, so element numbers survive a tool rebuild. The window is visible by default (`browser_headless` off) so the user can watch and take over.
- **Custom skills (`skills.py`):**
  - The SKILL.md header holds name, description, args, run, tier (default write), network (default false) and timeout. Invalid skills are listed with their problems instead of loading.
  - Script skills get their arguments as JSON on stdin, run with `cwd` set to the skill folder and `HOME`/`TMPDIR` set to its `work/` folder, a minimal environment and a timeout. Output is capped at 20,000 characters.
  - On macOS they run under `sandbox-exec` with: `(deny network*)` unless `network: true`; file writes only to `work/` and temp folders; and reads denied for Mail, Messages, Keychains, Cookies, Safari, Group Containers, AddressBook, Chrome, the agent's data, `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.config/gh`. Without a sandbox (non-macOS), script skills refuse to run unless `skills_require_sandbox` is off (tests only).
  - The Connectors tab rescans the folder. A message mentioning a skill's name offers the tools even for quick questions.
- **Files:** every path is resolved and checked to be inside `file_roots` (default `~/Downloads`, `~/Desktop`, `~/Documents`). Trash moves files to `~/.Trash`, so they can be recovered.

---

## 7. Policy, approvals and audit

- **Tiers (declared per tool, enforced by `policy/engine.py`):**
  - **read** and **draft** run automatically.
  - **write** needs approval unless a matching grant exists.
  - **danger** needs a fresh one-time approval every time.
- **Scopes for write approvals:**
  - once;
  - this request (task);
  - until restart (session);
  - 1 hour or 24 hours;
  - always.

  Grants are listed under **Approvals**, where they can be revoked.
- **Pending approvals** store the paused tool loop as JSON. Approvals still pending when the agent restarts are marked expired.
- **Audit log** (`audit` table): every tool call, approval request and decision, grant revocation, connector test and proactive job is appended. Each row's `hash = SHA-256(previous_hash + canonical JSON of the row)`. **Activity** shows the log, and `/api/audit/verify` recomputes the chain, reporting the first row that was altered outside the app.

---

## 8. Memory

- **Storage:** one SQLite file, `~/Library/Application Support/LocalAIAgent/localagent.db`. Tables:
  - `messages`, `memories`, `decisions`, `examples`;
  - `approvals`, `grants`, `audit`;
  - `jobs`, `nudges`, `meta`.
- **Vectors:** float32 blobs searched with numpy (no SQLite extensions). Brute-force cosine search is fast at personal scale (thousands of rows).
- **Identity file:** `identity/about-me.md` is regenerated from the `memories` table on every change. **Forget** deletes the row and its vector together, and the file is rewritten.
- **Dream** (overnight, while plugged in):
  - re-reads the day's messages to extract facts it missed;
  - merges near-duplicate memories (cos ≥ 0.88, confirmed by `qwen3:1.7b` through a JSON schema);
  - writes a report nudge.

---

## 9. Proactivity

- **Scheduler** (`proactive/scheduler.py`):
  - jobs persist in SQLite with `next_run`, and the server ticks every 60 s;
  - if the Mac slept through a run, the job runs **once** when it wakes, marked `late`; missed runs are never replayed;
  - a job can **defer** itself (dream on battery retries in 30 min);
  - **Run now** doesn't move the schedule.
- **Jobs** (`proactive/jobs.py`):
  - **morning_brief** (daily, `brief_time`): calendar, reminders, unread mail and unreplied mail go to `qwen3:4b`, with "use only this data". The brief appears in Chat and in Nudges.
  - **checks** (every `check_every_minutes`, default 30). Candidates are:
    - events starting within 60 min;
    - reminders due within 60 min or overdue;
    - mail received 1–`followup_days` days ago and never replied to (Mail's `was replied to`).

    Each candidate is deduplicated by key, then **decided** (`should_nudge`, `urgency`).
  - **dream** (daily, `dream_time`), as described in section 8.
- **Delivery policy** (`proactive/nudges.py`):
  - every nudge is stored and listed;
  - a macOS notification (via `display notification`) is sent only if notifications are on, it isn't **quiet hours** (handles ranges across midnight), and today's **cap** (`max_nudges_per_day`) isn't reached. Briefs aren't capped; dream reports are silent.
  - Dismiss, Snooze 1 h, and Ask about this.

---

## 10. Voice

```
mic (browser) ─ Web Audio ScriptProcessor ─ energy VAD ─ downsample → 16 kHz mono 16-bit WAV
  → POST /api/voice/transcribe → read_wav (stdlib wave + numpy) → mlx-whisper → text
  → normal chat turn (same decisions, tools, approvals)
  → POST /api/voice/speak → strip markdown → `say -r <rate> [-v <voice>] -f <tempfile>`
  → (conversation mode) reopen the mic when speech finishes
```

- **Ways to talk:**
  - hold to talk;
  - click to start and click again to stop;
  - hold **Space** when you're not typing;
  - **conversation mode** (VAD sends after ~1.2 s of silence).
- **Barge-in:** clicking the mic stops speech (`/api/voice/stop`).
- **Approvals:** never spoken or approved by voice; the agent says to approve on screen.
- **No ffmpeg:** the browser sends WAV directly.
- **No wake word:** this is deliberate, because an always-on mic costs battery and privacy (`PLAN.md` Appendix A #28).

---

## 11. Data and privacy

| Data | Where | Leaves the Mac? |
|---|---|---|
| Messages, memories, decisions, approvals, audit, nudges | SQLite in `~/Library/Application Support/LocalAIAgent/` | No |
| Identity file | `…/identity/about-me.md` | No |
| PDFs / spreadsheets the agent makes | `~/Documents/LocalAIAgent/` | No |
| Audio | In memory only, during transcription; never written to disk | No |
| Calendar/Mail/Contacts content | Read on demand through the Apple apps; only what a tool returns is kept (in messages or the audit summary) | No |
| iMessage/WhatsApp history | Read on demand, read-only, from the apps' own databases; never copied in bulk | No (a sent iMessage goes through Apple, as if you sent it) |

Network access happens only for **model downloads**: Ollama pulls from ollama.com, and the Whisper model comes from Hugging Face (anonymous; the "unauthenticated" warning is harmless). The optional `systemone` backend talks to a server you run on localhost.

---

## 12. Key settings

| Setting | Default | Meaning |
|---|---|---|
| `chat_model` / `fast_model` / `embed_model` | qwen3:4b / qwen3:1.7b / all-minilm | Ollama tags |
| `decision_backend` | hybrid | hybrid · prototype · slm · systemone |
| `confidence_threshold` | 0.6 | Escalate to the SLM judge below this |
| `prototype_temperature` | 30 | Softmax sharpness of the prototype classifier |
| `memory_top_k` / `memory_min_similarity` | 5 / 0.35 | Recall breadth and threshold |
| `max_tool_steps` | 5 | Tool-loop iterations per turn |
| `calendar_backend` | auto | Calendar listing: EventKit when allowed, else AppleScript |
| `enable_messages` / `enable_whatsapp` / `messages_include_groups` | on / on / off | Messages connector |
| `enable_browser` / `browser_headless` / `browser_executable` | on / off / (Chrome, else Chromium) | Browser |
| `enable_skills` / `skills_require_sandbox` | on / on | Custom skills |
| `file_roots` | ~/Downloads, ~/Desktop, ~/Documents | Files connector boundary |
| `brief_time` / `dream_time` / `check_every_minutes` | 08:00 / 03:00 / 30 | Proactive schedule |
| `quiet_start` / `quiet_end` / `max_nudges_per_day` | 22:00 / 07:30 / 6 | Interruption policy |
| `stt_model` / `tts_voice` / `tts_rate` | whisper-large-v3-turbo / system / 190 | Voice |

---

## 13. Testing and known limits

- **Automated tests:** 104 pytest tests (one drives a real headless Chromium against a local test site when Playwright and Chromium are available; CI skips it) run against a **fake Ollama** and a **fake osascript runner**:
  - the fake Ollama gives deterministic hashed embeddings, a rule-based judge and rule-based tool calls;
  - the fake osascript runner returns canned app outputs;
  - fake STT and TTS cover voice.

  They cover decisions, memory, the tool loop with approvals, scopes, danger tier, audit tampering, the scheduler's catch-up/defer/quiet-hours/cap behaviour, nudges, dream merging, WAV handling, the voice endpoints and the CLI.
- **Browser tests:** Playwright runs against the real UI, including a fake microphone.
- **CI:** a workflow for Ubuntu and macOS-14 (Apple Silicon) is ready in `.github/workflows/ci.yml`; it runs once the repo is on GitHub.
- **Not covered by automated tests:** the real AppleScripts against the Apple apps, real model quality, and real audio. These are verified by the manual checklists in `TESTING.md` on the target Mac.

Known limits:
- The decision percentages aren't calibrated probabilities (see 4.8).
- Without calendar Full Access, repeating events are expanded from their rules. A moved single occurrence can appear at both times, and rules dateutil can't parse are skipped.
- Mail search covers the Inbox only.
- Browser tasks with a 4B model work for short flows; long checkouts and sites with bot checks often fail. The element list is capped at 120 per page.
- WhatsApp reading uses an undocumented local database and only sees chats synced to WhatsApp Desktop. WhatsApp replies must be sent by the user.
- Proactivity runs only while the Mac is awake and the agent is running.
- Notifications are attributed to Script Editor.

Next on the roadmap (`PLAN.md`): Step 5 (browser and Mac app actions, skills, form filling), Step 6 (Telegram/iMessage), Step 7 (optional extras).
