# Plan: A local, on-laptop personal agent in the style of Muse and Instinct

## Context

The goal is a personal AI agent like **Meta Muse** (launched 8 Sep 2026; Mac app 17–18 Sep) and **Instinct** (Spear Street Technology, invite-only texting/calling agent) that runs **entirely on the user's laptop** with **local small language models (SLMs)**. A **Jev-style decision model** makes the first call on every input: what it is, which tool to use, whether it needs approval, and whether it's worth interrupting the user. Both products run in the cloud on frontier models with an always-on VM. This plan maps each of their features to what a 16 GB+ Apple Silicon Mac can do and says plainly where it can't.

Decisions already made: **Apple Silicon Mac, 16 GB+ first**; a **new standalone project** (not part of Synthiq); autonomy is **act with approvals** (Muse-style scoped approvals).

---

## 1. What the two products do (research summary)

### Meta Muse
- Agent app on web (muse.ai), iOS/Android, **WhatsApp**, and **Mac**. Smart glasses are on the roadmap. Runs on the Muse Spark model.
- Each user gets an always-on **Secure cloud VM**: Linux, its own browser, cron jobs, **concurrent sub-agents**, and it can compile code and build custom **Skills**. Sandboxed with systemd-nspawn.
- **Browser sub-agent** that works on the **accessibility tree**, not the raw DOM.
- **Memory**: Markdown plus Postgres with **384-dim embeddings**. A nightly **"dream" job** reviews conversations and writes notes about the user. An **identity view** shows what it stores, and the user can tell it to forget.
- **Connectors**: email, calendar, payments, health/fitness, smart home, dining, shopping, music, events. Partners include Walmart, Best Buy, Gap, Sephora, PayPal, Notion, GitHub and Box, and more than 1,500 developer connector applications arrived in the first week.
- **Actions**: send email, book travel, shop and check out (**Stripe Link single-use cards**), fill forms, summarise documents, make PDFs and spreadsheets, schedule reminders.
- **Mac app**: acts in native Mac apps (Files, Messages, Calendar, Notes, Mail), e.g. tidies Downloads, finds lost files, summarises messages.
- **Approvals queue** with scopes (one-time, session, task, time-bounded, persistent), an **activity log** and an **audit trail**. The agent never sees passwords or card numbers.
- Users can set the agent's name, avatar and tone. The working browser stays visible. Context carries across devices (start on phone, finish on laptop or WhatsApp).
- Teased: a **video-chat digital avatar**, more shopping partners, glasses integration.
- Limits: US-only, cloud-only (no local data residency), Amazon blocks it from shopping.

### Instinct
- **No app.** Users reach it by **iMessage, WhatsApp or a phone call**. Replies are terse and use tapbacks/reactions and **voice notes**.
- Runs on a **persistent cloud computer**, "trained to use a phone and a computer" the way a person does.
- Builds context from **email, messaging, screen, audio and location**, so it knows what "the usual place" means.
- **Proactive**: follows up on dropped threads, reminds about deadlines, and texts or calls first.
- Tasks: bookings, rides, cleaning up the inbox, shopping, flights, follow-ups, haggling over bills, **filling forms from memory** (e.g. visa applications), booking a handyman.
- **Vault** of logins, **Stripe Link one-time cards** with a spending limit the user approves.
- **Trusted Person network**: your Instinct can talk to the Instincts of people you trust to arrange plans.
- Risks reported in beta: data kept after disconnecting, a **prompt injection via email**, an unapproved action, and terms that let it **enter binding agreements**.

### Jev-style decision models (the "first decision" layer)
- **Jev** (Typesafe AI) is a closed "System 1" model. It is **non-autoregressive**: one forward pass over (state + allowed actions) returns **calibrated probabilities**, with no text generation and no JSON parsing.
- **Open, local alternatives** (Apache-2.0):
  - **Laya**: ModernBERT-large 421M; about 8–10 ms for 5 questions on a 4090; also a 322M multilingual version.
  - **von**: 395M ModernBERT; under 15 ms on CPU per its README (its own table shows 0.34 s on a 4-vCPU CPU and 23 ms on an A10G GPU); supports Apple MPS; `von serve`.
  - **NeoHorse-Jev-4B** and **Open-Jev-27B**: larger.
  - **Ollaya**: an Ollama-style local runner that speaks Typesafe's `/v1/systemone` format and uses GGUF via llama.cpp, so it runs on Metal.
- Question types: **choice** (pick 1 of K), **noul** (calibrated yes/no), **score** (position on an ordinal scale).
- Caveat: the ecosystem is a few months old and the benchmarks are self-reported. Phase 0 must measure accuracy on *our* labels.

