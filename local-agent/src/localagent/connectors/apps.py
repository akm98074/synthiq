"""Acting in Mac apps: open apps, read and press their buttons, type, and run Shortcuts.

Everything goes through AppleScript's System Events (Accessibility) and Shortcuts Events,
so it needs the Accessibility permission for Terminal. A small model is much better at
following a scripted Shortcut than at driving an unknown window, so the tools nudge it
toward Shortcuts first and keep raw UI pressing behind approvals:

  apps_list, app_ui_read, shortcuts_list     read
  app_open                                   draft
  app_ui_press, app_type_text, shortcuts_run write (approval; pressing Delete/Send/Buy… is danger)
"""
from __future__ import annotations

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s
from .applescript import parse_records
from .browser import COMMIT_WORDS

MAX_SCAN = 400
MAX_SHOW = 150
INTERESTING = {"AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXTextField",
               "AXTextArea", "AXSearchField", "AXComboBox", "AXLink", "AXTab", "AXTabGroup", "AXSlider",
               "AXCell", "AXRow", "AXMenuItem", "AXDisclosureTriangle", "AXIncrementor", "AXSegmentedControl"}
PRESSABLE = INTERESTING - {"AXTextField", "AXTextArea", "AXSearchField", "AXTabGroup", "AXSlider"}
BLOCKED_APPS = {"keychain access", "passwords", "1password", "1password 7", "bitwarden", "system settings",
                "system preferences", "terminal", "iterm2", "localaiagent"}


