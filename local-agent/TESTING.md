# Testing Step 7g (v0.15.0): Windows and Linux

On the Mac, 0.15.0 behaves like 0.14.0. A quick check there: `localagent doctor` is all green or amber as before, and voice, notifications and a custom skill still work.

What was verified before release: the full test suite (173 tests) on Linux, with the Windows and Linux code paths unit-tested; the Linux skill sandbox tested against real bubblewrap (the skill can't read your SSH folder or the network); the installer scripts parsed; CI runs on Ubuntu, macOS and Windows. **Not yet tried on a real Windows PC or Linux desktop**: please do the checks below if you have one.

### If something fails

| You see | Fix |
|---|---|
| Windows: "running scripts is disabled on this system" | Run it exactly as shown: `powershell -ExecutionPolicy Bypass -File install.ps1 …` |
| Windows: `localagent` not found after install | Open a new PowerShell window (pipx added it to PATH). |
| Linux: voice button says the add-on is missing | `pipx inject localaiagent faster-whisper pyttsx3` |
| Linux: no spoken replies | `sudo apt install espeak-ng`, then restart the agent. |
| Linux: a skill says it needs a sandbox | `sudo apt install bubblewrap`. On Ubuntu 24.04, if bwrap reports "Permission denied" for user namespaces, see `localagent doctor`. |

## Checks (Windows or Linux)

1. Install as in `UPGRADING.md`. The installer finishes with "Done" and `localagent doctor` shows the platform line "Calendar, Contacts, Messages … need macOS".
2. `localagent start`. The app opens at http://127.0.0.1:8765. Chat: _"Remember that my favourite tea is masala chai"_, then _"What tea do I like?"_.
3. _"Find the price of onions at Safeway Sammamish"_. Your Chrome opens, searches and answers.
4. Settings → turn on a nudge (e.g. **Test nudge** if shown) or wait for one. A desktop notification appears.
5. Press the mic, say _"What time is it?"_. It understands you (the first time it downloads the speech model) and the 🔊 button reads a reply aloud.
6. Linux only: `localagent skill new word-count`, then ask _"How many words in 'one two three'?"_ and approve. It answers 3 words.
7. `localagent autostart on`, sign out and back in: the agent is running. `localagent autostart off`.

## Please send back

1. Which OS and version, and did the installer finish without errors?
2. Which check failed, with the message.
3. Speech recognition speed on your machine (seconds from stopping speaking to the text).

Logs: `%LOCALAPPDATA%\LocalAIAgent\server.log` (Windows) or `~/.local/share/LocalAIAgent/server.log` (Linux).
