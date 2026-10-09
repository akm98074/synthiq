# LocalAIAgent: design document

**Version:** 0.14.0 (Steps 1–4 of 7) · **Platform:** Apple Silicon Mac, 16 GB+ · **Companion docs:** [`PLAN.md`](PLAN.md) (research, feasibility, roadmap), [`../UPGRADING.md`](../UPGRADING.md), [`../TESTING.md`](../TESTING.md)

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

### 5.1 Cloud escalation (Step 7c, `agent/cloud.py`)

- **When:** `wants_cloud()` is true only when `cloud_enabled` is on, an Anthropic key is in the vault, and either the message asks for it ("think harder", "use the cloud", "ask Claude"…) or `cloud_auto_hard` is on and the decision layer rated complexity 5.
- **What's sent:** `build_request()` makes the system prompt (persona plus the recalled memories if `cloud_send_memories`), up to six earlier turns (starting with a user turn), and the question with the trigger phrase removed. No tools or tool results, and nothing else from the Mac.
- **Approval:** a pseudo-tool `cloud_ask` (write tier, never offered to the model) runs through `Policy.needs_approval`/`request`, so the usual scopes, grants and audit apply. The card's summary names the model and the question, plus the counts of memories and earlier messages. The paused request is stored as `{"kind": "cloud", "req": …}` and resumed by `resume_after_decision`.
- **Call:** the official `anthropic` SDK (async), `client.beta.messages.stream(model=cloud_model, max_tokens=16000, output_config={"effort": cloud_effort}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")`.
  - Thinking isn't sent, so it's adaptive by default on Claude Opus 5.5.
  - A safety decline is retried server-side on the fallback model Anthropic picks for that refusal category. A remaining `stop_reason: "refusal"` is reported.
  - Typed SDK errors (authentication, permission, rate limit, status, connection) become plain messages.
- **Result:** the text is streamed as tokens, saved as the assistant message, and marked "(cloud)". The audit row records the counts, never the key.

---

## 6. Tools and connectors

| Connector | Tools (tier) | Mechanism |
|---|---|---|
| Calendar | `calendar_list_events` (read), `calendar_create_event` (write) | Listing: **EventKit** (pyobjc; expands repeating events, includes every account, invitation status) with an AppleScript fallback that expands repeating series from their RRULE (`connectors/recurrence.py`, python-dateutil). Creating: AppleScript |
| Reminders | `reminders_list` (read), `reminders_create` (write) | AppleScript |
| Notes | `notes_search` (read), `notes_create` (draft) | AppleScript |
| Mail | `mail_list`, `mail_followups`, `mail_read` (read), `mail_draft` (draft), `mail_send` (write) | Reads from Mail's own index (`Envelope Index`, read-only, Full Disk Access) and `.emlx` files; a bounded AppleScript (newest messages of each inbox, no bodies in lists) only if the index can't be used. Drafts and sends use AppleScript. Background checks never script Mail.app more than every 3 h, nor while Mail is above 2 GB or recently timed out (0.17.2; whole-inbox AppleScript queries had grown Mail to tens of GB). |
| Contacts | `contacts_find` (read) | AppleScript |
| Files | `files_search`, `files_list` (read), `files_open` (draft), `files_move` (write), `files_trash` (danger) | Python, confined to allowed folders |
| Documents | `documents_create_pdf`, `documents_create_spreadsheet` (draft) | fpdf2, openpyxl |
| Gmail (7b) | `gmail_search`, `gmail_read`, `gmail_followups` (read; untrusted), `gmail_draft` (draft), `gmail_send` (write) | Gmail REST API via httpx; OAuth installed-app flow with PKCE; tokens in the Keychain |
| Web search | `web_search` (read; optional `site`) | DuckDuckGo HTML results via httpx: titles, unwrapped links, snippets; untrusted |
| Browser | `browser_open` (draft), `browser_read` (read), `browser_find` (read), `browser_click`, `browser_type` (draft), `browser_submit` (danger) | The user's installed Google Chrome, started by the agent on its own profile and driven over DevTools (Playwright `connect_over_cdp`) |
| Custom skills | `skill_<name>` (tier from SKILL.md; at least write when `network: true`) | Folder with `SKILL.md`; scripts run under `sandbox-exec` |
| Mac apps & Shortcuts | `apps_list`, `app_ui_read`, `shortcuts_list` (read), `app_open` (draft), `app_ui_press` (write; danger for Delete/Send/Buy… labels), `app_type_text`, `shortcuts_run` (write) | AppleScript: System Events (Accessibility) and Shortcuts Events |
| Screen context (opt-in) | `screen_now`, `screen_recent` (read) | `screencapture` → Vision OCR (pyobjc), image deleted at once; text kept in `screen_snapshots` |
| Forms | `browser_fill_form` (draft) | The chat model maps memories to the current page's fields; values are typed in, never submitted |
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
- **Vault (`vault.py`):** secrets go through `keyring` (macOS login Keychain, service "LocalAIAgent"). Without a usable keyring (Linux without Secret Service, or tests with `LOCALAGENT_NO_KEYRING`), they go to `secrets.json` written 0600 via an atomic replace. Secrets are never in `config.json`, the audit log or tool output.
- **Gmail (7b, `connectors/gmail.py`):**
  - **Sign-in:** the user's own "Desktop app" OAuth client. `/api/gmail/login` builds the consent URL (scopes `gmail.modify` and `gmail.compose`, `access_type=offline`, `prompt=consent`, S256 PKCE, a random state kept for 10 minutes) with the redirect back to the agent's own `127.0.0.1` address. `/api/gmail/callback` exchanges the code, stores the refresh token in the vault, and records the address from `/profile`.
  - **Tokens:** access tokens are memory-only and refreshed early (60 s before expiry). One 401 triggers a forced refresh and a retry. `invalid_grant` deletes the refresh token and asks the user to reconnect.
  - **Search and read:** `messages.list` then `messages.get(format=metadata)` for summaries. `read` prefers `text/plain` parts and otherwise strips HTML (scripts and styles removed).
  - **Follow-ups:** threads matching `in:inbox -from:me newer_than:Nd older_than:Md`, excluding the promotions, social, updates and forums categories, whose last message isn't from the user.
  - **Drafts and sends:** RFC 822 via `EmailMessage`, base64url `raw`. Replies set `threadId`, `In-Reply-To` and `References`.
  - Nudge candidates are deduplicated by (title, subject) so Apple Mail and Gmail don't double up, and the brief uses Gmail for "waiting on your reply" when connected.
