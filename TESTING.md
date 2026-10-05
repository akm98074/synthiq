# Testing Step 2 (v0.2.0) on your Mac: connectors and approvals

To upgrade first, follow `UPGRADING.md` (it takes about 2 minutes, and your memories are kept). This checklist takes about 20 minutes.

## 0. Install / upgrade

```bash
bash install.sh localaiagent-0.2.1-py3-none-any.whl     # no sudo
localagent start
localagent version                                     # 0.2.0
```

### If the install fails

| You see | Fix |
|---|---|
| `./install.sh: command not found` or `permission denied` | Use `bash install.sh …` instead of `./install.sh`. |
| `Please don't run this with sudo` | Run it again without `sudo`. |
| `Homebrew is required` | Install it from https://brew.sh, open a new Terminal window, re-run. |
| `localagent: command not found` | Run `~/.local/bin/localagent start`; to fix it for good: `pipx ensurepath && source ~/.zshrc`. |
| `Ollama didn't start` | Open the Ollama app (or `ollama serve` in another window), re-run. |

## 1. Give permissions (once)

Open the **Connectors** tab and press **Test** on each Apple app. macOS asks _"Terminal wants access to control …"_; click **Allow**.
Each test should then show a green result (for example "Found 2 event(s)").

If you clicked "Don't Allow" by mistake, go to **System Settings → Privacy & Security → Automation → Terminal** and switch the app on.

## 2. Things that run on their own (read / draft)

In **Chat**, try these. You should see grey "✓ …" chips under the reply, and no approval card.

- `what's on my calendar today?` (then `…this week?`)
- `what reminders do I have?`
- `any unread email?`, then `read the first one`
- `find the newest PDF in my Downloads`
- `search my notes for travel`
- `what's Sam's email address?` (use a real contact name)
- `make a pdf packing list for a beach weekend`. It saves to `~/Documents/LocalAIAgent/` and Finder opens.
- `make a spreadsheet of a monthly budget for rent, food, transport`
- `draft an email to <your own address> saying the test worked`. A Mail compose window opens; nothing is sent.

## 3. Things that ask first (write / danger)

- `remind me to call mom tomorrow at 6pm`. An **orange "write"** card appears. Pick **Just this once**, then **Approve**, and check that the reminder is in Reminders.
- `add a calendar event "Test" tomorrow at 3pm`. Approve it with **Until the agent restarts**. Ask for a second event; it should **not** ask again.
- **Approvals → Standing permissions**: **Revoke** that permission, ask again, and the card comes back.
- `send an email to <your own address> with subject Hello`: **Decline**. Nothing is sent, and the agent acknowledges it.
- Put a junk file in Downloads, then `move <file name> from Downloads to the trash`. A **red "danger"** card appears, and it only offers "Just this once". Approve it, and the file is in the Trash (use Finder to put it back).

## 4. Activity log

Open **Activity**. Every action, approval and refusal above is listed, and the banner says **"Audit chain intact"**.

## 5. Feedback to send

1. Install/upgrade problems (terminal output).
2. Connector **Test** results: which apps worked and which didn't (copy the error text).
3. For each prompt above: did it pick the right tool? Right dates/times? Any made-up results?
4. Approval cards: clear enough? Were the scopes understandable?
5. Speed: how long until the first tool chip appears, and until the final answer.
6. Anything it should have done on its own or asked about, but didn't (or the reverse).

Known limits in this step:
- Recurring calendar events only show their first occurrence (an AppleScript limit).
- Mail search looks at the unified Inbox only.
- Calendar searches over very large calendars can take a few seconds.

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