---

## 2. Feature feasibility matrix (local, 16 GB Apple Silicon)

✅ feasible · 🟡 partial or with caveats · ❌ not feasible locally

| # | Feature (source) | Local | How / why not |
|---|---|---|---|
| 1 | Chat UI (both) | ✅ | Desktop app with streaming chat |
| 2 | Persistent memory, identity view, "forget" (Muse) | ✅ | SQLite + sqlite-vec + Markdown identity files; hard delete covers vectors too |
| 3 | Nightly "dream" consolidation (Muse) | ✅ | launchd job when **charging and idle**; the SLM writes and updates `about-me.md` and preference notes |
| 4 | Resolving "the usual place" (Instinct) | ✅ | Entity memory (places, people, routines) filled from mail, calendar and messages |
| 5 | Email / calendar / contacts / notes / files (both) | ✅ | Mac bridge: EventKit, Contacts, Mail/Notes through AppleScript or ScriptingBridge, plus Gmail/Graph/IMAP with OAuth loopback redirect |
| 6 | Acting inside native Mac apps (Muse Mac) | 🟡 | Accessibility (AX) API through a Swift helper. Reliable for scripted skills; open-ended UI driving with a 4–8B model is noticeably weaker than a frontier model |
| 7 | Browser sub-agent on the accessibility tree (Muse) | 🟡 | Playwright with a dedicated Chrome profile and AX snapshots. Works on simple flows; long multi-step checkouts, CAPTCHAs and bot detection lower success. Amazon-style blocks still apply |
| 8 | Always-on VM, cron, long background jobs (both) | 🟡 | launchd jobs and `pmset` scheduled wakes, but **nothing runs while the lid is closed or the Mac is off**. Missed jobs run on wake |
| 9 | Concurrent sub-agents (Muse) | 🟡 | RAM fits **one** generative model at a time. Sub-agents queue and share it; the decision model runs alongside |
| 10 | Approvals queue with 5 scopes + audit log (Muse) | ✅ | Policy engine; append-only, hash-chained audit log |
| 11 | Vault of credentials (Instinct) | ✅ | macOS **Keychain**; the model never sees secrets, the tool layer injects them |
| 12 | Single-use payment cards (both) | 🟡 | Stripe Link agent cards need a business integration. v1: the agent fills the cart and the **user pays**. Later: an optional virtual-card provider API |
| 13 | Partner commerce connectors (Walmart, PayPal…) (Muse) | ❌ | These are business partnerships. Browser automation is the only route, and fragile |
| 14 | Make PDFs and spreadsheets, summarise documents (Muse) | ✅ | Python libraries; the SLM writes the content |
| 15 | Reminders and scheduling (both) | ✅ | EventKit Reminders plus the app's own scheduler |
| 16 | Custom Skills (Muse) | ✅ | A skill is a folder with `SKILL.md`, scripts and a manifest, run in a sandbox (`sandbox-exec` profile plus a separate user dir) |
| 17 | Agent name, avatar, tone (Muse) | ✅ | Persona settings in the system prompt |
| 18 | Realtime video-chat avatar (Muse, teased) | 🟡/❌ | A 2D avatar with viseme lip-sync from TTS is ✅. A **photoreal realtime avatar alongside an LLM in 16 GB is ❌** |
| 19 | Smart glasses (Muse) | ❌ | Closed Meta hardware platform |
| 20 | WhatsApp channel (both) | 🟡/❌ | The official API is WhatsApp Business Cloud, which needs a public webhook (not local). Unofficial clients break the ToS. **Use Telegram instead** (long-polling needs no server) |
| 21 | iMessage channel (Instinct) | 🟡 | On the Mac: read `chat.db` (needs Full Disk Access), send through AppleScript. Needs a **second Apple ID** for the agent, works only while the Mac is awake, and can break with macOS updates |
| 22 | Voice conversation on the laptop (Instinct "call it") | ✅ | Silero VAD → WhisperKit / whisper.cpp → SLM → Kokoro TTS. About 1–2 s per turn, push-to-talk or wake word |
| 23 | Real phone calls to/from the agent (Instinct) | ❌ (local-only) | Needs telephony (e.g. Twilio) and a public endpoint, so it's cloud. A possible opt-in add-on later |
| 24 | Agent phones businesses or haggles bills (Instinct) | ❌ | Needs telephony, realtime voice-model latency and legal disclosure/consent rules, and a small model is too risky for this. Excluded |
| 25 | Ride hailing (Instinct) | 🟡/❌ | No public consumer ordering API. Browser automation on the web app at best |
| 26 | Proactive nudges: dropped threads, deadlines (Instinct) | ✅ | **Where the decision model fits best**: `noul(should_nudge)` + `score(urgency)` over events, with a calibrated threshold and quiet hours |
| 27 | Screen context (Instinct) | ✅ | Opt-in ScreenCaptureKit every N seconds + **Apple Vision OCR** (on-device, cheap), private apps excluded, auto-expiry |
| 28 | Ambient audio context (Instinct) | 🟡 | Always-on transcription costs battery and raises privacy issues. **Meetings only, opt-in per session** |
| 29 | Location context (Instinct) | 🟡 | CoreLocation on a Mac is Wi-Fi based and coarse. Good enough for home/office/travelling |
| 30 | Filling forms from memory (Instinct) | ✅ | Memory → field mapping, then **mandatory review** before submitting |
| 31 | Trusted Person agent-to-agent network (Instinct) | 🟡 | Needs a transport between two machines that are both online: end-to-end encrypted messages over a relay (Matrix or Tailscale) using an A2A-style protocol. Later phase |
| 32 | Cross-device continuity (Muse) | 🟡 | The phone reaches the laptop through Telegram or a Tailscale PWA. **Nothing works when the laptop is off** |
| 33 | Health/fitness, smart home (Muse) | 🟡 | HomeKit through Shortcuts ✅. Apple Health data stays on the iPhone, so only an import ❌/🟡 |
| 34 | Frontier-level reasoning (Muse Spark) | ❌ | A local 4–8B model is not frontier. Mitigate with the decision router, scripted skills, constrained decoding, and an **optional, off-by-default cloud escalation (bring your own key)** |
| 35 | Privacy: no ads, no training on user data (both) | ✅ | The local-first design does this by itself. Note it is **stronger than both products** |
| 36 | Prompt-injection resistance (Instinct incident) | 🟡 | `noul(contains_injection)` on all external content, a quarantined reader LLM, capability tokens, and approvals. Reduces risk but can't eliminate it |
| 37 | Binding agreements on the user's behalf (Instinct ToS) | Policy ❌ | Never allowed. Signing or accepting terms always needs a human |

