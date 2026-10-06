# Testing Step 7a (v0.9.0): "Hey Ari" wake word

Upgrade with `UPGRADING.md`. This takes about 5 minutes. Use the Mac's microphone or AirPods, in a fairly quiet room.

### If something fails

| You see | Fix |
|---|---|
| No **Hey Ari** box under the chat | **Settings → Voice → Enable voice** must be on, and the voice add-on installed. |
| "Microphone blocked" | Allow the microphone for `127.0.0.1:8765` in the browser's site settings (lock icon in the address bar). |
| It never wakes | Say it clearly, then pause briefly. Check `localagent setup --no-pull --voice` downloaded the wake-word model. |
| It wakes by itself | Tell me what was being said. You can add or change phrases in Settings. |

## Checks

1. Tick **Hey Ari**. The status shows _Listening for “Hey Ari”_.
2. Say **"Hey Ari"** and wait for the chime, then: _"what's on my calendar today?"_. The question appears in the chat and the answer is spoken.
3. In one breath: **"Hey Ari, what's the weather in Seattle?"**. It answers without a second step.
4. Talk normally for a minute (or play a podcast). It should **not** wake. Also try "Hey Siri": it shouldn't wake either.
5. Switch to another tab or app and say "Hey Ari, what time is it?". It should still answer, as long as the app's tab stays open.
6. Untick **Hey Ari**. The microphone indicator in the browser tab goes away.

## Please send back

1. How often did it miss "Hey Ari", and how often did it wake by mistake?
2. Time from the end of your sentence to the chime.
3. Any CPU or fan noise while listening?

Known limits:
- The app's page must be open in a browser tab (no background service yet).
- Loud music or TV can cause misses.

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
