# Testing v0.17.2: Trust tab redesign, Ask, wake word, reliability and security

**New in 0.17.2: Mail no longer runs out of memory** (see UPGRADING.md). If you already checked 0.17.1, only do these:
- M1. After upgrading, quit and reopen Mail. Open Trust → Verify & export → Safety checks. "Mail isn't slowed down by the agent" shows ✅ and "reads Mail's index". If it says it uses Mail.app instead, please send the reason it shows.
- M2. Ask _"Any unread email?"_ and _"Read the first one"_: both answer as before.
- M3. After a day of normal use, open Activity Monitor → Memory: Mail stays at a normal size (hundreds of MB, not GB), and the "out of application memory" warning doesn't come back.

0.17.1 fixed "Hey Ari" being heard but not run. If you already checked 0.17.0, also redo steps 7–9.

Do the steps in `UPGRADING.md` first (about 5 minutes). This checklist takes about 15 minutes.

**Verified before release:**
- 255 automated tests on Linux, including:
  - Run checks with 6,000 contact names;
  - a 20,000-entry activity log (the Trust status stays under half a second, and tampering is still caught);
  - Ask answers from the records, with injected text never reaching the model;
  - the wake endpoint falling back when the wake model is broken;
  - a real sandbox run that tries to reach a session-bus socket;
  - phone PIN guessing across calls;
  - one-time sign-in codes.
- A real browser run:
  - the Trust status line, sub-tabs, capability rows, preset, pause;
  - Ask chips and typed questions, plus a privacy question in chat;
  - Run checks reporting its time;
  - phone width with no sideways scrolling;
  - the wake word with a simulated microphone: the click-to-start prompt when audio is paused, "Heard …" on a near miss, waking on "Hey Ari", and the reason shown when it's switched off.
- CI on Ubuntu, macOS and Windows.

**Only your Mac can verify:**
- your real microphone with the real wake model;
- the keychain block for skills;
- real calls.

### If something fails

| You see | Fix |
|---|---|
| "Open LocalAIAgent from its app or Terminal" right after upgrading | Expected once (the sign-in secret was replaced). Run `localagent open`. |
| "Click anywhere on this page to start listening for “Hey Ari”" | Expected after the page loads: browsers keep the microphone audio paused until you click. Click once. |
| "Wake word: …" in red under the chat | That's the reason it can't listen. Please send it. |
| "Heard “…”, not “Hey Ari”" | It heard you but didn't recognise the phrase. Please send the exact text in quotes; matching is tuned from these. |
| Phone: "This line is locked for now" | 5 wrong PINs within an hour. It unlocks after an hour, or right away if you save a new PIN in Settings → Phone line. |
| A custom skill fails to start | Send the error. Skills can no longer use the keychain. |

## Checks

**Sign-in**
1. Run `localagent open`. The app opens. Look at the address in your browser's history: it has `?c=…`, not your secret, and opening that history entry again shows "Link expired".

**Trust tab**
2. Open **Trust**. The top shows one line ("✅ All good" or "⚠ N things need your attention"), the reasons, Pause, and Observer · Assistant · Agent.
3. **Overview:** press the example questions. Each answer appears in a second, with "Based on your records" underneath. Type _"Is screen context on?"_: a **Turn on Screen context** button appears.
4. In **Chat**, ask _"What did you send to the internet this week?"_. The answer ends with "(From your Trust records …)".
5. **Capabilities:** one line per capability, grouped On and Off. Click a row to see what it reads, what can leave, the risk and the safeguards.
6. **Verify & export:** set **From** to a month ago and press **Run checks**. Within a few seconds you see "Checked N log entries … in X s" and the findings. **Download record** still works.

**Hey Ari**
7. In Trust → Capabilities, switch **Wake word** on. Under the chat it says "Listening for “Hey Ari”", or "Click anywhere on this page…": then click once.
8. Say _"Hey Ari"_. You hear a chime and it listens. Say _"Hey Ari, what's on my calendar today?"_ in one breath: the question appears in the chat and it answers.
9. Say something else. For a moment it shows "Heard “…”, not “Hey Ari”".

**Phone** (if you use it)
10. Call, and type a wrong PIN five times (over two calls). The next call says the line is locked. Save a new PIN in Settings → Phone line, and call again: it works.

## Please send back
1. Did any step behave differently from the description?
2. For the wake word: what does it show under the chat, and does "Hey Ari" wake it?
3. Is the Trust tab clearer now? Anything you'd still remove or rename?

Logs: `~/Library/Application Support/LocalAIAgent/server.log` (Windows: `%LOCALAPPDATA%\LocalAIAgent\server.log`, Linux: `~/.local/share/LocalAIAgent/server.log`).
