# Testing Step 7f (v0.14.0): call your agent

Set it up with `UPGRADING.md` (about 15 minutes, needs a Twilio number and `cloudflared`). This checklist takes about 5 minutes.

### If something fails

| You hear / see | Fix |
|---|---|
| "We're sorry, an application error has occurred" | The tunnel isn't running, or the webhook URL is wrong. It must be `<tunnel address>/twilio/voice`, POST. |
| Settings status "Not listening" | `localagent stop` then `localagent start`. |
| Activity: "bad or missing Twilio signature" | The **Public URL** in Settings must be exactly the tunnel address (https, no trailing path), and the auth token must be the current one. |
| "This number is private" when you call | Add your mobile number with country code, as in `+14255550100`. |

## Checks

1. Call your Twilio number. You hear "Hi, it's Ari. What can I do for you?".
2. Say _"What's on my calendar tomorrow?"_. You hear "One moment", then the answer. It asks "Anything else?".
3. Say _"Draft an email to Sam saying I'll be late"_. It prepares the draft; check Mail's drafts.
4. Say _"Send an email to Sam saying hi"_. It should **not** send; it says to approve in the app.
5. Say _"Goodbye"_. It hangs up.
6. Call from another phone. You hear "this number is private".
7. **Activity** shows the call and the rejected one.

## Please send back

1. Time from finishing your question to the answer.
2. Was speech understood well?
3. What would you most want to do by phone?

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
