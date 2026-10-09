# Upgrading LocalAIAgent

Upgrading keeps everything you've built up: memories, conversation history, decision corrections and settings. They live in `~/Library/Application Support/LocalAIAgent/` (Windows: `%LOCALAPPDATA%\LocalAIAgent`, Linux: `~/.local/share/LocalAIAgent`), which the installer never touches.

## From 0.17.1 to 0.17.2 (Mail "ran out of application memory")

```bash
bash install.sh localaiagent-0.17.2-py3-none-any.whl
localagent start
```

**Why:** the agent asked Mail.app over AppleScript to search your whole inbox every 30 minutes, and loaded whole messages just to show a short preview. Mail keeps much of that in memory, so it grew until macOS showed "Your system has run out of application memory" with Mail paused at tens of GB.

**What changed:**
- The agent now reads Mail's own index file (read-only), the same way it reads Messages. Background checks no longer ask Mail.app for anything.
- If that index can't be read on your Mac, it uses a small script that looks only at your newest inbox messages, at most every 3 hours. It skips the check if Mail is already using over 2 GB, or didn't answer in time recently.
- Trust → Verify & export → Safety checks shows "Mail isn't slowed down by the agent", with which way it reads your mail.

**After upgrading:**
1. Quit Mail once (Force Quit if it's paused) and reopen it.
2. Keep **Mail (Apple)** switched on.
3. Full Disk Access for LocalAIAgent (already needed for Messages) lets it read Mail's index.

## From 0.17.0 to 0.17.1 ("Hey Ari" heard but nothing happened; "null" in Trust)

```bash
bash install.sh localaiagent-0.17.1-py3-none-any.whl
localagent start
```

A fix for the wake word. In 0.17.0, "Hey Ari" could show under the chat box as "Heard “…”" without the command going into the chat. The speech model sometimes adds sound labels such as `[BLANK_AUDIO]` or `(music)`, or keeps filler words ("Okay, so hey Ari", "Hey, uh, Ari"), and those made the phrase look like it wasn't at the start. They are now ignored. Also fixed: a stray word "null" in the Trust tab (under "All good" and under Ask answers).

Nothing else changes, and you don't need to sign in again.

If it still shows "Heard “…”, not “Hey Ari”", please send the exact text in quotes: it shows which wording is still missed.

## From 0.16.2 to 0.17.0 (Trust tab redesign, wake word fix, security hardening)

```bash
bash install.sh localaiagent-0.17.0-py3-none-any.whl
localagent start
```

Windows: `powershell -ExecutionPolicy Bypass -File install.ps1 localaiagent-0.17.0-py3-none-any.whl`.

**One thing to expect:** the first time 0.17.0 starts, it replaces the app's sign-in secret. In 0.16, that secret was part of the sign-in link, so it may sit in your browser history. A browser tab that was open before shows "Open LocalAIAgent from its app or Terminal": run `localagent open` once. From now on, sign-in links carry a one-time code that works once, for 60 seconds.

What's new:
- **Trust tab.** A single status line ("All good" or "N need your attention") with Pause and the trust preset, then four sub-tabs: Overview, Capabilities, Activity, Verify & export. Capabilities are one line each; open a row for the details. **Run checks** now finishes in about a second, even with a large address book (it used to run for minutes and freeze the app). It shows how long it took.
- **Ask about privacy & security.** Type a question in Trust → Overview, or ask in chat: "What did you send last week?", "Who can control you?", "Is screen context on?". Answers come from the agent's own records, and show what they're based on.
- **"Hey Ari" works.** Browsers keep the microphone audio paused until you click the page. The app now says "Click anywhere on this page to start listening" until you do. If the wake word can't work, it now says why instead of staying silent. Switching **Wake word** on in Trust also turns Voice on.
- **Responsiveness.** The Trust status no longer re-reads the whole activity log every minute, so the app stays quick as the log grows.
- **Security.** Custom skills can no longer reach the keychain or the Secret Service. After 5 wrong phone PINs in an hour the phone line locks for an hour (saving a new PIN unlocks it). The sign-in link no longer contains the secret.

## From 0.16.1 to 0.16.2 (fix for "error -10669" on the Mac)

```bash
bash install.sh localaiagent-0.16.2-py3-none-any.whl
localagent start
```

If `localagent start` failed with **"_LSOpenURLsWithCompletionHandler() failed … error -10669"**, this fixes it:
- The LocalAIAgent app is now built on your Mac with Apple's `osacompile`, which makes an app macOS will launch. The installer launches it once to check.
- If macOS still won't run it, the installer removes it, and the agent runs from Terminal (as in 0.15).
- `localagent start` never gets stuck on the app again: if the app won't open, it says so and starts from Terminal instead.

`localagent doctor` shows which one is in use: "permissions identity". To try the app again later, run `localagent app install`.

## From 0.16.0 to 0.16.1

```bash
bash install.sh localaiagent-0.16.1-py3-none-any.whl
localagent start
```

A bug fix: a reminder or calendar event could occasionally produce a second, duplicate nudge. Nothing else changes, and your data and settings are kept. If you're coming from 0.15 or earlier, also read the 0.16.0 notes below: they explain the sign-in, the Mac app, the phone PIN and the Trust tab.

## From 0.15.0 to 0.16.0 (security fixes and the Trust & Transparency center)

```bash
bash install.sh localaiagent-0.16.0-py3-none-any.whl
localagent start
```

Windows: `powershell -ExecutionPolicy Bypass -File install.ps1 localaiagent-0.16.0-py3-none-any.whl`.

**Read this first: a few things change for you.**

1. **Open the app with `localagent start` or `localagent open`.** For your privacy, the app now opens only for you. An old bookmark to http://127.0.0.1:8765 shows "Open LocalAIAgent from its app or Terminal" until your browser is signed in. `localagent open` signs it in, and it stays signed in.
2. **Mac: a LocalAIAgent app.** The installer creates `~/Applications/LocalAIAgent.app`, and `localagent start` runs the agent as that app. macOS asks once more for each permission, now under the name **LocalAIAgent**: Calendar, Automation, Full Disk Access for Messages, Accessibility. If you gave Terminal Full Disk Access only for the agent, you can switch Terminal off in System Settings → Privacy & Security → Full Disk Access.
3. **Phone line: set a PIN.** Calls are refused until you do. Use Settings → Phone line → Phone PIN, or run `localagent phone setup`. Every call asks for it, because caller ID can be faked.
4. **Trusted agents: compare safety codes once.** Each pairing shows 4 emoji. Check with your friend, on a call or in person, that you both see the same ones, then press **They match**. Until then nothing is answered automatically for their agent, and you can't ask it things.
5. **Some changes ask you to confirm.** Turning on screen context, the cloud model, the phone line, friends' agents or the iMessage channel shows what the change risks and asks first. Every settings change appears in Activity.

### What changed in 0.16.0

- **New Trust tab** (first in the bar):
  - every capability, with an on/off switch, its risk, what it reads, what can leave this computer, its safeguards, the system permission it needs (with a link on the Mac), and when it was last used;
  - **trust presets**: Observer (only looks), Assistant (also drafts), Agent (also acts, with your approval);
  - **Pause**, a button at the top: the agent only answers you, read-only. Also `localagent pause` / `resume`, or text "pause" / "resume";
  - **What left this computer**: every search, page, email, message and answer that went out;
  - **Safety checks**, and **Verify & export**: pick dates, run the app's own checks (personal data, actions without approval, injection attempts, log integrity), and download a record you can check yourself or give to Claude or ChatGPT to review. A reviewer prompt is included, and personal data is hidden unless you choose otherwise.
- **Safer by design** (all must-fix and high-priority items from `docs/SECURITY_REVIEW.md`):
  - Other programs and websites can't use the app.
  - After reading an email, a chat or a web page, nothing can be sent out without your OK, even if you had allowed it before.
  - Approvals show the full email or message, and say why they ask.
  - "Always" permissions apply only to that recipient or site, and expire after 30 days.
  - Programs and scripts are never opened.
  - Calendar invites, notes and contacts are treated as written by others.
  - Custom skills on the Mac can't read your home folder or drive other apps.
  - Your data folder is readable only by you.
- **New installs** start with Messages, WhatsApp, Mail, Contacts and Mac apps off; turn on what you want in the Trust tab. **Upgrades keep your current choices.**

## From 0.14.0 to 0.15.0 (Step 7g: Windows and Linux)

On the Mac nothing changes in how you use it:

```bash
bash install.sh localaiagent-0.15.0-py3-none-any.whl
localagent start
```

To install on a **Windows 10/11** PC: copy `install.ps1` and the `.whl` into one folder, open **PowerShell** (not as Administrator) in that folder, and run:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 localaiagent-0.15.0-py3-none-any.whl
```

On **Linux** (Ubuntu 22.04+, Debian 12+, Fedora): `bash install.sh localaiagent-0.15.0-py3-none-any.whl`. For custom skills that run scripts also install bubblewrap (`sudo apt install bubblewrap`); for spoken replies install eSpeak (`sudo apt install espeak-ng`).

### What changed in 0.15.0

- **Runs on Windows and Linux:** chat, memory, Files, Documents, Gmail, web look-ups, your Chrome, cloud model, avatar, trusted agents, phone line, voice and notifications. The Apple apps stay Mac-only, and `localagent doctor` says which parts need a Mac.
- **Voice off the Mac:** speech recognition with faster-whisper (on the computer, no cloud), speech with the Windows voices or eSpeak.
- **Notifications** use Windows toasts or the Linux desktop's notifications. The text is never pasted into a command.
- **Custom skills on Linux** run inside a bubblewrap sandbox: no network unless the skill asks for it, a private /tmp, and your private folders (SSH and cloud keys, browser profiles, keyrings, the agent's own data) hidden. On Windows, skills that run scripts are refused until a sandbox exists there; instruction-only skills work.
- **`localagent autostart on`** works on Windows (Startup folder) and Linux (desktop login), as on the Mac.

## From 0.13.0 to 0.14.0 (Step 7f: call your agent)

```bash
bash install.sh localaiagent-0.14.0-py3-none-any.whl
localagent start
```

Off by default. Setting it up takes about 15 minutes and needs a Twilio account (a US number is about $1.15/month plus about 1–2¢ per minute).

1. At https://www.twilio.com sign up, then buy a phone number with **Voice**. On the console's front page, copy the **Auth Token**.
2. Install a tunnel so Twilio can reach your Mac: `brew install cloudflared`.
3. In Terminal run `localagent phone setup` and paste the auth token; it goes into your Keychain. Then start the tunnel it shows and **leave that window open**:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:8767
   ```

   It prints an address like `https://words-words.trycloudflare.com`.
4. In the app: **Settings → Phone line**: tick **Answer calls**, enter your own mobile number (with country code, e.g. `+14255550100`), paste the tunnel address as **Public URL**, and **Save**.
5. In the Twilio console, open your number → **Voice** → **A call comes in**: **Webhook**, URL `<tunnel address>/twilio/voice`, **HTTP POST**. Save.
6. Call your Twilio number from your mobile.

The free tunnel address changes every time cloudflared restarts; repeat steps 4–5 then. A named Cloudflare tunnel or Tailscale Funnel gives a fixed address.

### What changed in 0.14.0

- **Call your agent** from your own phone: "What's on my calendar tomorrow?", "Any emails from Priya?", "Find the price of onions at Safeway Sammamish". It answers in short spoken sentences, then asks "Anything else?". Say "goodbye" to hang up.
- **Safe by phone:** it can look things up and prepare drafts, but it never sends, changes or deletes anything by phone; it tells you to approve that in the app.
- **Only you:** only your own numbers are answered (others hear "this number is private"), and every request must be signed by Twilio with your auth token. Calls and rejected attempts appear in **Activity**.
- **Privacy note:** Twilio recognises your speech and speaks the answers, so a call passes through Twilio (cloud). Everything else stays on your Mac. The tunnel only reaches the small phone listener, never the app itself.

## From 0.12.0 to 0.13.0 (Step 7e: trusted agents)

```bash
bash install.sh localaiagent-0.13.0-py3-none-any.whl
localagent start
```

Off by default. To pair with a friend who also runs LocalAIAgent:

1. Both of you: **Settings → Trusted agents → Turn on trusted agents**, then **Save**. macOS may ask whether Python may accept incoming connections; click **Allow**.
2. You: press **Create an invite** and send the code (it starts with `la1-`) to your friend, by iMessage for example. It works once, for 7 days.
3. Your friend pastes it under **Accept** and presses **Accept**. You each now see the other's agent.
4. Tick what the friend's agent may do without asking you: **See when you're busy** (times only, never titles) and/or **Leave you messages**.

Both Macs must reach each other: the same Wi-Fi, or both on [Tailscale](https://tailscale.com) (free), which works anywhere. With Tailscale, put your Tailscale address in **How friends reach this Mac**, e.g. `http://100.101.102.103:8766`, before creating the invite.

### What changed in 0.13.0

- **Ask a friend's agent:** "is Sam free Thursday afternoon?", "leave Sam's agent a message that I'll be late", "ask Sam if he can do dinner Friday". Sending always shows an approval card first.
- **What their agent can do without you:** see your busy times (if allowed) and leave you messages (a nudge). Any other question becomes a nudge **"Sam's agent asks …"** with a **Reply** button; nothing is answered for you.
- **End-to-end encrypted** with keys that never leave your Macs (yours is in the Keychain). Messages that are tampered with, replayed, older than 5 minutes, or from agents you haven't paired are rejected and logged in **Activity**.

## From 0.11.0 to 0.12.0 (Step 7d: a face that talks)

```bash
bash install.sh localaiagent-0.12.0-py3-none-any.whl
localagent start
```

Under the chat box, tick **Face**. Your agent's face appears above the conversation.

### What changed in 0.12.0

- **A face that talks.** With **Face** on, spoken replies play in the app instead of through the Mac's speaker directly, and the mouth moves with the voice, louder syllables open it wider. It blinks, smiles when idle, and follows your light or dark theme.
- **🔊 on every reply** reads that reply aloud (with or without the face).
- It works with voice input, conversation mode and "Hey Ari". Clicking the mic stops it talking.
- The voice and speed are still set in **Settings → Voice**.

## From 0.10.0 to 0.11.0 (Step 7c: optional cloud model)

```bash
bash install.sh localaiagent-0.11.0-py3-none-any.whl
localagent start
```

Nothing changes until you turn it on. To use it:

1. Get an API key at https://console.anthropic.com (Settings → API keys). Usage is billed by Anthropic to you.
2. In the app: **Settings → Cloud model (optional)**. Paste the key and press **Save key**; it goes into your Keychain. Tick **Allow asking the cloud model**, then **Save**.
   - Or in Terminal: `localagent cloud-key`.

### What changed in 0.11.0

- Start a question with **"think harder"**, **"use the cloud"** or **"ask Claude"**, for example _"think harder: compare these two mortgage offers…"_. You'll see an approval card that names the cloud model and shows exactly what will be sent: your question, plus how many earlier messages and memories go with it.
  - Approve **Just this once**, **For 1 hour**, and so on.
  - Decline, and nothing leaves your Mac.
- The answer streams back into the chat, marked **"(cloud)"**. The cloud model only answers: it can't use your calendar, mail, files or browser.
- Settings:
  - the model (default **Claude Opus 5.5**) and effort (default **high**);
  - whether relevant memories are included (on);
  - **Also offer it for the hardest questions** (off): asks to escalate when the agent rates a question as very hard.
- If Anthropic's safety checks decline a question, the request is automatically retried on another Claude model that Anthropic picks (its "fallbacks" option). If that declines too, you're told.

## From 0.9.0 to 0.10.0 (Step 7b: Gmail sign-in)

```bash
bash install.sh localaiagent-0.10.0-py3-none-any.whl
localagent start
```

### Connect Gmail (one-time, about 5 minutes)

Google requires every app that reads Gmail to have its own "OAuth client". You create one for yourself; nobody else is involved and it's free.

1. Open https://console.cloud.google.com and sign in with your Gmail account. Create a project, for example **LocalAIAgent** (top bar → project picker → **New project**).
2. **APIs & Services → Library**: search for **Gmail API** and click **Enable**.
3. **Google Auth Platform → Branding** (older consoles call it **OAuth consent screen**): app name `LocalAIAgent`, your email as support and developer contact. Save.
4. **Audience**: user type **External**. Then click **Publish app** and confirm. This stops Google from asking you to sign in again every 7 days. Your app stays private; it just isn't "verified", which is fine for your own use.
5. **Clients → Create client**: application type **Desktop app**, name `LocalAIAgent`. **Create**, then copy the **Client ID** and **Client secret**.
6. In the agent: **Settings → Gmail**, paste both, and press **Save and connect Gmail**.
   - A Google tab opens. Pick your account. Google says _"Google hasn't verified this app"_ because it's your own; click **Advanced → Go to LocalAIAgent (unsafe)**, then **Allow**.
   - The tab says _"Gmail connected as …"_. Close it. Settings shows **Connected as you@gmail.com**.

Alternatively run `localagent gmail-login` in Terminal; it asks for the same two values.

### What changed in 0.10.0

- **Gmail directly.** "Any unread emails from Priya?", "what did the bank email say?", "draft a reply to Sam's lunch email saying Thursday works": these now use Gmail itself, including labels and Gmail's search syntax.
  - Drafts appear in Gmail's **Drafts** (on your phone too). Sending asks first.
- **Nudges and the brief** use Gmail for "waiting on your reply". The same email seen in Apple Mail and Gmail gives one nudge, not two.
- **Keychain vault.** The client secret and the Gmail sign-in are stored in your **login Keychain** (item "LocalAIAgent"), never in the config file, and never shown to the model. macOS may ask once to allow access; click **Always Allow**.
- **Disconnect** any time in Settings, or remove access at https://myaccount.google.com/permissions.

## From 0.8.0 to 0.9.0 (Step 7a: "Hey Ari" wake word)

```bash
bash install.sh localaiagent-0.9.0-py3-none-any.whl
localagent start
```

The installer downloads the small wake-word model (about 75 MB) along with the speech model.

Then, under the chat box, tick **Hey Ari** (or **Settings → Voice → Wake word**). If the browser asks, allow the microphone. The status line says _Listening for “Hey Ari”_.

### What changed in 0.9.0

- **Say "Hey Ari"** any time the app's page is open (it can be in the background). You hear a short chime, then say what you want; or say it in one go: "Hey Ari, what's on my calendar today?". The answer is spoken, and it goes back to listening for the wake phrase.
- It follows your agent's name: rename the agent to Max and it's "Hey Max". You can add extra phrases in Settings.
- **Private:** every short burst of speech is transcribed on your Mac by a tiny model and thrown away unless it starts with the wake phrase. Nothing is recorded or saved. It never wakes on its own spoken replies.
- Untick **Hey Ari** to switch it off; the microphone is then released.

## From 0.7.2 to 0.8.0 (Step 6: text your agent from your iPhone)

```bash
bash install.sh localaiagent-0.8.0-py3-none-any.whl
localagent start
```

Then, in the app, open **Settings → Text me (iMessage)**:

1. Tick **Let me talk to the agent by iMessage from my phone**.
2. Leave **How** on **Text myself** (recommended).
3. Enter **your own** phone number and/or Apple ID email, the ones your iPhone uses for iMessage. For example `+1 425 555 0100, me@icloud.com`.
4. **Save**, then press **Send a test message**. A text from yourself starting with 🤖 should arrive on your iPhone.

Now, on your iPhone, open the conversation **with yourself** (your own name or number) and text, for example, `Ari, what's on my calendar tomorrow?`. Start with the agent's name. The answer arrives in the same chat within a few seconds, starting with 🤖.

This needs the Mac awake, the agent running, and the same Full Disk Access as the Messages connector (0.5.0).

### What changed in 0.8.0

- **Text your agent.** Anything you can type in the app works by text: questions, look-ups, reminders, emails, web tasks.
- **Approve by replying.** When something needs your OK, the text says what, and you reply:
  - `yes` (just this once), `yes 1h`, `always`, or `no`;
  - danger actions (buying, deleting) take only `yes` or `no`.
- **Nudges and the morning brief by text** (setting on by default). Quiet hours still apply.
- **Only you.** Only messages you send to yourself starting with the agent's name are read. Messages from anyone else are never answered; they're noted in **Activity**.
- **Alternative for a spare Mac:** give the agent its own Apple ID in Messages, then choose "The agent has its own Apple ID". You then text that Apple ID like a person.
  - Messages holds only one Apple ID at a time, so don't do this on the Mac where you read your own chats.

## From 0.7.1 to 0.7.2 (the agent uses your real Google Chrome, and you can watch it)

```bash
bash install.sh localaiagent-0.7.2-py3-none-any.whl
localagent setup --no-pull --browser
localagent start
```

The middle command opens Chrome once with the agent's own profile, loads a test page and closes it. It should print `Browser works: Google Chrome 1xx …`. If it fails, it prints the exact reason; please send me that line.

### What changed in 0.7.2

- **Real Google Chrome, reliably.** The agent now starts your installed Google Chrome itself (from /Applications or ~/Applications), on its own separate profile, and connects to it. It no longer depends on Playwright's own copy of Chromium, which is what failed before.
  - It runs next to your normal Chrome without touching your tabs or logins.
  - Close its window any time: the next web task opens it again, still signed in to whatever you signed in to there.
  - If something goes wrong, the error says exactly what Chrome reported.
- **Watch it work, like Muse.** In the agent's Chrome window, a cursor glides to each button or field, a green ring and label show what it's doing ("Ari: clicking “Add to Cart”"), and typing appears letter by letter. A status pill in the corner says the current step, and each step pauses briefly so you can follow.
  - Turn it off, or change the pause, in **Settings → Connectors**.
- **Live view in the chat.** After each browser step, the chat shows a small picture of the page. Click it to enlarge.

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

   The last line should print `0.6.0`. The installer adds the browser add-on. The agent uses your **Google Chrome** with its own separate profile.
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
