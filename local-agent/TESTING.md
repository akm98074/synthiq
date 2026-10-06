# Testing Step 7d (v0.12.0): a face that talks

Upgrade with `UPGRADING.md`. This takes about 3 minutes, with the volume up.

### If something fails

| You see | Fix |
|---|---|
| No **Face** box under the chat | **Settings → Voice → Enable voice** must be on (macOS). |
| The face shows but there's no sound | Click anywhere on the page once (browsers need a click before playing audio), then try 🔊 again. |
| Sound plays but the mouth doesn't move | Tell me the browser and version. |

## Checks

1. Tick **Face**. A round face with your agent's name appears above the chat, blinking now and then.
2. Ask anything, then press **🔊** under the reply. You hear it, and the mouth opens and closes with the words.
3. Hold the mic and ask _"What's on my calendar today?"_. The answer is spoken by the face.
4. While it's talking, click the mic. It stops mid-sentence.
5. Switch macOS to Dark Mode. The face follows the theme.
6. Untick **Face**. Spoken replies go back to the Mac's own speaker.

## Please send back

1. Does the lip movement look natural enough?
2. Would you like a different face (style, colour, an image of your choice)?

Logs: `~/Library/Application Support/LocalAIAgent/server.log`
