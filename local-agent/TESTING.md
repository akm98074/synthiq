# Testing Step 7c (v0.11.0): optional cloud model

Set it up with `UPGRADING.md` (2 minutes; needs an Anthropic API key). This checklist takes about 5 minutes and costs a few cents.

### If something fails

| You see | Fix |
|---|---|
| "The cloud add-on isn't installed" | `pipx inject localaiagent anthropic`, then restart. |
| "That doesn't look like an Anthropic API key" | Copy the whole key; it starts with `sk-ant-`. |
| "Anthropic rejected the API key" | Make a new key in the Anthropic console and save it again. |
| No approval card, just a normal answer | **Settings → Cloud model → Allow asking the cloud model** must be ticked and saved, and the message must start with "think harder", "use the cloud" or "ask Claude". |

## Checks

1. `What's 17 × 23?` should get a normal local answer, no card.
2. `Think harder: explain the difference between a Roth and a traditional IRA for someone in their 30s`
   - Expected: an approval card, "Send to claude-opus-5-5 (Anthropic, cloud): …", that lists what goes along. Press **Decline**: "nothing was sent".
3. Ask again and press **Approve → Just this once**. The answer streams in; the chips show "Answered by claude-opus-5-5 (cloud)".
4. Approve one with **For 1 hour**, then ask another "think harder" question. It goes without a card.
5. **Activity** shows each cloud request (what was asked, approved, answered). The API key isn't anywhere in it.
6. Untick **Allow asking the cloud model**: "think harder" questions are answered locally again.

## Please send back

1. Was it clear what would be sent?
2. Were the cloud answers worth it compared with the local ones?
3. Should it offer the cloud on its own for hard questions?

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
