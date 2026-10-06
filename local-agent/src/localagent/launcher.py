"""What LocalAIAgent.app runs (see macapp.py): start the agent in this process, or just open the
window if it is already running. `--no-open` starts it without opening a browser (login items)."""
from __future__ import annotations

import os
import sys
import threading
import webbrowser


def main() -> None:
    from .cli import _healthy, _pid_file, _signin_url, _url

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
