---
name: review-localagent
description: Project-specific code review for LocalAIAgent (local macOS personal agent - Ollama SLMs, Jev-style decision layer, AppleScript/EventKit connectors, approvals, proactivity, voice). Use before every commit or release, when asked to "review", "check for mistakes", or before sending the user a new package. Encodes the failure modes this project has actually hit.
---

# LocalAIAgent review

Review the change (default: `git diff` against the last release commit, plus untracked files) for the failure modes below. They come from real problems in this project. The user tests every release on their Mac and only reports back afterwards, so a mistake costs a full round trip.

## How to run

1. **Scope:**
   - `git log --oneline -5` to identify the last release commit;
   - `git diff <release>..` and `git status --short` for untracked files.

   Read every changed file in full, not only the hunks, when it touches policy, connectors, the installer or the UI.
2. **Walk the checklist.** For each item that applies, check the code. Don't skip a section because it "looks fine".
3. **Run the verification gates** (section K). A review isn't done until they pass.
4. **Report** each finding as: severity (blocker / should-fix / nit), `path:line`, a concrete failure scenario (input → wrong result), and the fix. Fix blockers and should-fix items, then re-run the gates.

## A. Install, upgrade and copy-paste commands (the user runs these verbatim on macOS zsh)

- [ ] Docs and replies say `bash install.sh …`, **never** `./install.sh` (downloads lose the executable bit) and **never** `sudo` (Homebrew refuses root; pipx would install for root). The installer must refuse root.
- [ ] Copy-paste command blocks contain **no inline `# comments`** and **no apostrophes outside quotes**. Interactive zsh treats `#` literally, and an apostrophe opens a `quote>` prompt (this happened with `tccutil … # only resets Terminal's …`).
- [ ] `localagent` must work right after install: pipx's `~/.local/bin` is often not on PATH. The installer links it into `$(brew --prefix)/bin` and calls the binary by full path.
- [ ] The installer stops a running agent before replacing it, keeps the user's data directory, and is idempotent (re-running is safe).
- [ ] The **version is bumped in all three places**: `pyproject.toml`, `src/localagent/__init__.py`, `tests/test_cli.py`. The wheel file names in `install.sh`, `README.md`, `TESTING.md` and `UPGRADING.md` match.
- [ ] Every new UI asset is **version-stamped** in `server.py` `index()`, with `Cache-Control: no-cache` set, so a stale cached script never pairs with a new page (this happened: an empty Connectors tab).
- [ ] New optional dependencies are an **extra with a platform marker** and are injected by the installer only where they work (e.g. `mlx-whisper` on darwin arm64, `pyobjc-framework-EventKit` on darwin). The base package must still install on Linux CI.
- [ ] Expected scary-looking output is pre-explained in docs (e.g. the Hugging Face "unauthenticated requests" warning).

## B. macOS privacy (TCC): the most common real-world failure

- [ ] Any new access to an Apple app or data store states **which permission** it needs:
  - Automation (AppleScript; error -1743);
  - Calendars/Reminders "Full Access" (EventKit);
  - Microphone (browser);
  - Notifications (they show as "Script Editor").
- [ ] Error messages for denied access name the exact **System Settings path** and say to restart the agent from Terminal.
- [ ] Remember the attribution: permissions belong to the app that **started** the agent (Terminal). `autostart` (launchd) is a different app and must be documented as re-prompting.
- [ ] Code paths that can run in tests or CI must **never touch real system resources**. EventKit, osascript, `say` and notifications must be injectable and must default to off when a fake runner is injected (see `Runtime.__init__`).

## C. AppleScript connectors

- [ ] Arguments are passed as **argv** (`osascript - arg…`), never spliced into script text: no injection from model, email or user text.
- [ ] `whose start date …` on Calendar **does not expand repeating events**. The AppleScript path must also fetch repeating series and expand their RRULE in Python (`recurrence.py`). Never rely solely on EventKit TCC: it failed twice on the real Mac.
- [ ] Never request TCC access from the background server (macOS may not show the prompt). Read the status only, show it to the user ("via AppleScript (EventKit: …)"), and request access from a foreground CLI command.
- [ ] Dates passed out of AppleScript must be built from components (`YYYY-MM-DD HH:MM:SS`). Large second offsets print as `6.3E+8` and break parsing.
- [ ] Dates cross the boundary as **integer second offsets from now**, never locale-formatted strings. Watch AppleScript coercing large reals to `1.2E+6`.
- [ ] Records use the `\x1e`/`\x1f` separators. The parser tolerates short records and empty fields.
- [ ] Every script has a timeout, and stderr is mapped through `explain_error`.