---

## 3. Architecture

```
┌──────────── Tauri 2 desktop app (React UI) ─────────────┐
│ Chat · Approvals queue · Activity log · Memory/identity │
│ Skills · Connectors · Persona · Model manager · Privacy │
└───────────────▲─────────────── unix socket / localhost ─┘
                │
┌───────────────┴── core daemon (Python 3.12, FastAPI) ──────────────────┐
│ Event bus ← ingest: user msgs, Telegram/iMessage, mail, calendar,      │
│              screen OCR, voice, timers, file changes                    │
│ 1. DECIDE  (Jev-style, <50 ms)  → intent, tool, risk, urgency, nudge?  │
│ 2. ROUTE   by confidence/complexity → fast path | SLM agent | ask user │
│ 3. AGENT   SLM planner/executor, grammar-constrained tool calls        │
│ 4. POLICY  approvals engine (scopes) + audit log                       │
│ 5. MEMORY  SQLite + sqlite-vec + Markdown identity; "dream" job        │
│ Tools = MCP servers  ·  Model manager (load/unload, memory budget)     │
└───────▲──────────────────────────▲─────────────────────────▲──────────┘
        │ MCP stdio                │ HTTP                    │
┌───────┴─────────┐   ┌────────────┴─────────┐   ┌───────────┴─────────┐
│ mac-bridge      │   │ Model runtimes       │   │ Browser worker       │
│ (Swift): AX,    │   │ Ollaya (decision),   │   │ Playwright + AX      │
│ ScreenCaptureKit│   │ MLX-LM / llama.cpp,  │   │ snapshots, own       │
│ Vision OCR,     │   │ WhisperKit, Kokoro,  │   │ Chrome profile       │
│ EventKit, Keych.│   │ embeddings           │   │                      │
│ iMessage, CoreLoc│  └──────────────────────┘   └──────────────────────┘
└─────────────────┘
```

### Model stack and memory budget (16 GB, about 9 GB for the app)

