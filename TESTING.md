# Testing Step 1 (v0.1.2) on your Mac

Allow about 30 minutes, most of it downloading models.

## 1. Install

Put all the downloaded files in one folder, open Terminal in that folder (`cd ~/Downloads` or wherever they are), and run the installer **without `sudo`**. Homebrew asks for your password itself if it needs it.

```bash
bash install.sh localaiagent-0.1.2-py3-none-any.whl
localagent doctor        # every line should be ✅ (platform may be ✅ or ⚠️)
localagent start         # opens http://127.0.0.1:8765
```

If anything fails here, please send the full terminal output.

### If the install fails

| You see | Fix |
|---|---|
| `./install.sh: command not found` or `permission denied` | Downloads lose their "executable" flag. Use `bash install.sh …` instead of `./install.sh`. |
| `Please don't run this with sudo` | Run it again without `sudo`. |
| `Homebrew is required` | Install it from https://brew.sh, open a new Terminal window, re-run. |
| `localagent: command not found` after installing | Run `~/.local/bin/localagent start` now; to fix it for good run `pipx ensurepath && source ~/.zshrc` (or open a new Terminal window). |
| `Ollama didn't start` | Open the Ollama app, or run `ollama serve` in another Terminal window, then re-run the installer. |

## 2. Chat and decisions

Under each message you send, chips show the **intent**, its **confidence**, the **backend** (`prototype` or `prototype+slm` if it escalated) and the **latency**. Amber chips mean low confidence.

Try these and note whether the intent looks right:

- `hey, how's it going?` → chit-chat
- `why do onions make you cry?` → quick answer
- `draft a short apology email for missing the meeting` → task
- `remind me to call mom at 6pm` → schedule (it should say it can't set reminders yet)
- `clean up my downloads folder` → computer action (it should say it can't act yet)

## 3. Memory

1. Send: `I'm vegetarian and I prefer window seats on flights`. You should see "remembered: …" chips.
2. Send: `what do you know about me?`. It should mention both facts.
3. Send: `suggest a dinner for tonight`. It should take the vegetarian preference into account.
4. Open **Memory**: edit one fact, then **Forget** the other. Check that the identity file at the bottom updates.
5. Ask `what do you know about me?` again. The forgotten fact must not appear.

## 4. Teach it

1. Open **Decisions**. Find a message whose intent was wrong (or use "Try a message" with something ambiguous like `ship it`).
2. Pick the right label and press **Save correction**.
3. Try a similar message. It should now lean towards your label.

## 5. The Phase-0 gate

```bash
localagent eval decision                       # default hybrid backend
localagent eval decision --backend prototype   # fastest path only
localagent eval decision --backend slm         # SLM judge only (slow)
```

Please send the three summary tables. The target is intent accuracy ≥ 90% and ECE ≤ 0.05 with p95 latency under 50 ms for the prototype backend. If it misses, Step 2 starts by improving the decision layer, for example with a stronger embedding model (`localagent setup --embed-model nomic-embed-text`), more examples, or temperature calibration.

## 6. Models and settings

- **Models**: check what's loaded and the RAM. Press **Unload** and watch memory drop.
- **Settings**: rename the agent and change its tone, then chat. Optionally switch the chat model to `qwen3:8b` if you have 24 GB+ (`ollama pull qwen3:8b` first).

## Feedback to send

1. Install problems, if any (with terminal output).
2. The `eval decision` tables.
3. Messages where the intent was wrong, and how often it escalated.
4. Reply speed: time to first word for short and long answers.
5. Memory: did it save the right things? Too much, too little?
6. Anything you'd change before Step 2 (connectors and approvals).

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
