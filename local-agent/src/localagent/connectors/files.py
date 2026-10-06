"""Files connector: search, list, move, trash and open files inside allowed folders."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s

MAX_DEPTH = 4
MAX_VISITED = 20000
SKIP_DIRS = {"node_modules", "Library", "__pycache__"}


def parse_roots(spec: str) -> list[Path]:
    roots = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            p = Path(part).expanduser().resolve()
            if p.exists() and p.is_dir():
                roots.append(p)
    return roots


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# Opening these with the default app runs code (.command opens in Terminal, .exe/.bat run directly,
# .desktop launches its Exec line, .app/.pkg install or start programs, …).
EXECUTABLE_EXT = {
    ".app", ".command", ".tool", ".sh", ".bash", ".zsh", ".csh", ".fish", ".pkg", ".mpkg", ".dmg", ".scpt",
    ".applescript", ".workflow", ".terminal", ".webloc", ".inetloc", ".url", ".exe", ".bat", ".cmd", ".com",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".msi", ".msp", ".lnk", ".scr",
    ".cpl", ".reg", ".jar", ".py", ".pyw", ".pl", ".rb", ".php", ".desktop", ".appimage", ".run", ".bin",
    ".deb", ".rpm", ".snap", ".flatpakref", ".action", ".prefpane", ".kext", ".mobileconfig", ".shortcut",
}


def launches_code(p: Path) -> bool:
    if p.suffix.lower() in EXECUTABLE_EXT or any(s.lower() in (".app", ".pkg") for s in p.suffixes):
        return True
    if p.is_dir():
        return False
    return sys.platform != "win32" and os.access(p, os.X_OK)


class FileSpace:
    def __init__(self, roots: list[Path], trash_dir: Path | None = None):
        self.roots = roots
        self.trash_dir = trash_dir or (Path.home() / ".Trash" if sys.platform == "darwin"
                                       else Path.home() / ".local/share/Trash/files")

    def allowed(self, p: Path) -> bool:
        return any(p == r or r in p.parents for r in self.roots)

    def resolve(self, value: str, must_exist: bool = True) -> Path:
        raw = Path(value).expanduser()
        candidates = [raw] if raw.is_absolute() else (
            [r / raw for r in self.roots] + [Path.home() / raw])
        for c in candidates:
            c = c.resolve()
            if not self.allowed(c):
                continue
            if not must_exist or c.exists():
                return c
        roots = ", ".join(str(r) for r in self.roots) or "none configured"
        if must_exist:
            raise ToolError(f"'{value}' was not found inside the allowed folders ({roots}).")
        raise ToolError(f"'{value}' is outside the allowed folders ({roots}).")

    def describe(self, p: Path) -> dict:
        st = p.stat()
        return {"path": str(p), "name": p.name, "is_dir": p.is_dir(),
                "size": None if p.is_dir() else st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")}

    def search(self, query: str, folder: str | None, extension: str | None, limit: int) -> list[dict]:
        bases = [self.resolve(folder)] if folder else self.roots
        q = query.lower().strip()
        ext = (extension or "").lower().lstrip(".")
        hits: list[Path] = []
        visited = 0
        for base in bases:
            base_depth = len(base.parts)
            for dirpath, dirnames, filenames in os.walk(base):
                visited += 1
                if visited > MAX_VISITED:
                    break
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                               and not d.endswith(".app")]
                if len(Path(dirpath).parts) - base_depth >= MAX_DEPTH:
                    dirnames[:] = []
                for name in filenames + dirnames:
                    if name.startswith("."):
                        continue
                    low = name.lower()
                    if q and q not in low:
                        continue
                    if ext and not low.endswith("." + ext):
                        continue
                    hits.append(Path(dirpath) / name)
        hits.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return [self.describe(p) for p in hits[:limit]]

    def listing(self, folder: str, limit: int) -> list[dict]:
        base = self.resolve(folder)
        if not base.is_dir():
            raise ToolError(f"'{folder}' is not a folder.")
        items = [p for p in base.iterdir() if not p.name.startswith(".")]
        items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [self.describe(p) for p in items[:limit]]

    def move(self, paths: list[str], destination: str) -> list[dict]:
        dest = self.resolve(destination, must_exist=False)
        dest.mkdir(parents=True, exist_ok=True)
        moved = []
        for value in paths:
            src = self.resolve(value)
            target = dest / src.name
            if target.exists():
                target = dest / f"{src.stem} ({int(time.time())}){src.suffix}"
            shutil.move(str(src), str(target))
            moved.append({"from": str(src), "to": str(target)})
        return moved

    def trash(self, paths: list[str]) -> list[dict]:
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for value in paths:
            src = self.resolve(value)
            if src in self.roots:
                raise ToolError("Refusing to trash a whole allowed folder.")
            target = self.trash_dir / src.name
            if target.exists():
                target = self.trash_dir / f"{src.stem} {int(time.time())}{src.suffix}"
            shutil.move(str(src), str(target))
            out.append({"from": str(src), "trash": str(target)})
        return out


def _paths_arg(a: dict) -> list[str]:
    paths = a.get("paths") or []
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        raise ToolError("Give at least one path.")
    return paths


def file_tools(space: FileSpace) -> list[Tool]:
    def fmt(items: list[dict]) -> str:
        return "\n".join(
            f"- {it['path']}" + ("/" if it["is_dir"] else f" ({_human_size(it['size'])})")
            + f", modified {it['modified'].replace('T', ' ')}" for it in items)

    def search(a: dict) -> ToolResult:
        items = space.search(a.get("query", ""), a.get("folder"), a.get("extension"), int(a.get("limit", 20)))
        if not items:
            return ToolResult("No matching files.", "No matching files", [])
        return ToolResult("Matching files (newest first):\n" + fmt(items), f"Found {len(items)} file(s)", items,
                          untrusted=True)   # file names come from downloads, senders, …

    def listing(a: dict) -> ToolResult:
        items = space.listing(a["folder"], int(a.get("limit", 50)))
        if not items:
            return ToolResult("The folder is empty.", "Empty folder", [])
        return ToolResult(f"Contents of {a['folder']} (newest first):\n" + fmt(items),
                          f"{len(items)} item(s) in {a['folder']}", items, untrusted=True)

    def move(a: dict) -> ToolResult:
        moved = space.move(_paths_arg(a), a["destination"])
        return ToolResult("Moved:\n" + "\n".join(f"- {m['from']} -> {m['to']}" for m in moved),
                          f"Moved {len(moved)} item(s)", moved)

    def trash(a: dict) -> ToolResult:
        out = space.trash(_paths_arg(a))
        return ToolResult("Moved to Trash:\n" + "\n".join(f"- {m['from']}" for m in out),
                          f"Moved {len(out)} item(s) to Trash", out)

    def open_file(a: dict) -> ToolResult:
        p = space.resolve(a["path"])
        if launches_code(p):
            raise ToolError(f"{p.name} is a program or script, and opening it would run it. For your safety "
                            "the agent never opens those; open it yourself in Finder/Explorer if you trust it.")
        cmd = ["open", str(p)] if sys.platform == "darwin" else ["xdg-open", str(p)]
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]  # noqa: S606 - opens with the default app
            else:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (FileNotFoundError, OSError) as exc:
            raise ToolError("No program available to open files.") from exc
        return ToolResult(f"Opened {p}.", f"Opened {p.name}", {"path": str(p)})

    paths = {"type": "array", "items": {"type": "string"}, "description": "File or folder paths"}
    return [
        Tool("files_search", "Find files or folders by name inside the user's allowed folders (Downloads, Desktop, Documents).",
             obj({"query": s("Part of the file name (case-insensitive)"),
                  "folder": s("Limit to this folder, e.g. 'Downloads' (optional)"),
                  "extension": s("Only this extension, e.g. pdf (optional)"),
                  "limit": i("Max results (default 20)")}),
             "read", "files", search, lambda a: f"Search files for “{a.get('query', '')}”",
             ("computer_action", "task", "quick_answer")),
        Tool("files_list", "List the newest items in a folder.",
             obj({"folder": s("Folder, e.g. 'Downloads' or a full path"), "limit": i("Max items (default 50)")},
                 ["folder"]),
             "read", "files", listing, lambda a: f"List {a.get('folder', '')}", ("computer_action", "task")),
        Tool("files_move", "Move files/folders into a destination folder (created if missing).",
             obj({"paths": paths, "destination": s("Destination folder, e.g. 'Documents/Archive'")},
                 ["paths", "destination"]),
             "write", "files", move,
             lambda a: f"Move {len(_paths_arg(a)) if a.get('paths') else '?'} item(s) to {a.get('destination', '')}",
             ("computer_action",)),
        Tool("files_trash", "Move files/folders to the Trash.",
             obj({"paths": paths}, ["paths"]), "danger", "files", trash,
             lambda a: "Move to Trash: " + ", ".join(Path(p).name for p in (a.get("paths") or [])[:5]),
             ("computer_action",)),
        Tool("files_open", "Open a file with its default app.",
             obj({"path": s("File path")}, ["path"]), "draft", "files", open_file,
             lambda a: f"Open {a.get('path', '')}", ("computer_action",)),
    ]
