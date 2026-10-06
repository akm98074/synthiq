# Testing Step 5c (v0.7.0 / 0.7.1): Mac apps, form filling, screen context

Upgrade first with `UPGRADING.md`, including **Accessibility** for Terminal (and Screen Recording if you'll try screen context). This checklist takes about 20 minutes. The 5a and 5b checklists are in the 0.5.0 and 0.6.0 packages.

### If something fails

| You see | Fix |
|---|---|
| "macOS needs Accessibility permission…" | Accessibility → Terminal on, then quit Terminal (Cmd+Q), reopen it, and run `localagent stop` and `localagent start`. |
| "macOS hasn't allowed screen reading" | Run `localagent screen-access`, allow Terminal under **Screen & System Audio Recording**, quit and reopen Terminal, restart the agent. |
| "Screen reading needs the screen add-on" | `pipx inject localaiagent pyobjc-framework-Vision pyobjc-framework-Quartz`, then restart. |
| "The window changed; read it again." | Expected if the app changed between reading and pressing. Ask again. |
| Shortcuts errors | Open the Shortcuts app once, and check the shortcut runs there by itself. |

## A. Mac apps and Shortcuts

1. `What apps are open?` The list should match your Dock, with the front one marked.
2. In the Shortcuts app, make a simple shortcut called **Test Agent** (for example, "Show Notification: hello"). Then ask `Run my Test Agent shortcut`.
   - An approval card appears. Approve **For 1 hour**, and the notification shows.
   - Ask again: it should run without asking.
3. Open **Notes** with a new note, then ask `Read the Notes window`. You should see numbered buttons and fields.
4. `In Notes, press the button to make a checklist` (or another button you can see). An approval card names the exact button.
5. Ask it to read **Keychain Access** or **System Settings**. It should refuse.

## B. Form filling

1. Tell it about yourself first, if you haven't: `My full name is …`, `My email is …`, `I live in <city>`.
2. `Open https://httpbin.org/forms/post`, then `Fill in the form for me`.
   - Fields fill in, in the agent's browser window. The reply lists each value and the fact it came from, and what's left for you.
   - Nothing is submitted. Saying `Submit it` shows the red danger approval.

## B1. Look-ups (0.7.1)

1. `Find price of onion in Safeway Sammamish`
   - Expected: a "✓ Searched the web" chip, then the agent opens safeway.com in its window and searches for onions. The answer gives a price and the link, and notes that prices can vary by store.
   - Safeway may ask you to pick a store or ZIP code. Pick Sammamish in the agent's window once, and ask again.
2. `Chutneys Bellevue`
   - Expected: what it is (an Indian restaurant), address, hours, phone and rating, with a link.
3. `Is Trader Joe's Redmond open now?` and `Weather in Seattle this weekend` should both be searched, not guessed.
4. `What is the capital of Portugal?` should be answered directly, with no search chip.
5. If you see "The search engine asked for a robot check", the agent switches to Bing in its window. Tell me if that happens often.

## B2. Shopping (0.7.1)

1. In the agent's browser window (it opens on the first web task), go to amazon.com and **sign in yourself** once. The agent stays signed in after that, in its own window only.
2. Ask `Find a stainless steel electric kettle under $40 on Amazon and add the best-rated one to my cart`.
   - Expected: it searches, opens a product, and shows a red approval card for **Add to Cart**. Approve it.
   - Then it **stops** and summarises the item, price and delivery. It shouldn't go to checkout.
3. Optional: `Go ahead and place the order`. Every step (checkout, Place your order) shows its own approval card. Decline at the last one if you don't want the kettle.
4. If a payment field appears, the agent should say you need to fill it in yourself.

If Amazon shows a CAPTCHA, solve it in the window and ask again. Amazon's terms restrict automated shopping, so keep this to occasional personal use.

## C. Screen context (optional)

1. Turn it on in **Settings → Screen context** and **Save**.
2. Open a web article, then ask `What's on my screen?` It should describe the article.
3. Switch to **Messages** and ask again. It should say Messages is on the private-apps list.
4. Wait 5–10 minutes while reading something, then ask `What was I reading 10 minutes ago?`
5. **Settings → Forget screen history now** should report how many snapshots it deleted. Turning the feature off also deletes everything.

## Please send back

1. Anything that failed, with the exact message.
2. Apps: which apps or buttons worked, and which confused it?
3. Forms: right values? Anything filled that shouldn't have been?
4. Screen: was the text accurate? Did it slow the Mac down?

Known limits:
- Driving unfamiliar app windows with a small local model is hit-and-miss. Shortcuts are far more reliable; turn the things you do often into Shortcuts.
- Reading a big window (for example a long Mail list) can take several seconds.
- Screen context reads only the main display, and only while the Mac is awake and unlocked.

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