| Role | Default (16 GB) | 24 GB+ | Runtime | RAM |
|---|---|---|---|---|
| Decision ("first call") | **Laya-421M** or **von-395M** | same | Ollaya / `von serve` (MPS) | ~1 GB, always loaded |
| Agent / planner SLM | **Qwen3-4B** or **Gemma 4 E4B** (4-bit) | **Qwen3-8B** / Qwen3-30B-A3B | MLX-LM (llama.cpp + GBNF fallback) | 3–5 GB, loaded on demand |
| Fast text (summaries, titles) | Qwen3-1.7B | same | MLX | ~1.2 GB |
| Embeddings | 384-dim (bge-small class, like Muse) | same | sentence-transformers on MPS | ~0.2 GB |
| Speech to text | Whisper large-v3-turbo (WhisperKit) | same | CoreML | ~1.5 GB, on demand |
| Text to speech | Kokoro-82M | same | MLX/ONNX | ~0.3 GB |
| Screen understanding | Apple Vision OCR + AX tree; small VLM only as fallback | Qwen2.5-VL-3B / Fara-7B | MLX | 0–3 GB, on demand |

The model manager enforces the budget. Only one large model is resident at a time, and models unload after idle time or under memory pressure.

### Decision layer: where the Jev-style model is used
Every event becomes a `state` (JSON with the message or email, recent context and memory snippets) plus typed questions, all answered in **one pass**:
- `choice intent`: {chit-chat, quick_answer, task, schedule, memory_write, memory_query, computer_action, ignore}
- `choice skill`: top-K candidates from the skills/tool registry, pre-filtered by embedding similarity
- `noul needs_approval`, `noul contains_injection`, `noul needs_clarification`, `noul interrupt_now`
- `score urgency (1–5)`, `score complexity (1–5)`. Complexity picks the 1.7B model, the 4–8B model, or the opt-in cloud escalation.

**Confidence gating**: if max probability < τ (tuned per question on a calibration set), escalate to the SLM to reason it out, or ask the user. Every correction the user makes is stored as a label. **Fallback** if the open models do poorly on our labels: fine-tune our own ModernBERT multi-head classifier (LoRA on MPS) on SLM-generated synthetic data plus logged corrections. The interface stays the same.

### Approvals policy
- Risk tiers: **read** (auto) → **draft** (auto, shown in the activity log) → **send / modify** (approval, scope chosen by the user) → **spend / delete / submit forms / sign up** (always one-time approval, amount shown).
- Scopes as in Muse: one-time, session, task, time-bounded, persistent (persistent only allowed for low tiers).
- The tool layer, not the model, enforces tiers. Each tool declares its tier in its MCP manifest.

---

## 4. Phased delivery

**Phase 0: Feasibility spikes (go/no-go)**
- Decision model: label about 300 real-world events (intent, tool, needs_approval, nudge). Measure accuracy and ECE for Laya and von on an M-series Mac. Target ≥90% intent accuracy and ECE < 0.05.
- SLM tool calling: run 50 scripted tool tasks on Qwen3-4B, Gemma 4 E4B and Qwen3-8B with constrained JSON. Target ≥85% valid-and-correct calls.
- Mac bridge: AX-driven actions in Mail, Calendar, Notes and Finder; ScreenCaptureKit + Vision OCR throughput and battery cost.
- Measure end-to-end voice latency.

**Phase 1: Core**: Tauri shell, core daemon, model manager, decision router, chat with streaming, memory (SQLite + sqlite-vec + Markdown identity), identity view and forget, persona settings.

**Phase 2: Connectors and approvals**: mac-bridge MCP (EventKit, Contacts, Mail, Notes, Files, Keychain), Gmail/Graph OAuth, approvals queue with scopes, hash-chained activity/audit log, PDF/XLSX output.

**Phase 3: Proactivity**: scheduler (launchd + `pmset` wakes, catch-up on wake), event ingest from mail and calendar, nudge pipeline (`should_nudge`, urgency, quiet hours, daily caps), dropped-thread detector, "dream" consolidation job, morning brief.

**Phase 4: Voice**: push-to-talk and wake word, VAD → WhisperKit → SLM → Kokoro, barge-in, voice notes in and out.

**Phase 5: Acting on the computer**: browser worker (Playwright with AX snapshots in a dedicated profile), native Mac app actions over AX, Skills system with sandbox, form filling from memory with mandatory review, opt-in screen context with OCR and app blocklist.

**Phase 6: Messaging channels**: Telegram bot (recommended), iMessage relay (experimental, second Apple ID), terse style, reactions, approvals answered by reply.

**Phase 7: Stretch**: trusted-agent network (end-to-end encrypted relay, A2A-style), 2D avatar with lip-sync, opt-in cloud escalation, opt-in Twilio voice line, Windows/Linux port (UI Automation / AT-SPI, llama.cpp CUDA).

