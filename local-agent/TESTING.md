# Testing Step 5b (v0.6.0): browser and custom skills

Upgrade first with `UPGRADING.md`. This checklist takes about 20 minutes. If you haven't tested 5a (Messages) yet, its checklist is in the 0.5.0 package.

### If something fails

| You see | Fix |
|---|---|
| "The browser add-on isn't installed" | `pipx inject localaiagent playwright`, then `localagent setup --no-pull --browser`, then restart the agent. |
| "Couldn't start a browser" | Install Google Chrome, or run `localagent setup --no-pull --browser`. |
| A skill shows "Not loaded: …" | Fix what it names in that skill's `SKILL.md`, then open **Connectors** again. |
| "Skills that run scripts need macOS's sandbox" | Only on non-Mac computers; script skills need macOS. |

## A. Browser (Chat tab)

1. `Open bbc.com and tell me the top 3 headlines`
   - A separate browser window opens on BBC. The answer should match the page.
   - Click the "✓ Opened …" chip: no approval was needed.
2. `Search wikipedia for Lisbon and tell me its population`
   - It should type into Wikipedia's search box, run the search and read the answer.
3. `Open https://httpbin.org/forms/post, fill in the customer name "Test" and pick a large pizza`
   - The fields fill in, in the window. Nothing is submitted.
4. `Now submit the order`
   - Expected: a red **danger** approval card, "Press “Submit order” on …", with only **Just this once**. Click **Decline**, and nothing is sent. Ask again and **Approve**; the window shows the result page.
5. Ask it to log in somewhere. It should say that you need to type the password yourself in its window.

## B. Custom skills

1. In Terminal: `localagent skill new word-count`, then open **Connectors** and find **Custom skills → word-count**.
2. In Chat: `Make a word count of: the quick brown fox` should answer "4 words…".
3. Write an instructions-only skill. Paste this into Terminal as one block:

```bash
mkdir -p ~/Library/Application\ Support/LocalAIAgent/skills/packing
cat > ~/Library/Application\ Support/LocalAIAgent/skills/packing/SKILL.md <<'EOF'
---
name: packing
description: My personal packing checklist for trips
---
Always pack: passport, chargers, medication, running shoes.
EOF
```

4. Then ask `Use my packing skill for a 3-day trip to Paris`. The list should include your items.
5. Optional sandbox check: edit `word-count/main.py` to read `~/Library/Messages/chat.db`. The skill should fail with "Operation not permitted".

## Please send back

1. Anything that failed, with the exact message.
2. Browser: which sites worked or confused it? Was it too slow?
3. Did every submit, book or pay step ask you first?
4. Skills: was it clear how to write one? What skill would you want first?

Known limits:
- A small local model gets lost on long multi-step sites (checkouts, travel booking). Short tasks work best.
- Sites with CAPTCHAs or bot checks may block the agent's window.
- The agent's browser is separate from yours: no shared logins or cookies.

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
