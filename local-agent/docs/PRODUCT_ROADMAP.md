# From project to product: competing with Muse and Instinct

*October 2026*

> **All of Muse and Instinct, running on your own computer.**
> **Full control. Real privacy. Zero token cost.**

Shorter variants, for different surfaces:

- App Store / site hero: *"Your AI agent. Your computer. Your rules."*
- Comparison ads: *"Everything Muse and Instinct do, without sending them your life."*
- Pricing page: *"No tokens. No meter. No cloud required."*

---

## 1. Where we stand

LocalAIAgent 0.15.0 already matches most of Muse's and Instinct's feature list on a single computer (see `OVERVIEW.md` §5). It also has advantages neither offers:

- visible decision probabilities;
- an egress-free default;
- end-to-end encrypted agent-to-agent without a server;
- no running cost.

Four gaps remain between a strong project and a product people choose over them:

| Gap | Why it matters to users | Muse/Instinct today |
|---|---|---|
| **1. Always there** | "It didn't reply because my laptop was asleep" kills the habit. | Cloud VMs never sleep. |
| **2. Smart enough** | Long tasks with a 4B model fail more often than with a frontier model. | Frontier models. |
| **3. Reaches everything** | 1,500+ connectors and shopping partners vs our ~15 integrations. | Partner ecosystems, one-time cards. |
| **4. Feels like a product** | Terminal install, Python, permissions granted to "Terminal". | Polished apps on every device. |

A fifth item is our moat, not a gap: **trust**. It has to be turned from architecture into something users can see (`TRUST_UX.md`) and something that is actually secure (`SECURITY_REVIEW.md` P0/P1).

---

## 2. Capabilities to build

### Pillar A: Trust you can verify (our moat; do first)

| Capability | What it is | Why it wins |
|---|---|---|
| **Security P0/P1 fixes** | Authenticated local API, data-flow taint, executable blocking, payload-visible approvals, per-target grants | Prerequisite for any public release. |
| **Privacy Control Center** | One screen: every capability, OS permission, last use, on/off, "turn off and forget"; trust presets (Observer / Assistant / Agent) | Users can *see* and *change* what the agent can do. |
| **Egress ledger + weekly privacy receipt** | Every byte that left the machine, with the exact content | Proves the local claim. Neither competitor can show this. |
| **"Why?" on everything** | Explanation card for every action and nudge: decision probabilities, sources, the rule that allowed it | Explainability as a feature, not a doc. |
| **Agent firewall mode** | A switch that blocks all outbound network except Ollama and explicitly approved destinations; enforced in-process and optionally with the OS firewall | "Airplane mode for your AI". |
| **Open core + reproducible builds + third-party audit** | Publish the agent core, sign releases, commission an audit | Trust from people who can check. |
| **Hard limits** | No binding agreements, no money movement, nothing irreversible by phone, ever | The opposite of Instinct's terms. |

### Pillar B: Always available, on every device (closes Gap 1)

| Capability | What it is | Notes |
|---|---|---|
| **Home node mode** | Run the agent on an always-on machine (Mac mini, home PC, NAS, a small Linux box) and use laptops and phones as clients | The same package; `localagent serve --home`. Most households have or can buy a $500 always-on box: still zero token cost. |
| **Companion apps (iOS, Android)** | A thin client: chat, approvals with full payload, voice, push notifications, share sheet, App Intents / Siri | Connect over Tailscale or our **blind relay** (below). |
| **Blind relay** | An optional rendezvous server that forwards **end-to-end encrypted** packets between your devices and your friends' agents. It can't read content and stores nothing beyond a short offline queue | It solves NAT and sleep for phones and peers without breaking privacy. The relay can be self-hosted. |
| **Multi-device sync** | Laptop ↔ home node sync of memory and settings (CRDT, E2E encrypted) | Start on the laptop, continue on the phone, as Muse does. |
| **Wake-on-demand** | Wake-on-LAN or `pmset` scheduling for proactive jobs; a "keep awake while charging" option | Mitigates sleep for laptop-only users. |
| **Phone context (opt-in)** | Location, focus mode and calendar from the phone app | Brings back Instinct's "the usual place" from the device that actually knows. |

### Pillar C: Smarter on small models (closes Gap 2)

| Capability | What it is | Expected effect |
|---|---|---|
| **Hardware-aware model tiers** | Auto-select: 8 GB → 1.7B/4B; 16 GB → 4B/8B; 32 GB+ → 14B–32B (MLX/llama.cpp); a home node with a GPU runs larger models | Better quality for users with better hardware. |
| **Fine-tuned tool-calling model** | LoRA on Qwen-class 4–8B using our tool schemas and synthetic and corrected traces (from opted-in users only, locally) | Fewer wrong tool calls and malformed arguments. |
| **Plan → act → verify loop** | Explicit plans with checkpoints; verify each step's result before the next; retry with a narrower prompt | Long tasks stop drifting. |
| **Learned recipes ("do it like last time")** | A successful multi-step run (e.g. a Safeway price check) becomes a deterministic recipe the agent replays, with the model handling only the variable parts | Turns 20 fragile steps into one reliable one. Shareable as skills. |
| **Real System-1 decision model** | Distil the prototype + judge decisions and user corrections into a small Jev-style model (ModernBERT class) | Calibrated probabilities, ~10 ms, multilingual. |
| **Parallel sub-agents** | llama.cpp/Ollama parallel slots and a task queue with priorities; background tasks with progress | Muse-style "work on these three things". |
| **Optional cloud, still in control** | Any provider or the user's own key, with redaction (names, numbers, emails replaced before sending), per-request approval or a monthly budget | A frontier model when the user wants one, without giving up control. |

