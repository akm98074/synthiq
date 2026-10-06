# Upgrading LocalAIAgent

Upgrading keeps everything you've built up: memories, conversation history, decision corrections and settings. They live in `~/Library/Application Support/LocalAIAgent/`, which the installer never touches.

## From 0.7.0 to 0.7.1 (better shopping, no card details)

```bash
bash install.sh localaiagent-0.7.1-py3-none-any.whl
localagent start
localagent version
```

The last line should print `0.7.1`. No new permissions are needed.

### What changed in 0.7.1

- **Look-ups search the web first.** Ask "find price of onion in Safeway Sammamish" or just "Chutneys Bellevue". The agent searches the web (DuckDuckGo), opens the best page (for a shop, the shop's own site and its search box), and answers with the source link. A business name plus a place gets you what it is, address, hours, phone and rating. General-knowledge questions are still answered directly.
  - Only the search words leave your Mac. You can turn this off under **Connectors → Web search**.
- **Big pages work better.** The agent now sees a page's main content (the product, its price, "Add to Cart") before the site's menus. A new **find** step reaches any button or link on the page, even on huge pages like Amazon's.
- **Never types card details.** Card number, security code, expiry, IBAN and ID-number fields are refused, like passwords. You type those yourself.
- **Shopping stops at the cart** unless you clearly asked it to buy: it adds the item and summarises the price and delivery. Add to Cart, checkout and Place order each still show a red approval card.

## From 0.6.0 to 0.7.0 (Step 5c: Mac apps, screen context, form filling)

1. Put the new files in one folder, open Terminal there, and run (no `sudo`):

   ```bash
   bash install.sh localaiagent-0.7.0-py3-none-any.whl
   localagent version
   ```

   The last line should print `0.7.0`.
2. Allow **Accessibility** so the agent can read and press buttons in other apps:
   - Open **System Settings → Privacy & Security → Accessibility**.
   - Turn on **Terminal**. If it isn't listed, click **+** and choose **Applications → Utilities → Terminal**.
3. Optional: **screen context** is off unless you turn it on. To use it, run:

   ```bash
   localagent screen-access
   ```

   Then allow **Terminal** under **Privacy & Security → Screen & System Audio Recording**.
4. **Quit Terminal completely** (Cmd+Q), open it again, and start the agent:

   ```bash
   localagent start
   ```

5. For screen context, turn on **Settings → Screen context → Let the agent read the text on my screen**, then **Save**.

### What changed in 0.7.0

- **Mac apps and Shortcuts.** Ask "what apps are open?", "run my Focus shortcut" or "in Notes, make the title bold".
  - The agent prefers your **Shortcuts** when one fits, because they're reliable. Otherwise it reads the app's window and presses buttons by number.
  - Pressing, typing and running a Shortcut ask first. Buttons such as Delete, Send or Buy ask every time.
  - It never operates password managers, Keychain Access, System Settings or Terminal.
- **Form filling from memory.** Open a page with a form, then say "fill in the form for me". The agent fills in what it knows (name, email, address…) and lists what it used and what's left.
  - It never fills in passwords, card numbers, security codes or ID numbers, and **never submits**. Submitting is the usual danger approval.
- **Screen context (opt-in).** When on, the agent reads the text on your screen every 5 minutes with Apple's on-device OCR. The screenshot is deleted at once, and only the text is kept, for 2 hours.
  - It skips password managers, Messages, WhatsApp, Signal and FaceTime (edit the list in Settings), and the lock screen.
  - Ask "what's on my screen?" or "what was that article about kettles I was reading earlier?". **Forget screen history now** clears it.
- Each request can now be judged by what it actually does: pressing a "Delete" button counts as a danger action even though pressing other buttons doesn't.

## From 0.5.0 to 0.6.0 (Step 5b: browser and custom skills)

1. Put the new files in one folder, open Terminal there, and run (no `sudo`):

   ```bash
   bash install.sh localaiagent-0.6.0-py3-none-any.whl
   localagent start
   localagent version
   ```

   The last line should print `0.6.0`. The installer adds the browser add-on. If you have **Google Chrome**, the agent uses it with its own separate profile. Otherwise it downloads Chromium (about 150 MB).
2. Optional: try a custom skill.

   ```bash
   localagent skill new word-count
   localagent skill list
   ```

   Then open **Connectors**. The skill appears under **Custom skills**, and you can ask "make a word count of: …".

### What changed in 0.6.0

- **Browser.** Ask "open bbc.com and tell me the top headlines" or "search amazon for a blue kettle under $40".
  - The agent uses **its own browser window**, which you can watch. It isn't signed in to anything. If a site needs a login, sign in yourself in that window once; the agent never types passwords.
  - It can read pages, click links, fill in fields and run searches on its own. Anything that **submits, sends, books, pays or deletes** shows an approval card every time ("Just this once" only).
  - Page text is treated like email: instructions hidden in a page are flagged ⚠ and ignored.
- **Custom skills.** Folders in `~/Library/Application Support/LocalAIAgent/skills/` with a `SKILL.md`. A skill can be plain instructions ("how I pack for trips") or run a script.
  - Scripts run in macOS's sandbox: **no network** unless the skill says `network: true`, writes only to the skill's own `work` folder, and no access to Mail, Messages, Keychains, browser data or the agent's own data.
  - A skill that uses the network always asks for approval.

## From 0.4.2 to 0.5.0 (Step 5a: iMessage and WhatsApp)

1. Put the new files in one folder, open Terminal there, and run (no `sudo`):

   ```bash
   bash install.sh localaiagent-0.5.0-py3-none-any.whl
   localagent version
   ```

   The last line should print `0.5.0`.
2. Give Terminal **Full Disk Access**, which lets the agent read your Messages and WhatsApp history on this Mac:
   - Open **System Settings → Privacy & Security → Full Disk Access**.
   - Turn on **Terminal**. If it isn't listed, click **+**, open **Applications → Utilities**, and choose **Terminal**.
   - **Quit Terminal completely** (Cmd+Q) and open it again. macOS only applies this permission to a fresh Terminal.
3. Start the agent from the new Terminal window and check the permission:

   ```bash
   localagent start
   localagent doctor
   ```

   The line `messages (Full Disk Access)` should say `ok`.
4. For WhatsApp, have **WhatsApp Desktop** (from the App Store or whatsapp.com) installed and linked to your phone. Only chats synced to the Mac can be read.
5. The first iMessage the agent sends shows a macOS prompt, _"Terminal wants to control Messages"_. Click **OK**.

### What changed in 0.5.0

- **Messages connector.** Ask "which chats are waiting on my reply?", "what did Sam say?" or "reply to Mum on WhatsApp that I'll call at 8".
  - **iMessage/SMS:** the agent drafts the reply and shows it on an approval card; it's sent only when you approve.
  - **WhatsApp:** WhatsApp opens with the reply typed into the chat, and **you press Send**. WhatsApp has no way for apps to send from a personal account.
  - Group chats are left out unless you turn them on in **Settings → Connectors**.
- **Nudges and the morning brief** now include chats waiting on your reply (older than an hour). Automated senders such as bank codes are skipped.
- **Prompt-injection guard.** Emails and chats are written by other people, so the agent treats them as data. If one contains text aimed at an AI ("ignore previous instructions…"), the result is marked ⚠ and logged in **Activity**. Every send or change for the rest of that request needs your fresh approval, even if you'd allowed it before.

## From 0.4.1 to 0.4.2 (repeating meetings without extra permissions)

1. Put the new files in one folder, open Terminal there, and run (no `sudo`):

   ```bash
   bash install.sh localaiagent-0.4.2-py3-none-any.whl
   localagent start
   localagent version
   ```

   The last line should print `0.4.2`.
2. In Chat, ask `What's on my calendar this week?`. Repeating meetings now appear, using the Calendar permission you already gave Terminal.
   The chip shows where the events came from, for example "Found 14 event(s) via AppleScript (EventKit: not asked yet)".
3. Optional, for the most exact results (moved or cancelled single occurrences): give the agent EventKit access from Terminal:

   ```bash
   localagent calendar-access
   localagent stop
   localagent start
   ```

   Click **Allow** if macOS asks. If it prints "access denied", open **System Settings → Privacy & Security → Calendars**, set **Terminal** to **Full Access**, and restart the agent as above. The chip then says "via EventKit".

### What changed in 0.4.2

- **Repeating meetings fixed for everyone.** Without EventKit, the agent now reads each repeating series' rule from Calendar and works out every occurrence in the requested range itself (skipping deleted occurrences). No new permission is needed.
- **It tells you why.** The calendar result, the Connectors **Test** and `localagent doctor` all show the EventKit status: not installed, not asked yet, access denied, or ok.
- **New `localagent calendar-access` command.** It asks macOS for calendar access from Terminal, where the prompt reliably appears. The background agent no longer asks on its own.

## From 0.4.0 to 0.4.1 (complete calendars and cleaner replies)

1. Put the new files in one folder, open Terminal there, and run (no `sudo`):

   ```bash
   bash install.sh localaiagent-0.4.1-py3-none-any.whl
   localagent start
   localagent version
   ```

   The last line should print `0.4.1`. The models are already downloaded, so this takes a minute.
2. Open **Connectors** and press **Test** on **Calendar**. macOS asks _"Terminal would like full access to your calendars"_; click **Allow**.
   The test should then say "Found N event(s) **via EventKit**".
3. If no prompt appears, or the test still says "via AppleScript": open **System Settings → Privacy & Security → Calendars**, set **Terminal** to **Full Access**, then run `localagent stop` and `localagent start` from Terminal.

### What changed in 0.4.1

- **Complete calendars.** Calendar now reads through Apple's EventKit, so **repeating meetings**, invitations you haven't answered, and every account in Calendar (Gmail, Outlook/Exchange, iCloud) are included. Events that appear in two calendars are listed twice and labelled with the calendar they came from.
  - If full calendar access isn't allowed, the agent falls back to the old method and says that repeating events may be missing.
  - **Settings → Connectors → Calendar source** lets you force one method.
- **See the full list yourself.** Click the "✓ Found N event(s)" chip under a reply to expand every item the tool returned. This works for calendar, reminders, mail and files.
- **Cleaner replies.** No more stray reasoning text ending in `</think>`, and **bold** and bullet lists now render properly.

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
   localagent version
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
   localagent version
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