### Proposed repo layout (new project)
```
app/          Tauri 2 + React (chat, approvals, activity, memory, skills, settings)
core/         Python daemon: events/ decide/ llm/ agent/ policy/ memory/ tools/ skills/ scheduler/
mac-bridge/   Swift package → MCP stdio server (AX, ScreenCaptureKit, Vision, EventKit, Keychain, iMessage, CoreLocation)
browser/      Playwright worker
models/       manifests, checksums, download scripts
evals/        decision set, tool-call tasks, scenario scripts, injection red-team set
```
Synthiq offers ideas but no code to reuse. Its chunking (`api/pipeline/chunker.py`) and voice/style extraction (`api/pipeline/voice_extractor.py`) are patterns worth reading for memory ingest and the persona, but they are built on Claude, Voyage and Pinecone and would need rewriting for local models.

---

## 5. Main risks
- **Small-model quality** on open-ended multi-step tasks. Mitigate with the decision router, scripted skills over free-form UI driving, constrained decoding, human approvals, and opt-in cloud escalation.
- **Laptop isn't always on.** Say so in the UI ("runs while your Mac is awake"); catch up on wake.
- **Memory pressure on 16 GB.** A single resident large model, with 4B as the default.
- **Prompt injection** from email and web pages. Injection classifier, quarantined reader, capability-scoped tools, approvals.
- **Platform fragility**: iMessage DB schema, AX changes across macOS versions, site bot detection.
- **Open decision models are new.** Phase 0 gate plus our own classifier as the fallback.

---

## 6. Verification
- `evals/decision`: accuracy, macro-F1 and **ECE** per question type; p50/p95 latency on M-series (target < 50 ms).
- `evals/tools`: success rate across 50+ scripted tool tasks per model.
- `evals/scenarios`: end-to-end scripts (e.g. "reply to the dropped thread from Priya", "book Friday dinner at the usual place", "tidy Downloads") run against a test macOS user with fixture mail and calendar data. Assert the actions taken and that approvals were requested.
- `evals/injection`: red-team corpus (malicious emails and web pages). Target: no unapproved tier-3+ actions.
- Performance: peak RSS under 9 GB on a 16 GB machine; battery drain per hour with screen context on vs off.
- Manual: approvals for every scope type, forget really deletes (rows plus vectors plus Markdown), and the app works fully with networking off (apart from connector sync).

## 7. On approval
Only `akm98074/synthiq` is in scope for this session. On approval, I'll commit this plan as `docs/local-agent/PLAN.md` on branch `claude/charming-curie-j4irpv`, with the sources listed below, and push it. Code scaffolding should go in the new standalone repo once the user creates it and adds it to the session.

---

## Appendix A: Why each 🟡 / ❌ feature is limited