- **Look-ups (0.7.1, `connectors/websearch.py`):**
  - `quick_answer` messages are always offered the tools (when web search is on). The guide tells the model to call `web_search` for anything that changes or is local (prices, shops, restaurants, hours, phone numbers, weather, news), open the best result, and answer from that page with the link. For a store's price, it opens the store's own site and uses its search box. General-knowledge questions get no tool call.
  - The decision layer gained 14 seed examples (`data/web_seed.jsonl`) such as "chutneys bellevue" → quick_answer. Seed files are now tracked per file in `meta` (`seeded:<file>`), so new seed sets reach existing installs.
  - The search POSTs to `html.duckduckgo.com/html/` and parses `result__a`/`result__snippet`, unwrapping `uddg` redirect links and dropping DuckDuckGo-internal links (ads). A robot check or network error points the model to Bing in the agent's browser.
- **Starting Chrome (0.7.2, `ChromeProcess`):**
  - `find_chrome()` uses the `browser_executable` setting (an `.app` or binary), else Google Chrome, Beta or Canary in `/Applications` or `~/Applications`.
  - Chrome is started as a normal process (no automation flags): `--remote-debugging-port=0 --remote-debugging-address=127.0.0.1 --user-data-dir=<data>/browser-profile --no-first-run --no-default-browser-check`. Chrome writes the chosen port to `DevToolsActivePort`; the agent polls `/json/version` (20 s), then attaches with `connect_over_cdp`.
  - A different user-data-dir means a separate Chrome instance, so the user's own Chrome is never touched.
  - A Chrome from an earlier agent run that still holds the profile and answers is **reused**. A live holder that doesn't answer is reported with its pid. A `SingletonLock` left by a dead process is removed.
  - If the tab is closed, a new one opens in the same window. If Chrome is gone, it's started again with the same profile, so logins persist. On shutdown, the agent terminates the Chrome it started (or sends `Browser.close` to a reused one).
  - Every failure (not found, exited with code N plus Chrome's stderr tail, port never opened, attach failed) is reported verbatim. Playwright's bundled Chromium is never used. `localagent setup --browser` runs the same start-up against example.com.
- **Watching it work:**
  - Before each click or type, `SHOW_JS` scrolls the element into view and draws a fixed overlay (pointer-events none) with an animated cursor, a highlight ring, a label "<agent>: clicking “…”" and a click ripple.
  - `PILL_JS` shows a status pill. The window comes to the front, and the step waits `browser_action_delay_ms` (600). Typing up to 80 characters uses `press_sequentially` at 40 ms per letter.
  - The overlay sits on `<html>`, outside `<body>`, so it never appears in the page text or the element list.
  - After each step a JPEG of the viewport is captured with CDP `Page.captureScreenshot` (quality 50, scaled to about 640 px wide). It's sent as `data.shot` for the chat's live view and isn't stored.
- **Browser (Step 5b, `connectors/browser.py`):**
  - The model never sees HTML. `SNAPSHOT_JS` tags up to 1,500 visible interactive elements with `data-la-ref=N` (duplicate links with the same href and text are skipped). It returns title, URL and the main content's `innerText` (cut at 6,000 characters), or the whole page's text when there's no main content.
  - Each element gets a priority: 0 inside `main`, `[role=main]`, `article` or Amazon-style `#dp`/`#centerCol`; 2 inside header, nav or footer; 1 otherwise. The model sees the first 120 by priority, plus a "+N more" line. `browser_find(text)` searches all tagged elements by label words, so nothing on the page is out of reach.
  - `needs_submit()` decides what counts as committing: a label matching buy, pay, order, send, delete, book, subscribe, agree…, or a form-submit button that isn't plainly search/filter/next. `browser_click` refuses those and points to `browser_submit` (danger: approved every time, scope "once" only).
  - `browser_type` refuses password fields and fields whose label matches `forms.SENSITIVE` (card number, CVV, expiry, IBAN, SSN, one-time codes). It presses Enter only in search boxes (`type=search`, `role=search`, or a name/placeholder containing search/query/`q`).
  - Only http(s) URLs open; `javascript:`, `file:` and `data:` are rejected. Page content is `untrusted`, so it's fenced and scanned like mail.
  - The latest snapshot is stored on the browser object, so element numbers survive a tool rebuild. The window is visible by default (`browser_headless` off) so the user can watch and take over.
- **Custom skills (`skills.py`):**
  - The SKILL.md header holds name, description, args, run, tier (default write), network (default false) and timeout. Invalid skills are listed with their problems instead of loading.
  - Script skills get their arguments as JSON on stdin, run with `cwd` set to the skill folder and `HOME`/`TMPDIR` set to its `work/` folder, a minimal environment and a timeout. Output is capped at 20,000 characters.
  - On macOS they run under `sandbox-exec` with: `(deny network*)` unless `network: true`; file writes only to `work/` and temp folders; and reads denied for Mail, Messages, Keychains, Cookies, Safari, Group Containers, AddressBook, Chrome, the agent's data, `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.config/gh`. Without a sandbox (non-macOS), script skills refuse to run unless `skills_require_sandbox` is off (tests only).
  - The Connectors tab rescans the folder. A message mentioning a skill's name offers the tools even for quick questions.
- **Mac apps (Step 5c, `connectors/apps.py`):**
  - `ui_snapshot.applescript` walks `entire contents of window 1` (up to 400 items). Python keeps interactive roles (button, checkbox, text field, tab, menu item…) plus static text, and shows up to 150, numbered by their position.
  - `ui_press.applescript` re-reads the window and checks the element's role and name are unchanged before `AXPress`. Otherwise it says "The window changed".
  - Password managers, Keychain Access, System Settings, terminals and the agent itself are refused. Accessibility errors (-1719, -25211) become the permission steps.
- **Per-call risk:** a `Tool` may define `risk(args)`. `Tool.tier_for(args)` takes the higher of that and the declared tier. The policy uses it to decide approval, and the approval row stores it (so a "Delete" press allows only "once"). If the element isn't known, the press counts as danger.
- **Screen context (`connectors/screen.py`):**
  - Off by default. When on, a "screen" job runs every `screen_every_minutes`. `snap()` runs `front_app`, then:
    - skips the lock screen and apps on `screen_blocklist`;
    - checks `CGPreflightScreenCaptureAccess`;
    - runs `screencapture -x` to a temp file, OCRs it with `VNRecognizeTextRequest` (accurate), and deletes the file in a `finally`;
    - keeps the text (up to 8,000 characters), deduplicated by SHA-256 of app, title and text.
  - Rows older than `screen_retention_minutes` are purged on every capture and read. Turning the feature off, or `DELETE /api/screen`, deletes all of them. Screen text is `untrusted`.
- **Form filling (`connectors/forms.py`):** fillable fields are text, email, number and similar inputs, text areas and selects; never passwords, buttons, checkboxes or files. Fields whose label mentions passwords, card numbers, CVV, expiry, IBAN, SSN or one-time codes are left out of the prompt. The model gets the memories and fields and returns `{ref, value, source}` under a JSON schema. Unknown refs, empty values and select values that aren't real options are dropped. Nothing is clicked.
- **Files:** every path is resolved and checked to be inside `file_roots` (default `~/Downloads`, `~/Desktop`, `~/Documents`). Trash moves files to `~/.Trash`, so they can be recovered.

---

### 6.1 iMessage channel (Step 6, `channels/imessage.py`)

- **Loop:** a background task polls `chat.db` every 3 s through `IMessages.new_since(last_rowid)`. The last ROWID is kept in `meta` (`imessage_channel_last`), and the first start skips history.
- **What counts as a message for the agent:**
  - **self mode (default):** your own sent message (`is_from_me=1`) in the chat whose identifier is one of `imessage_owner_handles`, starting with the agent's name. The prefix is stripped. Duplicates within 2 minutes are dropped (a self-chat can log both copies). Anything starting with 🤖 (the agent's own replies) is ignored.
  - **account mode:** incoming (`is_from_me=0`) one-to-one messages from an owner handle. Others are audited as `channel_ignored` (sender only, no content) and never answered.
  - Group chats are never used, and there's a rate limit of 12 per minute.
