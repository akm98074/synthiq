# Testing Step 7b (v0.10.0): Gmail sign-in

Connect Gmail first with `UPGRADING.md` (about 5 minutes). This checklist takes about 10 minutes.

### If something fails

| You see | Fix |
|---|---|
| "That doesn't look like a Google OAuth client ID" | Copy the **Client ID** (it ends with `.apps.googleusercontent.com`), not the project ID. |
| Google: "Access blocked: … has not completed the Google verification process" | **Audience**: publish the app, or add your Gmail address under **Test users**. |
| Google: "redirect_uri_mismatch" | The client must be type **Desktop app**, not Web. |
| "Gmail error: Gmail API has not been used in project…" | Enable the **Gmail API** for that project (step 2). |
| "…revoked or expired. Connect Gmail again" | Press **Save and connect Gmail** again. If it happens weekly, publish the app (step 4). |

## Checks

1. **Connectors → Gmail → Test** should say "Found 1 Gmail message".
2. `What are my unread emails in Gmail?` lists real unread mail; click the chip to see them all.
3. `Read the latest email from <someone>` gives the full text.
4. `Which Gmail emails haven't I replied to this week?` should list threads where they wrote last, without newsletters.
5. `Draft a reply to <that email> saying thanks, I'll look tomorrow`. Check **Gmail → Drafts** (also on your phone): the draft is in the same thread.
6. `Send an email to <your other address> saying test from Ari` shows an approval card. Approve; the email arrives.
7. **Nudges → Run now** on the checks: Gmail threads waiting on you appear once each.
8. Open **Keychain Access**, search "LocalAIAgent": the items are there. Search the agent's `config.json` for your secret; it must not be there.
9. **Settings → Gmail → Disconnect**: the Gmail tools disappear from **Connectors**.

## Please send back

1. Where did the Google set-up confuse you? (I'll improve the steps.)
2. Were search results and follow-ups right?
3. Did the draft land in the right thread?

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