def apps_tools(runner) -> list[Tool]:
    state: dict[str, dict] = {}   # app → last UI snapshot

    def check_app(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ToolError("Say which app.")
        if name.lower() in BLOCKED_APPS:
            raise ToolError(f"The agent doesn't operate {name} (passwords, system settings and terminals are off "
                            "limits). Ask the user to do it.")
        return name

    def element(app: str, ref: int) -> dict:
        snap = state.get(app.lower())
        if snap is None:
            raise ToolError(f"Read the app's window first with app_ui_read (app={app}).")
        for e in snap["elements"]:
            if e["ref"] == ref:
                return e
        raise ToolError(f"No element [{ref}] in {app}; read the window again.")

    def label(e: dict) -> str:
        return e["name"] or e["description"] or e["value"][:40] or e["role"][2:]

    async def list_apps(a: dict) -> ToolResult:
        apps = [{"name": r[0], "frontmost": len(r) > 1 and r[1] == "true"}
                for r in parse_records(await runner.run("apps_list", []))]
        lines = [f"- {x['name']}{' (in front)' if x['frontmost'] else ''}" for x in apps]
        return ToolResult("Open apps:\n" + "\n".join(lines), f"{len(apps)} app(s) open", apps)

    async def open_app(a: dict) -> ToolResult:
        app = check_app(a["app"])
        await runner.run("app_activate", [app])
        return ToolResult(f"Opened {app}.", f"Opened {app}", {"app": app})

    async def read_ui(a: dict) -> ToolResult:
        app = check_app(a["app"])
        recs = parse_records(await runner.run("ui_snapshot", [app, str(MAX_SCAN)]))
        title = recs[0][0] if recs else ""
        els = []
        for r in recs[1:]:
            if len(r) < 5 or not r[0].isdigit():
                continue
            e = {"ref": int(r[0]), "role": r[1], "name": r[2], "description": r[3], "value": r[4][:200]}
            if e["role"] in INTERESTING or (e["role"] == "AXStaticText" and e["value"].strip()):
                els.append(e)
        els = els[:MAX_SHOW]
        state[app.lower()] = {"title": title, "elements": els}
        lines = []
        for e in els:
            if e["role"] == "AXStaticText":
                lines.append(f"    {e['value'][:120]}")
            else:
                val = f" = “{e['value'][:60]}”" if e["value"] and e["role"] not in ("AXButton",) else ""
                lines.append(f"[{e['ref']}] {e['role'][2:]} “{label(e)}”{val}")
        return ToolResult(f"{app} — window “{title}”:\n" + ("\n".join(lines) or "(nothing readable)"),
                          f"Read {app}", {"app": app, "title": title}, untrusted=True)

    async def press(a: dict) -> ToolResult:
        app = check_app(a["app"])
        e = element(app, a["ref"])
        if e["role"] not in PRESSABLE:
            raise ToolError(f"[{e['ref']}] is a {e['role'][2:]}, not something to press.")
        await runner.run("ui_press", [app, str(e["ref"]), e["role"], e["name"]])
        state.pop(app.lower(), None)   # the window has probably changed
        return ToolResult(f"Pressed “{label(e)}” in {app}. Read the window again to see the result.",
                          f"Pressed “{label(e)}” in {app}", {"app": app})

    def press_risk(a: dict) -> str:
        try:
            e = element(str(a.get("app", "")), int(a.get("ref")))
        except (ToolError, TypeError, ValueError):
            return "danger"
        return "danger" if COMMIT_WORDS.search(label(e)) else "write"

    async def type_text(a: dict) -> ToolResult:
        app = check_app(a["app"])
        await runner.run("ui_type", [app, a["text"]])
        return ToolResult(f"Typed the text into {app} where the cursor was.", f"Typed into {app}", {"app": app})

    async def list_shortcuts(a: dict) -> ToolResult:
        names = [r[0] for r in parse_records(await runner.run("shortcuts_list", [])) if r and r[0]]
        if not names:
            return ToolResult("No shortcuts found in the Shortcuts app.", "No shortcuts", [])
        return ToolResult("Shortcuts:\n" + "\n".join(f"- {n}" for n in names), f"{len(names)} shortcut(s)",
                          [{"name": n} for n in names])

    async def run_shortcut(a: dict) -> ToolResult:
        out = await runner.run("shortcuts_run", [a["name"], a.get("input", "")])
        return ToolResult(f"Ran the shortcut “{a['name']}”." + (f" Output:\n{out[:4000]}" if out else ""),
                          f"Ran shortcut {a['name']}", {"output": out[:4000]})

    def press_summary(a: dict) -> str:
        try:
            e = element(str(a.get("app", "")), int(a.get("ref")))
            return f"Press “{label(e)}” in {a.get('app')}"
        except (ToolError, TypeError, ValueError):
            return f"Press element [{a.get('ref')}] in {a.get('app')}"

    app_arg = s("App name as shown in the Dock, e.g. Notes, Safari, Spotify")
    intents = ("task", "computer_action")
    return [
        Tool("apps_list", "List the apps that are open and which one is in front.", obj({}),
             "read", "apps", list_apps, lambda a: "See which apps are open", (*intents, "quick_answer")),
        Tool("app_open", "Open an app or bring it to the front.", obj({"app": app_arg}, ["app"]),
             "draft", "apps", open_app, lambda a: f"Open {a.get('app', '')}", intents),
        Tool("app_ui_read", "Read the buttons, fields and text in an app's front window (numbered).",
             obj({"app": app_arg}, ["app"]), "read", "apps", read_ui,
             lambda a: f"Read {a.get('app', '')}'s window", intents),
        Tool("app_ui_press", "Press a button, tab, checkbox or menu item by its number from app_ui_read.",
             obj({"app": app_arg, "ref": i("Element number from app_ui_read")}, ["app", "ref"]),
             "write", "apps", press, press_summary, intents, risk=press_risk),
        Tool("app_type_text", "Type text into the app's focused field (where the cursor is).",
             obj({"app": app_arg, "text": s("Text to type")}, ["app", "text"]),
             "write", "apps", type_text, lambda a: f"Type “{a.get('text', '')[:60]}” into {a.get('app', '')}",
             intents),
        Tool("shortcuts_list", "List the user's Shortcuts (from the Shortcuts app). Prefer a Shortcut over "
             "pressing buttons when one fits.", obj({}), "read", "apps", list_shortcuts,
             lambda a: "List your Shortcuts", (*intents, "quick_answer")),
        Tool("shortcuts_run", "Run one of the user's Shortcuts by name, with optional text input.",
             obj({"name": s("Exact shortcut name from shortcuts_list"), "input": s("Optional input text")},
                 ["name"]),
             "write", "apps", run_shortcut, lambda a: f"Run the shortcut “{a.get('name', '')}”", intents),
    ]
