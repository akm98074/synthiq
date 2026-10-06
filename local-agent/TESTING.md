# Testing v0.16.2: security fixes and the Trust & Transparency center

Do the steps in `UPGRADING.md` first (about 5 minutes). This checklist takes about 20 minutes.

**Verified before release:**
- 219 automated tests on Linux, including:
  - the review's attacks: a foreign Host, no secret, a cross-site POST;
  - an email injection the pattern scanner misses;
  - a phone PIN brute force;
  - an unverified friend's agent.
- A real browser run:
  - sign-in;
  - the full approval payload;
  - the Trust tab with toggles, confirmation, pause and presets;
  - running the checks and downloading the export (hashes and redaction checked);
  - safety codes on two agents;
  - phone width.
- CI on Ubuntu, macOS and Windows.

**Only your Mac can verify:**
- the LocalAIAgent app and its permission prompts;
- the tighter skill sandbox;
- real calls with a PIN.

### If something fails

| You see | Fix |
|---|---|
| `localagent start`: "_LSOpenURLsWithCompletionHandler() failed … error -10669" | Install 0.16.2. Or, right away: `rm -rf ~/Applications/LocalAIAgent.app && localagent start` (the agent then runs from Terminal). |
| "Couldn't start LocalAIAgent.app …; starting from Terminal instead" | The agent works; macOS refused the app. Retry with `localagent app install` and send the message it prints. |
| "Open LocalAIAgent from its app or Terminal" | Run `localagent open` (or `localagent start`). Your browser stays signed in afterwards. |
| macOS asks for Calendar/Automation/Full Disk Access again | Expected once: answer **Allow** for **LocalAIAgent**. For Messages: System Settings → Privacy & Security → Full Disk Access → turn on LocalAIAgent. |
| Messages or Mail say "disabled" | New installs start with them off: Trust tab → switch them on. |
| A custom skill now fails to start on the Mac | Send the error. The stricter sandbox may need the skill's Python location allowed. |
| Phone: "This phone line needs a PIN first" | Settings → Phone line → Phone PIN → Save PIN. |

## Checks

**Sign-in**
1. Open http://127.0.0.1:8765 in a private window. You see "Open LocalAIAgent from its app or Terminal", not your chats.
2. `localagent open`. The app opens normally.

**Mac app identity**
3. `localagent app install` prints "self-test passed", or explains that macOS wouldn't launch the app (then the agent runs from Terminal; please send that message). `localagent doctor` shows "permissions identity: LocalAIAgent.app" in the first case.
4. Ask _"What's on my calendar today?"_. If macOS asks, the prompt names **LocalAIAgent**.

**Trust tab**
5. Open **Trust**. The top line reads "Everything runs on this computer. N things left it in the last 7 days."
6. Each capability shows its risk, what it reads, what can leave, its safeguards and its system permission. On the Mac, click a permission name: System Settings opens on that page.
7. Switch **Screen context** on. A dialog explains the risk. Cancel, and it stays off.
8. Choose **Assistant**, then ask _"Send an email to me saying test"_. It refuses (Assistant never sends) and offers a draft. Choose **Agent** again.
9. Press **⏸ Pause** at the top. The tab says the agent is paused. Ask _"Remind me to call mom"_: it doesn't create the reminder. Press **▶ Resume**.

**Approvals and data leaving**
10. Ask _"Read my latest email and summarise it"_ (Mail or Gmail on), then _"Search the web for the sender's company"_. Searching words that weren't in your message asks first, and the card says why.
11. Ask _"Send an email to yourself saying hello"_. The approval card shows the full email open, with "Why it asks". Approve once.
12. **What left this computer** lists the email, with "you approved".

**Verify & export**
13. Set **From** to a week ago, then press **Run checks**. You see findings such as "Every action had your approval…" and "Activity log integrity: verified".
14. Press **Download record**. Open the zip:
    - `README_FOR_REVIEWER.md` explains the files;
    - email addresses appear as `<EMAIL_1>`;
    - `manifest.json` lists a SHA-256 for each file.
15. Optional: upload the zip contents to Claude or ChatGPT with the prompt from the README, and send us its verdict.

**Phone and trusted agents** (if you use them)
16. Call your number. It asks for your PIN. Type it and press #. A wrong PIN three times hangs up.
17. Trusted agents: both of you see the same 4 emoji. Press **They match** on both sides.

## Please send back

1. Did any step behave differently from the description?
2. Is anything in the Trust tab unclear or missing (wording, risks, controls)?
3. The AI reviewer's verdict on your export, if you tried step 15.

Logs: `~/Library/Application Support/LocalAIAgent/server.log` (Windows: `%LOCALAPPDATA%\LocalAIAgent\server.log`, Linux: `~/.local/share/LocalAIAgent/server.log`).
