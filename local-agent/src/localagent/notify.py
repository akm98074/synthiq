"""Desktop notifications on Windows and Linux (macOS uses the AppleScript `notify` script).

Text is passed through environment variables, never pasted into a command, so a message
can't inject shell or PowerShell code.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys

WINDOWS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $t.GetElementsByTagName("text")
$texts.Item(0).AppendChild($t.CreateTextNode($env:LA_TITLE)) > $null
$texts.Item(1).AppendChild($t.CreateTextNode($env:LA_BODY)) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($t)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("LocalAIAgent").Show($n)
"""


def command(title: str, body: str) -> tuple[list[str], dict] | None:
    env = {**os.environ, "LA_TITLE": title[:120], "LA_BODY": body[:300]}
    if sys.platform == "win32":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        return ([ps, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_TOAST], env) if ps else None
    send = shutil.which("notify-send")
    return ([send, "--app-name=LocalAIAgent", "--", title[:120], body[:300]], env) if send else None


async def notify(title: str, subtitle: str, body: str) -> None:
    cmd = command(f"{title}: {subtitle}" if subtitle else title, body)
    if cmd is None:
        return
    proc = await asyncio.create_subprocess_exec(*cmd[0], env=cmd[1], stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()


def available() -> bool:
    return sys.platform == "darwin" or command("x", "y") is not None
