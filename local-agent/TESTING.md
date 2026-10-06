# Testing Step 6 (v0.8.0): text your agent from your iPhone

Set it up with `UPGRADING.md` (2 minutes). This checklist takes about 10 minutes. Keep the Mac awake and the agent running.

### If something fails

| You see | Fix |
|---|---|
| No test message arrives | **Privacy & Security → Automation → Terminal → Messages** must be on, and Messages must be signed in. Try again. |
| Settings status "error — macOS blocked reading…" | Full Disk Access for Terminal (see the 0.5.0 steps), then restart the agent. |
| Your texts are ignored | Start with the agent's name ("Ari, …"), text **yourself**, and check that your number or email is in Settings exactly as the iPhone sends it. |
| Status "no owner set" | Add your number or email in Settings. |

## A. Basics

1. **Settings → Text me → Send a test message.** A 🤖 text arrives on your iPhone.
2. From your iPhone, in the chat with yourself: `Ari, what's on my calendar tomorrow?` A 🤖 reply arrives within about 5 seconds.
3. `Ari, chutneys bellevue` gets a look-up answer with a link.
4. Text yourself something **without** "Ari" (for example "milk"). Nothing happens.

## B. Approvals by text

1. `Ari, remind me to call mom at 6pm` should reply "Needs your OK: …" with how to answer. Reply `yes`; the reminder appears in Reminders.
2. `Ari, remind me to stretch at 7pm`, then reply `no`. Nothing is created.
3. Optional: `Ari, reply to <friend> on iMessage saying I'm running late`, then reply `yes 1h`.

## C. Nudges by text

1. In the app, **Nudges → Run now** on **Check calendar, reminders, email and chats**. Each new nudge also arrives as a 🤖 text (outside quiet hours).
2. **Run now** on **Morning brief**. The brief arrives as a text.

## Please send back

1. Did replies arrive? How long did they take?
2. Did approving by text work?
3. Were the nudge texts useful or too many?

Known limits:
- Works only while the Mac is awake with the agent running. Texts that arrive while the agent is stopped are skipped (it never answers old messages), so resend them.
- Pictures and voice notes aren't understood yet; send text.

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