- **A turn:** the command runs through `handle_turn`. Tokens are collected, markdown is turned into plain text, and the reply is split at 1,500 characters and sent with `messages_send.applescript` to the same chat id.
- **Approvals:** an `approval_required` event stores its id in `meta` (`imessage_channel_approval`) and adds "Needs your OK: <summary>. Reply …". The next owner message matching `yes [scope]`/`no` calls `Policy.decide` (danger forced to "once") and `resume_after_decision`.
- **Forwarding:** `Nudges.forwarders` sends nudges and the brief (not the dream report) when `imessage_forward_nudges` is on, outside quiet hours for interrupting kinds.
- **The one-Apple-ID limit:** Messages holds one Apple ID, so account mode suits a spare Mac. Self mode works on the user's own Mac alongside the Messages connector.

---

### 6.2a Phone line (Step 7f, `channels/phone.py`)

- **Listener:** a separate uvicorn app on **127.0.0.1:`phone_port`** (8767) with only `/twilio/voice`, `/twilio/gather` and `/twilio/result`. The user's tunnel (cloudflared / Tailscale Funnel) forwards their public URL to it, so the main app is never reachable from the internet.
- **Authenticity:** every request's `X-Twilio-Signature` must equal base64(HMAC-SHA1(auth token, `phone_public_url` + path + query + sorted form key/value pairs)), compared in constant time. The auth token is in the vault. Requests without a valid signature get 403 and are audited.
- **Callers:** only numbers in `phone_owner_numbers` (compared on the last 10 digits); others hear "private" and the call ends.
- **A turn:** `SpeechResult` → `handle_turn(channel="phone")`, which keeps only read/draft tools (nothing can be approved by phone), disables cloud escalation, and adds a short "phone call" style note. Because local turns can exceed Twilio's 15 s limit, the answer is computed in a background task while TwiML says "One moment" and `<Redirect>`s to `/twilio/result?id=…`, which `<Pause>`s and redirects until done (90 s cap). Replies go through `speakable()` (900 characters), are XML-escaped, and are spoken with `<Say>`, followed by another `<Gather>`.
- **Privacy:** Twilio does the speech recognition and synthesis (cloud), so this is opt-in and stated in the UI and docs.

