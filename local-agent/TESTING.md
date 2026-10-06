# Testing Step 7e (v0.13.0): trusted agents

You need a second Mac with LocalAIAgent 0.13.0 (a friend's or your own), on the same Wi-Fi or both on Tailscale. Pair them with `UPGRADING.md` (2 minutes). This checklist takes about 10 minutes.

### If something fails

| You see | Fix |
|---|---|
| "Couldn't reach …'s agent" | Both Macs awake with the agent running and on the same network (or Tailscale). Check **Settings → Trusted agents** says "listening". |
| "not listening (restart the agent)" | `localagent stop` then `localagent start`. If the port is taken, change it and create a new invite. |
| "invite not valid" | Invites work once and for 7 days: create a new one. |
| macOS asks about incoming connections | Click **Allow**. |

## Checks (Mac A = you, Mac B = friend)

1. After pairing, both see each other under **Trusted agents** with the friend's name and address.
2. On B, without allowing anything on A: `Is <A's owner> free tomorrow afternoon?` shows an approval card, then "I've passed this on". On A, a nudge **"…'s agent asks"** appears; press **Reply**, type "after 3 works"; on B a nudge "…'s agent replied: after 3 works" appears.
3. On A tick **See when you're busy**. On B ask again: the answer lists busy **times** only, never event titles.
4. On B: `Leave <A>'s agent a message that I'm running 10 minutes late`. On A a nudge "Message from …'s agent" appears.
5. On A **Remove** B. On B try again: it's refused, and A's **Activity** shows `peer_rejected`.

## Please send back

1. Did pairing work on your network? (Same Wi-Fi or Tailscale?)
2. What else should a friend's agent be allowed to do on its own?

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