- [ ] Reading another app's database (chat.db, WhatsApp, AddressBook): open with `mode=ro`, never write, check the schema first, and turn PermissionError/"unable to open" into the Full Disk Access steps (quit and reopen Terminal).
- [ ] Never automate sending where the platform has no API (WhatsApp): open the official link with the text typed in and let the user press Send.

- [ ] Browser: never let a draft-tier tool submit, send, buy or delete (`needs_submit()`), never type into password or payment/ID fields (`forms.SENSITIVE`), keep main-content elements ahead of navigation and reachable with `browser_find` on huge pages, open only http(s) URLs, and mark page text `untrusted`.
- [ ] Look-ups: anything that changes or is local (prices, hours, businesses, news) must go through `web_search` and a source page, never the model's memory; a new seed file must be tracked by `seeded:<file>` so it reaches existing installs.
- [ ] Browser start-up: launch the user's real Chrome ourselves (own profile, DevTools port 0 → `DevToolsActivePort`) and attach; never fall back silently, and never discard a launch error. Report every reason verbatim.
- [ ] Channels (iMessage): only owner handles are answered, never groups or strangers; the agent never answers its own 🤖 replies; old messages are never answered after a restart (persisted ROWID); approvals by reply keep danger at "once".
- [ ] Wake word: never store audio; ignore bursts while the agent listens, works or speaks (no self-wake); the name must match by sound, not just loosely ("Hey Siri" must not wake "Ari").
- [ ] Secrets (OAuth tokens, API keys) live only in `Vault` (Keychain, else a 0600 file); never in config.json, logs, audit, tool output or the UI after saving. Tests set `LOCALAGENT_NO_KEYRING`.
- [ ] OAuth: PKCE + state, loopback redirect to the agent's own address, refresh before expiry, one forced refresh on 401, `invalid_grant` → forget and ask to reconnect.
- [ ] Anything leaving the Mac for a model (cloud) goes through an approval that lists exactly what's sent; off by default; no tools in the cloud; the key stays in the vault. Use the official SDK, the current model id and `fallbacks="default"`, and handle `stop_reason == "refusal"`.
- [ ] Agent-to-agent: only sealed boxes from paired keys (plus hellos with a one-time token); check timestamp and nonce replay; rate-limit; no auto-answer beyond the scopes the user ticked; the listener runs only when enabled; never undo a working pairing on a failed retry.
- [ ] Skills: never run user scripts unsandboxed on macOS; network implies at least write tier; invalid SKILL.md files are reported, not half-loaded.

- [ ] Mac UI actions: re-verify the element (role + name) before pressing, refuse password managers/System Settings/terminals, and give risky labels a higher tier through `risk(args)`. Unknown elements count as danger.
- [ ] Screen capture: opt-in only; check the blocklist and lock screen before capturing; delete the image in `finally`; enforce retention on every read and write.

## D. LLM output hygiene

- [ ] All model text shown to the user goes through `strip_think` (non-streaming) or `ThinkFilter` (streaming). That includes an **orphan `</think>` with no opening tag** (Qwen3 does this even with `think:false`). Streaming consumers must handle the `RESET` sentinel / `{"type":"reset"}` event.
- [ ] Structured outputs use a JSON-schema `format` with enums. Tool arguments go through `validate_args`, and dates through `parse_when`.
- [ ] Lists the user asked for must not depend on the model's summary: tool results carry the full `data` list, and the UI shows it (expandable chips). The prompt says to list every item.
- [ ] Never claim more than the model gives. Decision percentages are **not calibrated probabilities** (kNN softmax at T=30; the SLM judge is a fixed 0.8 blend). Docs and UI copy must not call them calibrated. Calibration claims need `localagent eval decision` (ECE).
- [ ] Untrusted text (email bodies, notes, web, files) can contain instructions. It must never change policy, tiers or approvals, and must never be executed.

- [ ] Any tool returning text written by other people (mail, chats, web pages) sets `ToolResult(untrusted=True)`. It's then fenced and scanned, and a hit taints the run so grants stop applying. Proactive jobs that pass such text to the model must `fence()` it too.

## E. Policy, approvals and audit