### 6.2 Trusted agents (Step 7e, `connectors/peers.py`, `peers_server.py`)

- **Identity:** an X25519 key pair per agent (PyNaCl). The private key is in the vault; the public key and a 16-hex fingerprint are shown in Settings.
- **Pairing:** `invite()` stores a one-time token (7-day lifetime) and returns `la1-` + base64url(JSON {name, owner, key, addr, token}). The acceptor stores the peer and sends an encrypted `hello` {token, its card}. The inviter accepts a `hello` from an unknown key only with an unused, unexpired token (the box must still open with the sender's claimed key, which proves possession), then stores the acceptor.
- **Envelope:** `{from: public key, box: Box(sender_sk, recipient_pk).encrypt(JSON{…, ts, nonce})}`. Authenticated encryption, so only the paired agent can read it and only it could have written it.
  - Rejected: decryption failures, |ts − now| > 300 s, a repeated nonce (kept in `peer_nonces`), unknown senders, and more than 30 messages per minute per peer. Each rejection is audited as `peer_rejected`.
  - Responses are sealed the same way.
- **Policy:**
  - `ask/freebusy` is answered automatically only with the `freebusy` scope: busy blocks within at most 14 days, no titles, declined events excluded.
  - `ask/message` with the `message` scope becomes a nudge.
  - Anything else is stored in `peer_inbox` and shown as a "peer" nudge with **Reply**. The owner's reply is sent as a sealed `reply`, which arrives at the asker as a nudge.
  - Outbound `peer_ask` is a write tool (approval). Answers are `untrusted`.
- **Transport:** a separate uvicorn server (`a2a_app`, one POST route, no docs) on `a2a_host:a2a_port`, started only when `a2a_enabled` (restarted on settings changes). The main UI stays bound to 127.0.0.1. The address in invites is `a2a_public_addr`, or the LAN address found without sending packets (a UDP connect).

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

  Grants are keyed by **tool and target** (the recipient, chat, web site or friend's agent from `safety/egress.py`), so allowing emails to Priya doesn't allow emails to anyone else. "Always" expires after 30 days. Grants are listed under **Approvals** and in the Trust tab, where they can be revoked.
- **Approval cards** carry the full payload (`preview`: destination, URL, every argument in full) and the reason (`reason`: the tier, or the egress or taint rule that triggered it). The iMessage channel includes both in its text approvals.
- **Pending approvals** store the paused tool loop as JSON. Approvals still pending when the agent restarts are marked expired.
- **Audit log** (`audit` table): every tool call, approval request and decision, grant revocation, connector test and proactive job is appended. Each row's `hash = SHA-256(previous_hash + canonical JSON of the row)`. **Activity** shows the log, and `/api/audit/verify` recomputes the chain, reporting the first row that was altered outside the app.

### 7.1 Local API access (`security.py`, 0.16)

The UI server listens on 127.0.0.1, but any local program, and any website through DNS rebinding, can reach localhost. A middleware therefore checks every request:
1. **Host** must be `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`, or else 421.
2. **The per-install secret** (`<data>/api-token`, 0600): either the `la_session_<port>` cookie (HttpOnly, SameSite=Strict) that `GET /auth?c=<code>&next=…` sets, or `Authorization: Bearer` from the CLI. The secret never goes in a URL: `localagent open` first asks the running agent (with the Bearer secret) for a one-time code that works once, for 60 seconds (`POST /api/signin-code`; a cookie alone can't mint one). Since 0.17.0 the secret is replaced once on upgrade, because earlier links carried it. Otherwise 401, and `/` shows "open with `localagent open`". Exempt: `/api/health` and `/api/gmail/callback`, which arrives from Google and is protected by its single-use state and PKCE.
3. **Origin** on non-GET requests must be the app's own, or else 403.

UI responses carry a CSP (`default-src 'self'`) and `nosniff`. Security-sensitive settings (`config.SENSITIVE_SETTINGS`) need `X-Confirm: <keys>`; otherwise the server answers 428 with each change's risk, and the UI asks. Every settings change is audited as `settings_changed`.

### 7.2 Egress gating (`safety/egress.py`, 0.16)

One table says which tool calls can carry data off the computer and where: `web_search`, `browser_open`/`type`/`fill_form`, `gmail_send`, `mail_send`, `imessage_send`, `peer_ask`, `cloud_ask` and network skills. `ActionRun` sets `read_untrusted` once **any** untrusted result enters the conversation; the pattern scanner is no longer the only trigger. From then on:
- sends (write/danger) need a fresh approval, whatever grants exist;
- `browser_open` runs by itself only for an address already seen verbatim (a link on a page or in your message), which can't carry new data;
- typed or searched text runs by itself only if every word came from your own message;
- form filling from memory needs approval.

Before any untrusted read, only a URL whose query string is longer than 120 characters needs approval. The state survives an approval pause. `tests/test_redteam.py` covers an injection the scanner misses.

### 7.3 Trust & Transparency center (`trust.py`, 0.16)

- `CAPABILITIES`: one entry per capability with its setting, platform, OS permissions (deep links on macOS), what it reads, what can leave, risk level and text, and safeguards. Last use is derived from the audit log.
- **Presets** (`autonomy`): observer = read, assistant = draft, agent = everything with approvals. **Pause** (`paused`) caps the tool loop at read and stops the scheduler, the phone line, peer answers, the iMessage channel (except "resume") and the wake word. Both are enforced in `ActionRun._beyond_ceiling`, not only in the UI.
- **Egress ledger**: audit `tool_call` rows whose tool has egress, plus `channel_reply`, `channel_forward`, `phone_answer`, `peer_answered` and `peer_reply`.
- **Posture checks**: sign-in guard, binding, data folder mode, disk encryption, local models, sandbox, app identity (macOS), phone PIN, listener address, verified peers, cloud memories, permanent grants and the audit chain.
- **Automated checks** for a window: secrets and personal data in the log (`safety/pii.py`: emails, phones, Luhn-checked cards, SSNs, IBANs, API keys, JWTs, passwords, public IPs, street addresses, names from Contacts and peers), personal data that left, write/danger calls with neither an approval nor a prior grant, danger calls without a one-time approval, injection flags, blocked attempts, sensitive setting changes, and chain integrity.
- **Export** (`/api/trust/export`): a zip with `README_FOR_REVIEWER.md` (file guide and reviewer prompt), `settings.json`, `secrets.json` (set or not set, never values), `capabilities.json`, `grants.json`, `audit.jsonl`, `approvals.jsonl` (without the stored conversation state), `egress.jsonl`, `decisions.jsonl`, `integrity.json` (chain verify plus the window's boundary hashes), `checks.json`, and `manifest.json` (SHA-256 of every file). Redaction is on by default: stable tokens per value (`<EMAIL_3>`). A raw export requires `confirm_raw=yes`. Each export is audited.

### 7.4 Pairing verification and the phone PIN (0.16)

- **Trusted agents** show a 4-emoji safety code from `sha256(sorted public keys)`. Until a pairing is confirmed with "They match", the peer gets no automatic answers and can't be asked. Invites last 24 h.
- **The phone line** asks for a PIN (DTMF or spoken digits, kept in the vault) on every call. Three wrong tries end the call. A `StirVerstat` containing "Failed" is rejected, and with no PIN set every call is refused.

### 7.5 Data at rest and app identity (0.16)

- At every start the data folder is set to 0700 and its files to 0600 (`security.lock_down`), and the browser profile to 0700; `server.log` is created 0600. On Windows the per-user LocalAppData ACL applies. Disk encryption (FileVault, BitLocker, LUKS) is reported, not enforced.
- **macOS**: `localagent app install` (run by `install.sh`) builds `~/Applications/LocalAIAgent.app` on the Mac with Apple's `osacompile`. That gives an AppleScript applet, a Mach-O stub LaunchServices accepts. (0.16.0–0.16.1 used a shell-script executable, which macOS refused with error -10669.)
  - `plutil` sets bundle id `ai.localagent.app`, `LSUIElement` and the usage strings, and the bundle is ad-hoc signed.
  - The applet runs `python -m localagent.launcher --no-open` in the background and quits; the agent is its child, so permissions belong to LocalAIAgent.
  - **Self-test:** `install` writes `app-selftest-request` and opens the app. The launcher answers with `app-selftest-ok` without starting anything. If that doesn't happen within 15 s, the bundle is removed.
  - **Start:** `start` uses `open -g -a`. If `open` fails, or the agent doesn't come up in 30 s, it writes `app-launch-failed`, prints why, and starts from Terminal; later starts skip the app until `app install` succeeds.
  - Autostart's LaunchAgent runs `/usr/bin/open -g -a <app>`.
  - Because the signature changes, macOS may ask for permissions again after an upgrade.
- **The macOS skill sandbox** denies reading the home folder; only the skill folder and an interpreter under home are allowed back. It also denies Apple Events, LaunchServices and the pasteboard, and executing `osascript`, `open`, `pbcopy`/`pbpaste` and `shortcuts`.

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
    - mail received 1–`followup_days` days ago and never replied to (the index's "answered" flag; Mail's `was replied to` in the fallback).

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

### 10.0 Avatar (Step 7d)

- **Audio:** `SayTTS.synthesize()` runs `say -o <tmp>.wav --file-format=WAVE --data-format=LEI16@22050 -f <text file>` and returns the bytes. `POST /api/voice/audio` serves them (`no-store`), and temp files are deleted.
- **Lip-sync:** in the browser, an `AudioBufferSourceNode` feeds an `AnalyserNode` (fftSize 1024). Each frame's RMS × 6 (capped at 1) is smoothed 50/50 with the previous frame and mapped to one of five mouth shapes (ellipse rx/ry), exposed as `data-level` 0–4.
- **Face:** an SVG with blinks (random, about every 2.5–5 s), a resting smile when not talking, a gentle bob (off with reduced motion), and theme colours.
- **Control:** `avatar_enabled` switches spoken replies from the server's `say` to browser playback. 🔊 on each reply uses the same path. `voice.speaking` is set during playback, so the wake word never hears the agent itself, and clicking the mic stops the source (barge-in).

### 10.1 Wake word (Step 7a, `voice/wake.py`, `ui/voice.js`)

- **In the browser:** while "Hey <name>" is on, a second always-open mic stream runs a VAD. The noise floor is an exponential moving average, and "loud" means RMS above max(0.015, 3 × noise).
  - It keeps one block of pre-roll and ends a burst after 450 ms of silence or 6 s total.
  - Bursts with at least 250 ms of speech are sent as 16 kHz WAV to `POST /api/voice/wake`.
  - Bursts are dropped while recording, working, speaking or checking, so it never wakes on its own replies.
- **On the server:** bursts of 0.3–8 s are transcribed by `wake_model` (`mlx-community/whisper-tiny.en-mlx`). `match()` then requires the phrase at the start (one filler word allowed):
  - **phrases:** a greeting from hey/hi/hello/ok/okay/yo plus the agent's name, the bare name, and extra phrases from settings;
  - **greeting:** must be at least 0.6 similar;
  - **name:** compared in a sound-alike form (`phon`: doubled letters collapsed, a leading h dropped, ie/ee/ey/y → i, so "Harry" ≈ "Ari"), at least 0.75 similar (0.9 for a bare name). "Hey Siri" and "Are you there" don't match.
  - Words after the phrase are returned as the command.
- **On a hit:** a chime, then the command is asked directly or conversation mode starts. Audio is never stored.

---

## 11. Data and privacy

| Data | Where | Leaves the Mac? |
|---|---|---|
| Messages, memories, decisions, approvals, audit, nudges | SQLite in `~/Library/Application Support/LocalAIAgent/` | No |
| Identity file | `…/identity/about-me.md` | No |
| PDFs / spreadsheets the agent makes | `~/Documents/LocalAIAgent/` | No |
| Audio | In memory only, during transcription; never written to disk | No |
| Calendar/Mail/Contacts content | Read on demand through the Apple apps; only what a tool returns is kept (in messages or the audit summary) | No |
| Gmail | Read on demand from Google's Gmail API (it's your mail at Google); refresh token in the Keychain | Only the requests you make to Gmail |
| Cloud questions (opt-in) | Sent to Anthropic only after approval: the question, up to 6 earlier messages, and (setting) recalled memories | **Yes**, exactly what the approval card lists |
| Phone calls (opt-in) | Your speech and the agent's spoken replies pass through Twilio | **Yes**, via Twilio during calls |
| Trusted-agent messages (opt-in) | Sent directly to the paired agent, end-to-end encrypted; only what you approve (outbound) or allowed by scope (inbound) | Only to the paired Mac |
| Web search queries | Sent to DuckDuckGo (search words only, no account or cookies) | **Yes**, the query; turn off with `enable_web_search` |
| Screen text (opt-in) | `screen_snapshots` table, deleted after 2 hours; screenshots are deleted immediately after OCR | No |
| iMessage/WhatsApp history | Read on demand, read-only, from the apps' own databases; never copied in bulk | No (a sent iMessage goes through Apple, as if you sent it) |

Besides the web tools you ask for (web search queries, pages the agent's browser opens), network access happens only for **model downloads**: Ollama pulls from ollama.com, and the Whisper model comes from Hugging Face (anonymous; the "unauthenticated" warning is harmless). The optional `systemone` backend talks to a server you run on localhost.

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
| `enable_web_search` | on | Web look-ups |
| `phone_enabled` / `phone_owner_numbers` / `phone_public_url` / `phone_port` | off / (yours) / (tunnel URL) / 8767 | Phone line; the Twilio auth token is in the vault |
| `a2a_enabled` / `a2a_host` / `a2a_port` / `a2a_public_addr` | off / 0.0.0.0 / 8766 / (LAN address) | Trusted agents |
| `cloud_enabled` / `cloud_model` / `cloud_effort` / `cloud_send_memories` / `cloud_auto_hard` | off / claude-opus-5-5 / high / on / off | Cloud escalation; the API key is in the vault |
| `enable_gmail` / `gmail_client_id` / `gmail_account` | on / (yours) / (set on sign-in) | Gmail; the secret and tokens are in the vault |
| `enable_imessage_channel` / `imessage_channel_mode` / `imessage_owner_handles` / `imessage_forward_nudges` | off / self / (empty) / on | iMessage channel |
| `enable_browser` / `browser_headless` / `browser_executable` | on / off / (installed Google Chrome) | Browser |
| `browser_show_actions` / `browser_action_delay_ms` | on / 600 | Cursor, highlight and labels in the agent's window |
| `enable_skills` / `skills_require_sandbox` | on / on | Custom skills |
| `enable_apps` | on | Mac apps & Shortcuts |
| `screen_context_enabled` / `screen_every_minutes` / `screen_retention_minutes` / `screen_blocklist` | off / 5 / 120 / password managers, Messages, WhatsApp, Signal, FaceTime | Screen context |
| `file_roots` | ~/Downloads, ~/Desktop, ~/Documents | Files connector boundary |
| `brief_time` / `dream_time` / `check_every_minutes` | 08:00 / 03:00 / 30 | Proactive schedule |
| `quiet_start` / `quiet_end` / `max_nudges_per_day` | 22:00 / 07:30 / 6 | Interruption policy |
| `avatar_enabled` | off | Face with lip-sync (browser playback) |
| `wake_word_enabled` / `wake_phrases` / `wake_model` | off / (none) / whisper-tiny.en | Wake word |
| `stt_model` / `tts_voice` / `tts_rate` | whisper-large-v3-turbo / system / 190 | Voice |

---

## 13. Testing and known limits

- **Automated tests:** 219 pytest tests (two real agents in one process pair and exchange encrypted messages) (a fake Google OAuth and Gmail server covers sign-in, refresh, revocation and payloads) (one drives a real headless Chromium against a local test site when Playwright and Chromium are available; CI skips it) run against a **fake Ollama** and a **fake osascript runner**:
  - the fake Ollama gives deterministic hashed embeddings, a rule-based judge and rule-based tool calls;
  - the fake osascript runner returns canned app outputs;
  - fake STT and TTS cover voice.

  They cover decisions, memory, the tool loop with approvals, scopes, danger tier, audit tampering, the scheduler's catch-up/defer/quiet-hours/cap behaviour, nudges, dream merging, WAV handling, the voice endpoints and the CLI.
- **Browser tests:** Playwright runs against the real UI, including a fake microphone.
- **CI:** synthiq's `.github/workflows/local-agent.yml` runs the suite on Ubuntu and macOS-14 (Python 3.11–3.13) and on Windows (3.12), parses `install.ps1`, and builds and smoke-installs the wheel. Tests that drive a `/bin/sh` stand-in for Chrome or check POSIX file modes are skipped on Windows; the real bubblewrap confinement test runs where `bwrap` works.
- **Not covered by automated tests:** the real AppleScripts against the Apple apps, real model quality, and real audio. These are verified by the manual checklists in `TESTING.md` on the target Mac.

Known limits:
- The decision percentages aren't calibrated probabilities (see 4.8).
- Without calendar Full Access, repeating events are expanded from their rules. A moved single occurrence can appear at both times, and rules dateutil can't parse are skipped.
- Mail search covers the Inbox only.
- Driving unknown app windows with a 4B model is unreliable; Shortcuts are the dependable path. `entire contents` can be slow on large windows.
- Browser tasks with a 4B model work for short flows; long checkouts and sites with bot checks often fail. The element list is capped at 120 per page.
- WhatsApp reading uses an undocumented local database and only sees chats synced to WhatsApp Desktop. WhatsApp replies must be sent by the user.
- Proactivity runs only while the Mac is awake and the agent is running.
- Notifications are attributed to Script Editor (macOS).
- Windows: skills that run scripts are refused (no sandbox yet); not yet tried on a real PC.

### 13.1 Windows and Linux (Step 7g)

One code base; platform differences sit behind small selectors rather than a separate port, so every feature keeps one implementation and one set of tests.

| Concern | macOS | Windows | Linux | Where |
|---|---|---|---|---|
| Speech to text | mlx-whisper (Apple Silicon) | faster-whisper, CPU int8 | faster-whisper | `voice/stt.make_stt` |
| Speech out / avatar audio | `say` | pyttsx3 (SAPI voices) | pyttsx3 (eSpeak) | `voice/tts.make_tts` |
| Notifications | AppleScript `notify` | PowerShell toast | `notify-send` | `notify.py` |
| Skill sandbox | `sandbox-exec` profile | none: script skills refused | bubblewrap | `skills.run_skill` |
| Start at login | LaunchAgent plist | Startup-folder `.cmd` | XDG autostart `.desktop` | `cli.autostart` |
| Process control | signals | psutil terminate/kill | psutil | `cli.stop` |
| Chrome | /Applications | Program Files / LocalAppData | PATH | `browser.find_chrome` |
| Secrets | Keychain | Credential Manager (keyring) | Secret Service, else 0600 file | `vault.py` |
| Data folder | ~/Library/Application Support | %LOCALAPPDATA% | ~/.local/share | `platformdirs` |

Why these choices:
- **faster-whisper** is the fastest CPU Whisper with no ffmpeg dependency for raw arrays; MLX stays on Apple Silicon because it uses the GPU. The configured model name (often an MLX repo) is mapped to a size, and large models fall back to `small` because they are too slow on CPU.
- **Notification text goes through environment variables** (`LA_TITLE`, `LA_BODY`) and `notify-send --`: message content (which can come from email or chats) is never parsed as PowerShell or as a flag.
- **bubblewrap**: read-only root, private `/tmp`, `--unshare-net` unless the skill declares network, tmpfs over private folders (SSH, cloud credentials, browser profiles, keyrings, the agent's own data), then only the skill folder (read-only) and its `work/` (writable) bound back. Windows has no comparable unprivileged sandbox in the standard library, so script skills are refused there rather than run unconfined.
- **Apple-only connectors** (EventKit/AppleScript apps, Messages, screen OCR, Mac apps) are not emulated; `doctor` names them on other platforms.

Next on the roadmap: see `PLAN.md`.