### Pillar D: Reaches everything (closes Gap 3)

| Capability | What it is | Notes |
|---|---|---|
| **MCP client** | Plug in any Model Context Protocol server; each tool gets a tier (default *write*), untrusted-output marking, and appears in the Control Center | Thousands of existing connectors on day one, under our policy engine. |
| **Signed skill marketplace** | Skills with a permission manifest (folders, domains, tier), signatures, reviews; run sandboxed (and on Windows, using AppContainer) | Our answer to the "1,500 connectors in a week" story, with safety built in. |
| **First-party connectors** | Google Calendar/Drive, Outlook/Microsoft 365, Slack, Notion, Todoist, Home Assistant/HomeKit, Spotify, Apple Health export, bank/brokerage CSV import | Cover the top 90% of daily use. |
| **Commerce with the user's own card controls** | Virtual cards the user creates (Privacy.com, card-issuer single-use numbers, Apple Pay handoff) with a per-task cap; card details live in the vault and are typed by the tool layer, never seen by the model | Muse/Instinct-style checkout without a partner deal; payment remains a *danger* approval. |
| **Merchant recipes** | Maintained recipes for the top retailers, groceries, restaurants and travel sites; order tracking from email | Reliability where users shop most. |
| **Calls on your behalf (opt-in, later)** | Outbound calls with an explicit AI disclosure, a script approved before dialling, and a recording kept locally | Only after the legal review; never negotiating or agreeing to terms. |

### Pillar E: Feels like a product (closes Gap 4)

| Capability | What it is |
|---|---|
| **Native app shell** | A signed and notarised macOS app with a menu-bar icon (Swift or Tauri), a Windows MSIX, Linux Flatpak. It bundles Python and talks to Ollama. Its own TCC identity fixes the "Terminal has Full Disk Access" problem. |
| **One-click install, signed auto-update** | Ollama and models fetched with progress, verified by digest. Delta updates. Rollback. |
| **Real-time voice** | Streaming STT + neural TTS (Kokoro/Piper) with barge-in, about 500 ms turn latency on Apple Silicon; voice notes over iMessage. |
| **Avatar 2.0** | Expressive 2D/3D avatar with visemes from the TTS phonemes; optional photoreal on hardware that can afford it. |
| **Family and teams** | Separate agents per person on one home node; shared calendars; parental controls. |
| **Accessibility and languages** | Multilingual UI and voice; screen-reader-first UI. |

---

## 3. Phased plan

| Phase | Theme | Main deliverables |
|---|---|---|
| **1. Trustworthy beta** (6–8 weeks) | Pillar A | P0+P1 security fixes; Privacy Control Center; egress ledger; payload approvals; off-by-default onboarding; native macOS shell with its own TCC identity; signed installer |
| **2. Always there** (8–10 weeks) | Pillar B | Home node mode; iOS companion app (chat, approvals, push); blind relay (open source, self-hostable); E2E sync |
| **3. Smarter** (8–12 weeks, overlapping) | Pillar C | Hardware tiers; plan-act-verify; learned recipes; fine-tuned tool model; parallel tasks; redacting cloud option |
| **4. Everything** (ongoing) | Pillar D | MCP client; skill marketplace with signed manifests; top-10 connectors; virtual-card checkout |
| **5. Polish** (ongoing) | Pillar E | Real-time voice; Android; Windows/Linux native shells; avatar 2.0; family accounts |

**Release gates per phase:**

- the security review re-run with no open P0/P1;
- egress ledger tests ("this feature sends nothing" asserted in CI);
- an injection red-team suite passing;
- crash-free sessions above 99.5%.

---

## 4. Business model that keeps "zero token cost" honest

| Tier | Price | What |
|---|---|---|
| **Free** | $0 | The full local agent, all core features, unlimited use: no tokens, no meter |
| **Pro** | One-time license or ~$5/month | Companion apps and push via the blind relay, multi-device sync, premium voices, priority skill updates |
| **Family** | ~$10/month | Up to 6 people on one home node, shared planning |
| **Home node** | Hardware partner bundle | Pre-configured mini PC with the agent and models installed |
| **Marketplace** | Revenue share | Paid skills and merchant recipes from third parties |

What we never sell: user data, model access to user data, or ads. Cloud model use, if any, is always on the user's own key.

---

## 5. Positioning against each competitor

| Message | vs Meta Muse | vs Instinct |
|---|---|---|
| Privacy | "Muse needs your life on Meta's servers. We never see it." | "Instinct kept data after people disconnected. Ours is a folder you can delete." |
| Control | "Approvals with the full payload, and a ledger of everything that left." | "Never signs anything for you. No binding agreements, ever." |
| Cost | "No subscription required. Your computer does the work." | Same |
| Transparency | "See why it did everything, with the numbers." | "See the email that tried to hijack it, and that it said no." |
| Openness | "Open core, auditable, extensible with MCP and signed skills." | Same |

## 6. Risks and how to handle them

| Risk | Mitigation |
|---|---|
| Local models stay noticeably weaker on long tasks | Recipes and plan-verify for reliability; hardware tiers; optional cloud with redaction; focus marketing on daily tasks where small models do well. |
| The always-on story depends on a second device | Home node bundles; wake-on-demand; be honest that a laptop-only setup pauses when it sleeps. |
| Platform changes (macOS privacy, Messages DB format) | Native shell with proper entitlements; integration tests per macOS beta; prefer official APIs (EventKit, App Intents). |
| Merchant blocking of agents | Recipes that act as the user in their own browser; hand off to the user for checkout. |
| Security incident | P0/P1 first; red-team suite in CI; bug bounty; fast signed updates. |