- [ ] Every new tool declares the **right tier**:
  - read: looks only;
  - draft: creates something new and reviewable;
  - write: changes or sends;
  - danger: deletes, spends, submits or is irreversible.

  When in doubt, go up a tier.
- [ ] `danger` allows only the `once` scope. Persistent grants are never possible for danger.
- [ ] Paused runs store **JSON-serialisable** state, and resume handles pending calls after the approved one.
- [ ] Every executed tool call, approval decision, grant revocation and proactive job is appended to the **audit chain**. `/api/audit/verify` still passes.
- [ ] Nothing approves by voice, by notification click, or by model output.

## F. Security and privacy

- [ ] The server binds to `127.0.0.1` only. The only new network calls are model downloads, unless explicitly approved and documented in DESIGN §11.
- [ ] File paths are resolved (`.resolve()`) and confined to `file_roots`. Watch symlinks and `..`. Never trash or move a root.
- [ ] The UI never sets `innerHTML` from data except through `md()`, which escapes first. Data from email or calendar is rendered with `textContent` or `el()`.
- [ ] No secrets in logs or the audit log. Audio is never written to disk (STT runs in memory; the TTS temp file holds only reply text and is deleted).

## G. Data and upgrades

- [ ] Schema changes use `CREATE TABLE IF NOT EXISTS`, plus additive columns with defaults. A database from the **previous release opens** and keeps its memories, approvals and audit chain (test with `git worktree add <old commit>`).
- [ ] New seed sets are inserted on upgrade per set (`seed_store` checks each set's first question), not only on a fresh install.
- [ ] Settings get defaults and validation in `Settings.update`. Booleans are parsed from strings, and HH:MM values are validated.

## H. Proactivity

- [ ] Time logic uses the injected `clock`, not `time.time()`/`datetime.now()`, wherever tests need control.
- [ ] Quiet hours handle ranges across midnight. The cap counts only interruptions. Dedupe keys are **stable** across runs (an id, or title plus start), not timestamps, except for briefs and dreams.
- [ ] A missed schedule runs **once** (catch-up), never N times. `Deferred` reschedules; a manual run doesn't move the schedule.
- [ ] Heavy work (dream) respects battery state.

## I. Voice

- [ ] The browser sends 16 kHz mono 16-bit WAV, so the server never needs ffmpeg.
- [ ] `say` receives text via `-f <tempfile>`, never as an argument. Markdown and emoji are stripped. It can be stopped (barge-in).
- [ ] Approvals are never spoken as accepted; the agent tells the user to approve on screen.

## J. UI

- [ ] New tabs register a loader. Errors surface in the banner, never as a silent empty panel.
- [ ] Light and dark mode, and phone width (390 px) without horizontal scroll.
- [ ] Settings checkboxes read and write `.checked`, not `.value`.

## K. Verification gates (all must pass before sending a package)

Run these from the project root: `local-agent/` inside the synthiq repo, or the repo root if the project moves to its own repository. `$PY` is a Python 3.11+ environment with `pip install -e ".[dev]"` already done.

```bash
$PY -m pytest -q
node -e "for (const f of ['src/localagent/ui/app.js','src/localagent/ui/voice.js']) new Function(require('fs').readFileSync(f,'utf8'))"
bash -n install.sh
rm -rf dist && $PY -m build
python3 -m venv /tmp/la-clean && /tmp/la-clean/bin/pip install dist/*.whl && /tmp/la-clean/bin/localagent version
```

CI runs the same tests on Ubuntu and macOS-14 (synthiq's `.github/workflows/local-agent.yml`).

- **Browser:** drive the UI with Playwright using `executable_path="/opt/pw-browsers/chromium"` (don't run `playwright install`). Use the fake Ollama, fake runner, fake STT and fake TTS, and pass `--use-fake-device-for-media-stream` for voice.
- **Upgrade:** open a previous release's database with the new code (git worktree).
- **Installer:** stub-test it as a non-root user (`su nobody`) with fake `brew`/`pipx`/`curl`.
- **Dev-shell pitfall:** never `pkill -f <pattern>` where the pattern also appears in your own command line; it kills the shell running it.
- **Docs:** `TESTING.md`, `UPGRADING.md` and `DESIGN.md` describe the change, and every number in DESIGN matches the code (grep the constants).
- **Be honest in the hand-off:** say exactly what was verified here (fakes, Linux) and what only the user's Mac can verify (real AppleScript, EventKit, TCC prompts, audio, model quality).
