# Upgrading LocalAIAgent

Upgrading keeps everything you've built up: memories, conversation history, decision corrections and settings. They live in `~/Library/Application Support/LocalAIAgent/`, which the installer never touches.

## From 0.2.x to 0.4.0 (Steps 3 + 4: proactivity and voice)

Your memories, history, approvals, permissions and activity log are kept.

1. Put the new files in one folder, for example `~/Downloads/LocalAIAgent-0.4.0/`.
2. In Terminal (the same app you gave Calendar/Contacts permission to), **without `sudo`**:

   ```bash
   cd ~/Downloads/LocalAIAgent-0.4.0
   bash install.sh localaiagent-0.4.0-py3-none-any.whl
   ```

   The installer:
   - stops the running agent;
   - installs 0.4.0 and the **voice add-on** (on-device speech recognition);
   - checks your chat models (already downloaded, so this is quick);
   - downloads the **speech model** (about 1.6 GB, once). To skip it for now, run with `LOCALAGENT_VOICE=0 bash install.sh …`, then later run `localagent setup --voice`.
3. Start it from the same Terminal window:

   ```bash
   localagent start
   localagent version      # 0.4.0
   ```

   If a tab looks empty, press **Cmd+Shift+R** once.
4. **Allow notifications.** The first nudge triggers a macOS prompt. Notifications from the agent appear under **Script Editor**: open **System Settings → Notifications → Script Editor** and turn on **Allow notifications**. Choose **Alerts** if you want them to stay on screen.
5. **Allow the microphone.** The first time you press the mic button, the browser asks; click **Allow**.
   If you blocked it by mistake: in Chrome, click the icon left of the address bar → Microphone → Allow; in Safari, use **Settings → Websites → Microphone**.
   macOS may also ask whether your browser can use the microphone (**System Settings → Privacy & Security → Microphone**).
6. Optional: run `localagent autostart on` to start the agent when you log in. It's off by default, because macOS treats the auto-started agent as a different app and will ask for Calendar, Contacts and Mail permission again. Undo it with `localagent autostart off`.

Nothing else changes: no new Automation permissions are needed. Mail's "waiting on your reply" check uses the Mail permission you already gave.

### Going back to 0.2.1

```bash
localagent stop
pipx install --force ./localaiagent-0.2.1-py3-none-any.whl
localagent start
```

0.2.1 ignores the new tables.

## What changed in 0.4.0

- **Proactivity (Step 3):**
  - **Morning brief** at 08:00: your day, what's due, and emails waiting on your reply. It appears in Chat and in **Nudges**.
  - **Checks every 30 min:** events in the next hour, reminders that are overdue or due soon, and emails you haven't replied to in 1–7 days. The decision layer decides whether each one is worth interrupting you for, and how urgent it is. Its calls appear in **Decisions** and can be corrected there.
  - **Overnight memory review** at 03:00, only while plugged in: picks up facts you mentioned but it missed, and merges duplicate memories.
  - **Quiet hours** (22:00–07:30) and a **daily limit** on interruptions (6). Everything is still listed in **Nudges**, with Dismiss, Snooze 1 h and Ask about this.
  - Missed jobs (Mac asleep or agent off) run once when it's back. They're never replayed several times.
  - A new **mail_followups** tool, so you can also ask "which emails haven't I replied to?".
- **Voice (Step 4):**
  - Mic button in Chat: **hold to talk**, or **click to start and click again to send**. You can also hold the **Space** bar when you're not typing.
  - Speech recognition runs on your Mac (Whisper on Apple Silicon); nothing is uploaded.
  - Replies to voice messages are spoken with your Mac's voices. Choose a voice and speed in Settings.
  - **Conversation mode:** after it answers, it listens again, and a ~1 s pause sends what you said. Click the mic to interrupt it while it speaks.
  - Approvals are never spoken or voice-approved; it tells you to approve on screen.
- `localagent autostart on|off|status`.

## From 0.1.x or 0.2.0 to 0.2.1 (Step 2: connectors and approvals)

1. Put the new files in one folder (for example `~/Downloads/LocalAIAgent-0.2.1/`):
   `localaiagent-0.2.1-py3-none-any.whl`, `install.sh`, `TESTING.md`, `UPGRADING.md`.
2. Open Terminal in that folder and run, **without `sudo`**:

   ```bash
   cd ~/Downloads/LocalAIAgent-0.2.1
   bash install.sh localaiagent-0.2.1-py3-none-any.whl
   ```

   The installer stops the running agent, replaces the program, checks the models (already downloaded, so this is quick), and runs `localagent doctor`.
3. Start it again:

   ```bash
   localagent start
   localagent version      # should print 0.2.1
   ```

   If `localagent` isn't found, use `~/.local/bin/localagent start` and see the troubleshooting table in `TESTING.md`.
4. In the browser, open **Connectors** and press **Test** on Calendar, Reminders, Notes, Mail and Contacts. Each one shows a macOS prompt (_"Terminal wants access to control Calendar"_); click **Allow**. You only do this once per app.

Your new database tables (approvals, permissions, activity log) are created automatically on first start.

### Manual upgrade (if you'd rather not use the script)

```bash
localagent stop
pipx install --force ./localaiagent-0.2.1-py3-none-any.whl
localagent start
```

### Going back to 0.1.x

```bash
localagent stop
pipx install --force ./localaiagent-0.1.2-py3-none-any.whl
localagent start
```

0.1.x ignores the new tables, so your memories and history keep working.

## What changed in 0.2.1

- Fixes an empty **Connectors** tab (and other empty new tabs) after upgrading. The browser had kept the old cached script. The app now version-stamps its files, so this can't happen again. If you ever see an empty tab, reload with **Cmd+Shift+R**.

## What changed in 0.2.0

- **Connectors**: Calendar, Reminders, Notes, Mail, Contacts (through the Apple apps, so any Google, iCloud or Exchange account you've added to them works), Files (Downloads, Desktop, Documents) and Documents (PDF and Excel).
- **Approvals**: every action has a risk tier:
  - **read** runs on its own.
  - **draft** runs on its own and is logged.
  - **write** asks first; you can approve once, for this request, until restart, for 1 hour or 24 hours, or always.
  - **danger** (for example moving files to the Trash) asks every time.
- **Activity**: a hash-chained audit log of everything the agent did, asked for, or was refused. It flags any edit made outside the app.
- **Installer**: refuses `sudo`, finds the wheel by itself, puts `localagent` on your PATH, and stops a running agent before upgrading.
