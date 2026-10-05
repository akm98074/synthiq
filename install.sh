#!/usr/bin/env bash
# LocalAIAgent installer for macOS (Apple Silicon).
#
# Run it WITHOUT sudo, from the folder containing the downloaded files:
#   bash install.sh localaiagent-0.1.1-py3-none-any.whl
set -euo pipefail

say()  { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33mNote:\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31mError:\033[0m %s\n" "$*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
  die "Please don't run this with sudo. Homebrew refuses to run as root, and the app
       must be installed for your own user. Run instead:
         bash install.sh <path-to-localaiagent-*.whl>"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
find_wheel() {
  ls -t "$SCRIPT_DIR"/localaiagent-*.whl "$PWD"/localaiagent-*.whl 2>/dev/null | head -1 || true
}
WHEEL="${1:-$(find_wheel)}"
[ -n "$WHEEL" ] && [ -f "$WHEEL" ] || die "Can't find the localaiagent .whl file.
       Put install.sh and the .whl in the same folder, cd into it, and run:
         bash install.sh localaiagent-0.1.1-py3-none-any.whl"
WHEEL="$(cd "$(dirname "$WHEEL")" && pwd)/$(basename "$WHEEL")"

[ "$(uname -s)" = "Darwin" ] || warn "this installer targets macOS; continuing anyway."
[ "$(uname -m)" = "arm64" ] || warn "this build is tuned for Apple Silicon (arm64); continuing anyway."

# Homebrew (it asks for your password itself when it needs admin rights).
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
  done
fi
command -v brew >/dev/null 2>&1 || die "Homebrew is required. Install it from https://brew.sh,
       open a new Terminal window, then run this script again."

if ! command -v pipx >/dev/null 2>&1; then
  say "Installing pipx"
  brew install pipx
fi
pipx ensurepath >/dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"

if ! command -v ollama >/dev/null 2>&1; then
  say "Installing Ollama"
  brew install ollama
fi

if ! curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  say "Starting Ollama in the background"
  brew services start ollama >/dev/null 2>&1 || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 \
    || die "Ollama didn't start. Open the Ollama app (or run 'ollama serve' in another window) and re-run."
fi

say "Installing LocalAIAgent from $(basename "$WHEEL")"
pipx install --force "$WHEEL"

say "Downloading local models (about 4 GB the first time)"
localagent setup

say "Checking everything"
localagent doctor || true

cat <<'EOF'

Done. Start the agent with:

    localagent start

If your shell says "localagent: command not found", open a new Terminal window
(pipx just added ~/.local/bin to your PATH) and try again.
EOF
