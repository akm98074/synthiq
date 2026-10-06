"""What LocalAIAgent.app runs (see macapp.py): start the agent in this process, or just open the
window if it is already running. `--no-open` starts it without opening a browser (the applet
always passes it). A pending self-test request is answered without starting anything."""
from __future__ import annotations

import os
import sys
import threading
import webbrowser


def main() -> None:
    from .cli import _healthy, _pid_file, _signin_url, _url
    from .config import data_dir
    from .macapp import SELFTEST_OK, SELFTEST_REQUEST

    base = data_dir()
    if (base / SELFTEST_REQUEST).exists():
        # `localagent app install` checking that macOS will launch the app: answer and stop.
        (base / SELFTEST_REQUEST).unlink(missing_ok=True)
        (base / SELFTEST_OK).write_text("ok", encoding="utf-8")
        return
    show = "--no-open" not in sys.argv[1:]
    if _healthy(_url()):
        if show:
            webbrowser.open(_signin_url())
        return
    _pid_file().write_text(str(os.getpid()), encoding="utf-8")
    if show:
        threading.Timer(1.5, lambda: webbrowser.open(_signin_url())).start()
    from .server import main as serve

    sys.argv = [sys.argv[0]]
    serve()


if __name__ == "__main__":
    main()
