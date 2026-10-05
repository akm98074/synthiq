# Testing Steps 3 + 4 (v0.4.1): proactivity and voice

Upgrade first with `UPGRADING.md` (about 10 minutes, mostly the speech-model download). This checklist takes about 25 minutes.

### If something fails

| You see | Fix |
|---|---|
| `localagent: command not found` | Run `~/.local/bin/localagent start`; to fix it for good: `pipx ensurepath && source ~/.zshrc`. |
| A tab is empty | Press **Cmd+Shift+R**. |
| Mic button greyed out, with a tooltip about the "voice add-on" | `pipx inject localaiagent mlx-whisper`, then `localagent setup --no-pull --voice`, then restart. |
| "Microphone blocked" | Allow the mic for `127.0.0.1:8765` in your browser's site settings (see `UPGRADING.md` step 5). |
| No notifications | **System Settings → Notifications → Script Editor → Allow notifications**. Also check quiet hours in Settings. |
| Calendar/Mail errors in a job | Same fix as before: **Privacy & Security → Automation → Terminal**. Then start the agent from Terminal. |

## 0. Calendar completeness (new in 0.4.1)

1. **Connectors → Calendar → Test**. Allow full calendar access, and check that it says "via EventKit".
2. In Chat, ask `What's on my calendar this week?`
3. Click the "✓ Found N event(s)" chip and compare the list with Calendar's week view. Repeating meetings, invitations and events that appear in both your Gmail and Outlook calendars should all be there.

## A. Proactivity (Nudges tab)

1. Open **Nudges** and press **Run now** on **Morning brief**.
   - Expected: a "☀️ Your brief for …" card with 4–8 lines about *your* real day, and the same brief in **Chat**.
   - Check: does it mention only real events, reminders and emails? Nothing made up?
2. Setup for the next step: in Reminders, create a reminder due **10 minutes ago** (for example "Test overdue"). In Calendar, create an event starting in **30 minutes**.
   Press **Run now** on **Check calendar, reminders and email**.
   - Expected: a ⏰ card for the reminder and a 📅 card for the event. A **macOS notification** appears, unless it's quiet hours.
   - Also expected: ✉️ "Reply to …" cards for real emails from the last 7 days that you haven't answered. Newsletters and receipts should be skipped.
3. Open **Decisions**. Each candidate email appears with **should nudge** (yes/no) and **urgency**. Correct a wrong one; the next check learns from it.
4. Press **Run now** again. There should be **no duplicates**.
5. On one card, press **Snooze 1 h**, then **Dismiss** another. Press **Ask about this** on a ✉️ card, and send it with e.g. "draft a reply saying yes".
6. Press **Run now** on **Overnight memory review**. A 🌙 card says what it learned and merged. Check **Memory** for duplicates.
7. In **Settings → Proactivity**, set quiet hours to cover *now* and run the check again: cards still appear, but no notification. Set it back afterwards.
8. Leave the agent running for a while (or overnight). The check runs every 30 min, and the brief arrives at 08:00.

## B. Voice (Chat tab)

1. **Hold the mic button**, say _"What's on my calendar today?"_, and release.
   - Expected: "Transcribing…", then your words appear as a message, the agent checks your calendar, and **reads the answer aloud**.
2. **Click the mic** (don't hold), say _"Remind me to stretch in ten minutes"_, and click again.
   - Expected: an approval card, and it says _"I need your OK on screen…"_. Approve by clicking.
3. **Space bar:** click on an empty part of the page, hold Space, say _"Any emails I haven't replied to?"_, then release.
4. **Conversation mode:** tick it, press the mic once, and ask _"What's the weather like for a picnic?"_; pause about a second.
   - Expected: it answers aloud and then **listens again by itself**. Ask a follow-up the same way.
   - While it's speaking, **click the mic** to interrupt.
5. **Settings → Voice:** pick another voice (for example _Samantha_ or _Daniel_) and a faster rate, then save and try again.

## Please send back

1. Install or upgrade output, if anything failed.
2. **Brief:** was it accurate? Too long or too short?
3. **Nudges:** which were right, which were noise, and which did it miss? Did notifications appear? Were there duplicates?
4. **Voice:** time from releasing the mic to the text appearing; transcription accuracy (accent, background noise); voice quality; whether conversation mode feels natural.
5. Any dropped or failed jobs (in **Nudges**, the job card shows "last: … (error)" or "(deferred)").

Known limits:
- Calendar needs **Full Access** (Privacy & Security → Calendars → Terminal) for complete results, including repeating events; otherwise it falls back to AppleScript and says so.
- Proactivity only runs while the Mac is awake and the agent is running; missed jobs run once when it's back.
- There's no always-listening wake word ("Hey Ari") yet. Use conversation mode instead.
- The overnight review waits until the Mac is plugged in.
- Notifications appear as "Script Editor".

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
