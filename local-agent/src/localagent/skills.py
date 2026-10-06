"""Custom skills: folders you add that give the agent new abilities.

  <data folder>/skills/<name>/SKILL.md     front matter + instructions
  <data folder>/skills/<name>/...          any scripts the skill runs

SKILL.md starts with a small header:

    ---
    name: word-count
    description: Count the words in a piece of text.
    args: text                  # comma-separated string arguments (optional)
    run: python3 main.py        # optional; without it the skill is instructions only
    tier: read                  # read | draft | write | danger (default: write)
    network: false              # may the script use the network? (default: false)
    timeout: 30                 # seconds
    ---
    Anything below is shown to the agent as instructions.

A skill with `run` becomes a tool. Its arguments arrive as JSON on stdin, and whatever
it prints is the result. On macOS it runs under `sandbox-exec`:
  - no network unless `network: true`;
  - it can only write inside its own `work/` folder and temp folders;
  - it can't read Mail, Messages, Keychains, browser data, ~/.ssh or the agent's own data.
A skill that may use the network is always at least `write` tier (it could send data out).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .tools.base import TIERS, Tool, ToolError, ToolResult, obj, s

log = logging.getLogger(__name__)

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
MAX_OUTPUT = 20000
PRIVATE = ["Library/Mail", "Library/Messages", "Library/Keychains", "Library/Cookies", "Library/Safari",
           "Library/Group Containers", "Library/Application Support/AddressBook",
           "Library/Application Support/Google/Chrome", "Library/Application Support/LocalAIAgent",
           ".ssh", ".aws", ".gnupg", ".config/gh"]
LINUX_PRIVATE = [".local/share/LocalAIAgent", ".local/share/keyrings", ".config/google-chrome", ".config/chromium",
                 ".mozilla", ".thunderbird", ".password-store", ".docker", ".kube"]


@dataclass
class Skill:
    name: str
    folder: Path
    description: str
    body: str
    run: str = ""
    args: list[str] = field(default_factory=list)
    tier: str = "write"
    network: bool = False
    timeout: int = 30
    problems: list[str] = field(default_factory=list)

    @property
    def tool_name(self) -> str:
        return "skill_" + self.name.replace("-", "_")


def parse_skill(folder: Path) -> Skill:
    text = (folder / "SKILL.md").read_text(errors="replace").lstrip("\ufeff \t\n")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        head, sep, rest = text[3:].partition("\n---")
        if sep:
            body = rest.lstrip("-").lstrip("\n")
            for line in head.splitlines():
                line = line.split(" #", 1)[0].strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
    name = meta.get("name", folder.name).strip().lower()
    sk = Skill(name=name, folder=folder, description=meta.get("description", "").strip(), body=body.strip(),
               run=meta.get("run", "").strip(),
               args=[a.strip() for a in meta.get("args", "").split(",") if a.strip()],
               tier=meta.get("tier", "write").strip().lower(),
               network=meta.get("network", "false").lower() in ("true", "yes", "1"))
    try:
        sk.timeout = max(1, min(600, int(meta.get("timeout", "30"))))
    except ValueError:
        sk.problems.append("timeout must be a number of seconds")
    if not NAME_RX.match(sk.name):
        sk.problems.append("name must be lower-case letters, digits and dashes")
    if not sk.description:
        sk.problems.append("description is missing")
    if sk.tier not in TIERS:
        sk.problems.append(f"tier must be one of {', '.join(TIERS)}")
    if any(not re.match(r"^[a-z_][a-z0-9_]{0,30}$", a) for a in sk.args):
        sk.problems.append("args must be simple names like city, days")
    if sk.network and sk.tier in ("read", "draft"):
        sk.tier = "write"   # it could send your data somewhere
    return sk


def load_skills(root: Path) -> list[Skill]:
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists()):
        try:
            out.append(parse_skill(folder))
        except OSError as exc:
            log.warning("skill %s unreadable: %s", folder, exc)
    return out


def sandbox_profile(skill: Skill, home: Path) -> str:
    work = (skill.folder / "work").resolve()
    lines = ["(version 1)", "(allow default)"]
    if not skill.network:
        lines.append("(deny network*)")
    lines += ["(deny file-write*)",
              f'(allow file-write* (subpath "{work}") (subpath "/private/tmp") (subpath "/private/var/folders")'
              ' (literal "/dev/null") (literal "/dev/tty"))']
    lines += [f'(deny file-read* (subpath "{(home / p).resolve()}"))' for p in PRIVATE]
    # The skills folder sits inside the agent's (denied) data folder: re-allow this skill only.
    lines.append(f'(allow file-read* (subpath "{skill.folder.resolve()}"))')
    return "\n".join(lines)


def sandbox_available() -> bool:
    if sys.platform == "darwin":
        return shutil.which("sandbox-exec") is not None
    if sys.platform.startswith("linux"):
        return shutil.which("bwrap") is not None
    return False


def bwrap_command(skill: Skill, home: Path, cmd: list[str]) -> list[str]:
    """Linux: bubblewrap. Read-only root, private /tmp, private folders hidden (including the agent's
    own data), then only this skill's folder (read-only) and its work dir (writable) put back, and no
    network unless the skill declares it."""
    folder, work = skill.folder.resolve(), (skill.folder / "work").resolve()
    args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
            "--die-with-parent", "--new-session"]
    for p in PRIVATE + LINUX_PRIVATE:
        target = home / p
        if target.exists():
            args += ["--tmpfs", str(target.resolve())]
    # A private /tmp hides anything installed under /tmp (e.g. a virtualenv); put the interpreter back.
    for prefix in {Path(sys.prefix).resolve(), Path(cmd[0]).resolve().parent.parent}:
        if str(prefix).startswith("/tmp/") and prefix.exists():
            args += ["--ro-bind", str(prefix), str(prefix)]
    args += ["--ro-bind", str(folder), str(folder), "--bind", str(work), str(work)]
    if not skill.network:
        args.append("--unshare-net")
    return args + ["--chdir", str(folder), "--", *cmd]


async def run_skill(skill: Skill, args: dict, require_sandbox: bool = True) -> ToolResult:
    cmd = shlex.split(skill.run, posix=os.name != "nt")
    if not cmd:
        raise ToolError("This skill has nothing to run.")
    work = skill.folder / "work"
    work.mkdir(exist_ok=True)
    home = Path.home()
    if sandbox_available():
        if sys.platform == "darwin":
            cmd = ["sandbox-exec", "-p", sandbox_profile(skill, home), *cmd]
        else:
            cmd = bwrap_command(skill, home, cmd)
    elif require_sandbox:
        raise ToolError("Skills that run scripts need a sandbox: macOS's sandbox-exec, or bubblewrap on Linux "
                        "(sudo apt install bubblewrap). Not available on Windows yet.")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work), "TMPDIR": str(work),
           "LANG": os.environ.get("LANG", "en_US.UTF-8"), "SKILL_WORK_DIR": str(work),
           "PYTHONDONTWRITEBYTECODE": "1"}
    if sys.platform == "win32":             # Windows programs fail to start without these
        env.update({k: os.environ[k] for k in ("SYSTEMROOT", "SYSTEMDRIVE", "PATHEXT", "COMSPEC")
                    if k in os.environ})
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=skill.folder, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as exc:
        raise ToolError(f"Couldn't start the skill: {exc}") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(args).encode()), skill.timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise ToolError(f"The {skill.name} skill took longer than {skill.timeout}s.") from exc
    text = out.decode(errors="replace").strip()
    if proc.returncode != 0:
        raise ToolError(f"The {skill.name} skill failed: {(err.decode(errors='replace').strip() or text)[-500:]}")
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n…(output cut)"
    return ToolResult(text or "(no output)", f"Ran skill {skill.name}", None, untrusted=skill.network)


def skill_tools(root: Path, require_sandbox: bool = True) -> list[Tool]:
    tools = []
    for sk in load_skills(root):
        if sk.problems:
            log.warning("skill %s skipped: %s", sk.name, "; ".join(sk.problems))
            continue
        intents = ("task", "computer_action", "quick_answer", "schedule")
        desc = sk.description + (f" Instructions: {sk.body[:400]}" if sk.body and sk.run else "")
        if sk.run:
            params = obj({a: s(a.replace("_", " ")) for a in sk.args}, sk.args)
            tools.append(Tool(sk.tool_name, desc, params, sk.tier, "skills",
                              lambda a, sk=sk: run_skill(sk, a, require_sandbox),
                              lambda a, sk=sk: f"Run the {sk.name} skill"
                              + (f" with {', '.join(f'{k}={v!r}' for k, v in a.items())[:120]}" if a else ""),
                              intents,
                              egress=(lambda a, sk=sk: {"to": f"the internet (skill {sk.name})", "kind": "send",
                                                        "text": json.dumps(a), "what": "skill arguments"})
                              if sk.network else None))
        else:
            tools.append(Tool(sk.tool_name, sk.description + " (returns step-by-step instructions to follow)",
                              obj({}), "read", "skills",
                              lambda a, sk=sk: ToolResult(sk.body or "(empty)", f"Read the {sk.name} skill"),
                              lambda a, sk=sk: f"Read the {sk.name} skill", intents))
    return tools


def skill_status(root: Path) -> list[dict]:
    return [{"name": sk.name, "tool": sk.tool_name, "description": sk.description, "tier": sk.tier,
             "network": sk.network, "runs": bool(sk.run), "problems": sk.problems,
             "folder": str(sk.folder)} for sk in load_skills(root)]


EXAMPLE_SKILL = """---
name: {name}
description: Count the words, lines and characters in a piece of text.
args: text
run: python3 main.py
tier: read
network: false
timeout: 10
---
Use this when the user asks how long a text is.
"""

EXAMPLE_MAIN = '''import json
import sys

args = json.load(sys.stdin)
text = args.get("text", "")
print(f"{len(text.split())} words, {len(text.splitlines()) or 1} lines, {len(text)} characters")
'''


def scaffold(root: Path, name: str) -> Path:
    if not NAME_RX.match(name):
        raise ValueError("Use lower-case letters, digits and dashes, e.g. word-count")
    folder = root / name
    if folder.exists():
        raise FileExistsError(f"{folder} already exists")
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(EXAMPLE_SKILL.format(name=name))
    (folder / "main.py").write_text(EXAMPLE_MAIN)
    return folder