Each entry gives the **root cause** (why the cloud product can do it and a local app can't), **what we ship instead**, and **what would change the verdict**. The numbers match the matrix in §2.

### A.1 Limited by the laptop itself (power, uptime, RAM)

**#8 Always-on VM, cron, long background jobs: 🟡**
- *Root cause:* Muse and Instinct run on servers that never sleep. A laptop sleeps when the lid closes, on battery saver, or when it's shut down. macOS **suspends every third-party process during sleep**: Power Nap only runs Apple's own tasks, and `pmset` scheduled wakes are short, unreliable on battery, and don't work with the lid closed unless an external display and power are attached. Thermal throttling and App Nap also slow background processes.
- *Instead:* launchd agents with `StartCalendarInterval`, a **catch-up queue** that runs missed jobs on wake (with "this was due at 07:00" context), `pmset schedule wake` for important jobs when on AC power, and an honest UI line: "Runs while your Mac is awake."
- *Would change if:* the user adds an always-on home device (Mac mini or a spare machine) as the "agent host". The same daemon runs there and the laptop becomes a client.

**#9 Concurrent sub-agents: 🟡**
- *Root cause:* each Muse sub-agent gets its own share of a datacenter GPU. On 16 GB of **unified memory**, the OS and apps take about 6–7 GB, and a 4-bit 4B model takes about 3 GB weights plus 0.5–2 GB KV cache per context. Two generative models, or two long contexts, push the machine into swap, which kills latency and wears the SSD. Apple GPUs run one batch at a time, so "parallel" sub-agents would just take turns anyway.
- *Instead:* a single resident SLM with a **job queue**. Sub-agents are logical: separate contexts and goals, run one after another, with prefix (KV) caching where the runtime supports it. The decision model (~1 GB) runs alongside at all times.
- *Would change if:* 32 GB+ RAM (two 4B models or one 8B with large contexts), or batched serving via MLX/llama.cpp parallel slots on 24 GB+.

**#18 Photoreal realtime video avatar: 🟡 (2D) / ❌ (photoreal)**
- *Root cause:* a realtime talking head (LivePortrait/SadTalker-class) needs 25+ frames per second of diffusion or warping. That alone saturates an M-series GPU and needs 2–4 GB, competing with the SLM, Whisper and TTS. The combined latency (STT + LLM + TTS + video) on one laptop GPU breaks conversation (>3 s).
- *Instead:* a **2D or Live2D-style avatar** driven by visemes from the Kokoro TTS timing data. It costs almost nothing.
- *Would change if:* Apple Neural Engine-optimised avatar models appear, or the machine is an M-series Max/Ultra with 64 GB+.

**#34 Frontier-level reasoning: ❌**
- *Root cause:* Muse Spark and Instinct's models are frontier-scale and probably 100B+ parameters. On a 16 GB machine, practical limits are about 4–8B parameters at 4-bit. In practice that means reliable **single-step** tool calls, but noticeably more drift on 10+ step plans, long-context recall and ambiguous instructions.
- *Instead:* (1) the decision model handles the easy majority of inputs without generation; (2) **scripted skills**: tested procedures where the SLM fills parameters instead of planning from scratch; (3) grammar-constrained JSON for zero malformed calls; (4) short, focused contexts built from memory retrieval; (5) **opt-in cloud escalation** (bring your own key) for tasks the router scores at complexity ≥4, showing the user exactly what leaves the device.
- *Would change if:* 32–64 GB machines (Qwen3-30B-A3B / 32B class), or future SLM generations. The gap shrinks every few months but won't close for long-horizon tasks.

### A.2 Limited by platform APIs and closed ecosystems

**#6 Acting inside native Mac apps: 🟡**
- *Root cause:* the macOS Accessibility (AX) API exposes UI trees, but **apps vary widely**: Electron and custom-drawn apps expose sparse or unlabeled trees, and element IDs change between app versions. Driving arbitrary UI needs strong visual and spatial reasoning, where 4–8B models (even Fara-7B-class GUI models) trail frontier models. Muse's Mac app is backed by its cloud model.
- *Instead:* use **app-specific APIs first** (EventKit, Contacts, AppleScript/ScriptingBridge for Mail, Notes, Finder), and use AX only for well-labeled apps through tested skills. Open-ended "click around" mode is opt-in, step-by-step, and shows each action before running it.
- *Would change if:* better small GUI-agent models (the 7B class is improving fast), or 24 GB+ to run a dedicated GUI-agent model next to the planner.

**#7 Browser sub-agent: 🟡**
- *Root cause:* sites use **bot detection** (Cloudflare Turnstile, Akamai, CAPTCHAs), change their DOM often, and some explicitly block agents (Amazon blocked Muse). Long checkouts (10–30 steps with modals, address forms and 3-D Secure) compound per-step error rates: at 95% per step, a 20-step flow succeeds only about 36% of the time.
- *Instead:* a Playwright worker using the user's **own logged-in Chrome profile** (looks like the user, not a datacenter IP, which is actually an advantage over cloud agents), AX-tree snapshots to cut tokens, per-site **skills** for frequent sites, and **pausing for the human** on CAPTCHAs and payment.
- *Would change if:* sites publish agent APIs or MCP endpoints (a growing trend), which turns browsing into API calls.

**#13 Partner commerce connectors (Walmart, Best Buy, PayPal…): ❌**
- *Root cause:* these are **business partnerships** with private APIs, contracts and liability arrangements negotiated by Meta. An individual's local app can't get the same API access.
- *Instead:* browser automation (#7) for search and cart building; public APIs where they exist (Notion, GitHub and Box have public OAuth APIs, so those connectors **are** feasible ✅).
- *Would change if:* retailers publish open agent-commerce protocols that any client can use.

**#12 Single-use payment cards: 🟡**
- *Root cause:* Stripe Link's agent-card issuing is offered to **platforms** (Meta, Spear Street) under a commercial agreement with KYC, not to end-user desktop apps. Card issuing needs a regulated issuer relationship.
- *Instead:* v1: the agent builds the cart and **the user pays** in the browser (autofill from the Keychain/Safari wallet, the user clicks Pay). v2: optional integration with a consumer virtual-card provider whose API the user signs up for themselves (US-only providers exist), with per-merchant and per-amount limits enforced in our approval policy.
- *Would change if:* consumer-facing agent payment APIs become generally available.

**#19 Smart glasses: ❌**
- *Root cause:* Ray-Ban Meta glasses run Meta's closed platform; third-party apps can't take over the assistant pipeline or stream camera and mic freely to a local laptop service.
- *Instead:* none in v1. Phone-based voice through Telegram voice notes is the mobile path.
- *Would change if:* Meta opens a device SDK, or open-hardware glasses with a Bluetooth audio/camera API are used.

**#20 WhatsApp channel: 🟡 / ❌**
- *Root cause:* the only sanctioned API is the **WhatsApp Business Platform (Cloud API)**. It needs a business account, a verified phone number, and a **public HTTPS webhook** for incoming messages, so it's inherently cloud, and Meta's policies restrict general-purpose AI chatbots on it. Unofficial libraries that pretend to be WhatsApp Web **break the ToS** and risk getting the user's number banned.
- *Instead:* **Telegram Bot API** using long polling: the laptop pulls messages, so there's no public server, it's free and the API is official. It supports voice notes, reactions and inline buttons (perfect for approvals).
- *Would change if:* the user accepts a small cloud relay (webhook to an encrypted queue the laptop drains), which removes "local-only" for that channel.

**#21 iMessage channel: 🟡**
- *Root cause:* Apple provides **no iMessage API**. The only local approach is reading `~/Library/Messages/chat.db` (needs Full Disk Access; the schema changes with macOS releases and message bodies sit in `attributedBody` blobs) and sending through AppleScript to Messages.app. For the user to "text their agent", the agent needs its **own Apple ID** signed into Messages on that Mac, which means a second account. It only works while the Mac is awake (#8).
- *Instead:* experimental, opt-in relay, clearly labeled as such; Telegram is the default.
- *Would change if:* Apple ships an official Messages extension or agent API (Apple Intelligence App Intents are moving in this direction).

**#25 Ride hailing: 🟡 / ❌**
- *Root cause:* Uber and Lyft don't offer public **consumer ride-request APIs** (Uber's old Rides API is closed to new apps). Ordering through their web apps runs into bot detection and needs live payment confirmation.
- *Instead:* the agent works out pickup, destination and timing from the calendar and memory, opens the ride app's web flow or a **deep link** pre-filled for the user, and sets reminders ("leave in 20 min").
- *Would change if:* providers publish agent or MCP integrations.

**#29 Location context: 🟡**
- *Root cause:* Macs have no GPS. CoreLocation uses **Wi-Fi positioning**, which is accurate to about 20–100 m when Wi-Fi is on and unavailable when it isn't. A laptop also stays put most of the day, so it isn't a good proxy for where the user is (unlike the phone Instinct reads).
- *Instead:* coarse place detection (home/office/travelling) from Wi-Fi SSID + CoreLocation + calendar. That's enough for "the usual place" and for travel-aware reminders.
- *Would change if:* a companion phone app (iOS Shortcuts automation posting location over Tailscale) is added.

**#33 Health/fitness and smart home: 🟡**
- *Root cause:* **Apple Health data lives on the iPhone/Watch**. HealthKit has no data store on macOS, so a Mac app can't read it. Other fitness services (Strava, Oura) have cloud APIs that require OAuth with a redirect, which is doable but goes through their cloud. Smart home: HomeKit isn't directly available to a Mac command-line or desktop daemon; you go through Shortcuts.
- *Instead:* HomeKit through **Shortcuts** (`shortcuts run "…"`) ✅; a manual or periodic **Health export import** (XML) 🟡; optional cloud OAuth connectors for fitness services.
- *Would change if:* a companion iOS app is built to sync HealthKit data over the local network.

### A.3 Needs cloud infrastructure or telephony

**#23 Real phone calls to/from the agent: ❌ (local-only)**
- *Root cause:* a phone number needs a **carrier/telephony provider** (Twilio, Telnyx). Incoming calls hit the provider's cloud, which must reach your app through a **public webhook / media stream (WebSocket)**. A laptop behind NAT, often asleep, can't reliably take that. Realtime voice also needs <800 ms turn latency for natural conversation, and a local STT → LLM → TTS chain gets about 1–2 s.
- *Instead:* on-device voice mode (#22) and **Telegram voice notes** from the phone (asynchronous, so latency doesn't matter).
- *Would change if:* the user opts into a Twilio number + Tailscale Funnel/ngrok tunnel (no longer local-only, needs an always-awake host), plus faster local speech-to-speech models.

**#24 Agent calls businesses or haggles bills: ❌**
- *Root cause:* everything in #23, plus **legal**: many jurisdictions require disclosing AI callers and getting consent for recording (two-party consent states, US FCC rulings on AI-voice robocalls, the EU AI Act transparency duties). Negotiation is adversarial and open-ended, which is exactly where a 4–8B model is least reliable, and a mistake can commit the user to something.
- *Instead:* the agent **prepares** the call: a script, account details, target outcome and fallback positions shown on screen while the *user* calls. Or it drafts an email/chat-support message to send after approval.
- *Would change if:* never in a local-only build; possible later as a cloud add-on with explicit disclosure and the user listening in.

**#31 Trusted Person agent-to-agent network: 🟡**
- *Root cause:* two laptops agents must find and reach each other across NATs **while both are awake**. Instinct solves this with central servers. Peer-to-peer needs identity (whose agent is this?), key exchange, a relay for offline delivery, and a negotiation protocol that resists one agent manipulating the other (prompt injection between agents).
- *Instead (later phase):* end-to-end encrypted messages over an existing relay network (Matrix or a Tailscale tailnet shared between trusted people), an A2A-style typed protocol (propose_times / accept / decline, never free-form instructions), every incoming agent message treated as **untrusted data**, and commitments requiring the user's approval.
- *Would change if:* an open agent-to-agent standard with discovery matures. A small relay server makes delivery asynchronous and reliable.

**#32 Cross-device continuity: 🟡**
- *Root cause:* Muse's state lives in the cloud, so every device sees it. Here the **only copy is on the laptop**. When it's off or asleep, the phone has nothing to talk to.
- *Instead:* Telegram (messages queue on Telegram's servers until the laptop wakes and answers) and an optional **Tailscale PWA** for the full UI from the phone when the laptop is awake.
- *Would change if:* the always-on home host (see #8) is used, or end-to-end encrypted sync to a user-owned storage bucket is added.

### A.4 Limited by privacy, battery or safety design choices

**#28 Ambient audio context: 🟡**
- *Root cause:* always-on transcription keeps the mic, the Neural Engine/GPU and Whisper running around the clock. That means **double-digit percent battery per hour** and constant heat. Legally, recording other people without consent is restricted in many places. The macOS mic indicator would also be permanently on, which users find unsettling.
- *Instead:* **meeting mode**, started per session by the user or by a calendar event (with a consent reminder), plus push-to-talk and wake word. Transcripts are summarised into memory and the raw audio is deleted.
- *Would change if:* low-power on-device keyword spotting on the Neural Engine plus explicit legal and consent UX make an "always listening for the wake word only" mode acceptable.

**#36 Prompt-injection resistance: 🟡**
- *Root cause:* any model that reads untrusted text (emails, web pages, other agents) can be steered by instructions hidden in it. This is an **unsolved research problem**, and Instinct had a real incident. Small models are generally *more* susceptible than frontier models.
- *Instead:* layered defence: (1) the `contains_injection` decision check on all external content; (2) a **quarantined reader**: the model that reads untrusted content cannot call tools and only returns structured data; (3) capability-scoped tools (a "summarise email" task can't get a "send money" tool); (4) approvals for anything at tier 3 or above; (5) a red-team eval suite in CI.
- *Would change if:* never fully. This stays 🟡 for every agent product, cloud or local.

**#37 Binding agreements on the user's behalf: ❌ by policy**
- *Root cause:* not technical. Instinct's terms let it enter contracts, which reviewers flagged as a major risk. Given small-model error rates and the legal exposure, we **choose** not to allow it.
- *Instead:* accepting terms, signing, subscribing and making purchases are always one-time approvals that show the full terms and amount.

## Sources
- Muse: techcrunch.com/2026/09/08/meta-debuts-its-muse-ai-agent-will-consumers-trust-it · spinnable.ai/blog/what-is-meta-muse-guide · shop.zimaspace.com/blogs/tech-ai-hub/meta-muse-secure-vm-always-on-ai-agent · aiweekly.co/alerts/meta-ships-muse-for-mac-agent-now-acts-in-native-macos-apps · discoverai.tools/articles/meta-muse-personal-ai-agent-security-privacy-2026
- Instinct: eesel.ai/blog/instinct-ai-review · layer3labs.io/guides/instinct-ai-explained · gyld.ai/blog/instinct-ai-review-impressive-agent-real-privacy-risks · thursdai.news/companies/instinct
- Decision models: github.com/wfzyx/von · oflight.co.jp/en/columns/ollaya-local-decision-models-jev-ollama-2026 · regolo.ai/jev-and-system-one-models-benchmarks-open-source-alternatives-and-when-to-use-them · tryfriday.ai/blog/neohorse-jev-4b-open-decision-model
- Local models and computer use: ertas.ai/best/best-small-llm-for-local-deployment · star-history.com/blog/computer-use · pypi.org/project/agent-eyes
