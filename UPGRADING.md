# Upgrading LocalAIAgent

Upgrading keeps everything you've built up: memories, conversation history, decision corrections and settings. They live in `~/Library/Application Support/LocalAIAgent/`, which the installer never touches.

## From 0.1.x to 0.2.0 (Step 2: connectors and approvals)

1. Put the new files in one folder (for example `~/Downloads/LocalAIAgent-0.2.0/`):
   `localaiagent-0.2.0-py3-none-any.whl`, `install.sh`, `TESTING.md`, `UPGRADING.md`.
2. Open Terminal in that folder and run, **without `sudo`**:

   ```bash
   cd ~/Downloads/LocalAIAgent-0.2.0
   bash install.sh localaiagent-0.2.0-py3-none-any.whl
   ```

   The installer stops the running agent, replaces the program, checks the models (already downloaded, so this is quick), and runs `localagent doctor`.
3. Start it again:

   ```bash
   localagent start
   localagent version      # should print 0.2.0
   ```

   If `localagent` isn't found, use `~/.local/bin/localagent start` and see the troubleshooting table in `TESTING.md`.
4. In the browser, open **Connectors** and press **Test** on Calendar, Reminders, Notes, Mail and Contacts. Each one shows a macOS prompt (_"Terminal wants access to control Calendar"_); click **Allow**. You only do this once per app.

Your new database tables (approvals, permissions, activity log) are created automatically on first start.

### Manual upgrade (if you'd rather not use the script)

```bash
localagent stop
pipx install --force ./localaiagent-0.2.0-py3-none-any.whl
localagent start
```

### Going back to 0.1.x

```bash
localagent stop
pipx install --force ./localaiagent-0.1.2-py3-none-any.whl
localagent start
```

0.1.x ignores the new tables, so your memories and history keep working.

## What changed in 0.2.0

- **Connectors**: Calendar, Reminders, Notes, Mail, Contacts (through the Apple apps, so any Google, iCloud or Exchange account you've added to them works), Files (Downloads, Desktop, Documents) and Documents (PDF and Excel).
- **Approvals**: every action has a risk tier:
  - **read** runs on its own.
  - **draft** runs on its own and is logged.
  - **write** asks first; you can approve once, for this request, until restart, for 1 hour or 24 hours, or always.
  - **danger** (for example moving files to the Trash) asks every time.
- **Activity**: a hash-chained audit log of everything the agent did, asked for, or was refused. It flags any edit made outside the app.
- **Installer**: refuses `sudo`, finds the wheel by itself, puts `localagent` on your PATH, and stops a running agent before upgrading.
