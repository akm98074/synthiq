"""Who may talk to the local API.

The UI server listens on 127.0.0.1 only, but that alone doesn't stop:
- other programs on this computer calling it (any process can reach localhost), or
- a web page doing it through DNS rebinding (evil.example re-resolving to 127.0.0.1), or
- a web page sending simple cross-site POSTs.

So every request must
1. name this server in its Host header (127.0.0.1:<port> or localhost:<port>) - stops rebinding;
2. carry the per-install secret, as the session cookie the UI gets from /auth?t=… or as an
   `Authorization: Bearer` header (the CLI) - stops other programs and other users;
3. if it changes anything and the browser says where it came from (Origin), come from this app.

The secret lives in <data dir>/api-token, readable only by you.
"""
from __future__ import annotations

import hmac
import os
import secrets
import stat
import sys
from pathlib import Path

COOKIE = "la_session"
TOKEN_FILE = "api-token"
# The Gmail OAuth redirect arrives from Google (a cross-site navigation, so no SameSite cookie); it is
# protected by its own single-use state and PKCE verifier instead.
OPEN_PATHS = {"/api/health", "/auth", "/favicon.ico", "/api/gmail/callback"}


def private_file(path: Path) -> None:
    """Make a file readable only by its owner (POSIX; Windows relies on the per-user profile ACL)."""
    if sys.platform != "win32" and path.exists():
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def private_dir(path: Path) -> None:
    if sys.platform != "win32" and path.is_dir():
        os.chmod(path, stat.S_IRWXU)


PRIVATE_FILES = ("localagent.db", "localagent.db-wal", "localagent.db-shm", "server.log", "secrets.json",
                 TOKEN_FILE, "config.json", "about-me.md")


def lock_down(base: Path) -> None:
    """Only you can read the agent's data: the folder 0700, its files 0600 (POSIX). On Windows the
    folder lives in your own profile (LocalAppData), which other users can't read."""
    private_dir(base)
    for name in PRIVATE_FILES:
        private_file(base / name)
    for sub in ("browser-profile", "identity", "skills"):
        private_dir(base / sub)


def disk_encryption() -> tuple[bool | None, str]:
    """(on?, detail). None when it can't be told. Full-disk encryption protects the data if the
    computer is lost or stolen; the agent's files aren't encrypted separately."""
    import shutil
    import subprocess

    try:
        if sys.platform == "darwin" and shutil.which("fdesetup"):
            out = subprocess.run(["fdesetup", "status"], capture_output=True, text=True, timeout=5).stdout
            return ("On" in out), out.strip() or "unknown"
        if sys.platform == "win32" and shutil.which("manage-bde"):
            out = subprocess.run(["manage-bde", "-status", "C:"], capture_output=True, text=True, timeout=10).stdout
            on = "Protection On" in out
            return on, "BitLocker on" if on else "BitLocker off (or not readable without admin)"
        if sys.platform.startswith("linux") and shutil.which("lsblk"):
            out = subprocess.run(["lsblk", "-o", "TYPE"], capture_output=True, text=True, timeout=5).stdout
            on = "crypt" in out.split()
            return on, "an encrypted (LUKS) volume is present" if on else "no encrypted volume found"
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "couldn't tell"


def api_token(base: Path) -> str:
    """The per-install API secret, created on first use."""
    f = base / TOKEN_FILE
    try:
        tok = f.read_text().strip()
        if len(tok) >= 32:
            private_file(f)
            return tok
    except OSError:
        pass
    base.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(tok)
    private_file(f)
    return tok


def allowed_hosts(port: int, extra_host: str = "") -> set[str]:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    if extra_host and extra_host not in ("0.0.0.0", "::", "127.0.0.1", "localhost"):
        hosts.add(f"{extra_host}:{port}")      # the server was deliberately bound to that address
    return hosts


def same_secret(given: str | None, token: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), token.encode())


def bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def check(method: str, path: str, host: str | None, origin: str | None, cookie: str | None,
          authorization: str | None, port: int, token: str, extra_host: str = "") -> tuple[int, str] | None:
    """None if the request may proceed, else (status, reason)."""
    hosts = allowed_hosts(port, extra_host)
    if (host or "").lower() not in hosts:
        return 421, "This server only answers requests addressed to 127.0.0.1 or localhost."
    if method not in ("GET", "HEAD", "OPTIONS") and origin and origin.lower() not in {
            f"http://{h}" for h in hosts}:
        return 403, "Cross-site request refused."
    if path in OPEN_PATHS:
        return None
    if same_secret(cookie, token) or same_secret(bearer(authorization), token):
        return None
    return 401, "Not signed in. Open the app with: localagent open"
