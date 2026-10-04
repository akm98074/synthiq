#!/usr/bin/env bash
# LocalAIAgent installer for macOS (Apple Silicon).
# Usage: ./install.sh [path/to/localaiagent-*.whl]
set -euo pipefail

WHEEL="${1:-$(ls -t "$(dirname "$0")"/localaiagent-*.whl 2>/dev/null | head -1 || true)}"
say() { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
die() { printf "\033[1;31mError:\033[0m %s\n" "$*" >&2; exit 1; }

[ -n "$WHEEL" ] && [ -f "$WHEEL" ] || die "Wheel not found. Pass its path: ./install.sh localaiagent-0.1.0-py3-none-any.whl"
[ "$(uname -s)" = "Darwin" ] || echo "Note: this installer targets macOS; continuing anyway."

if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew is required: https://brew.sh (then re-run this script)"
fi

if ! command -v pipx >/dev/null 2>&1; then
  say "Installing pipx"
  brew install pipx
  pipx ensurepath >/dev/null || true
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v ollama >/dev/null 2>&1; then
  say "Installing Ollama"
  brew install ollama
fi

if ! curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  say "Starting Ollama in the background"
  (brew services start ollama >/dev/null 2>&1) || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
  done
fi

say "Installing LocalAIAgent from $WHEEL"
pipx install --force --python python3 "$WHEEL" || pipx install --force "$WHEEL"
export PATH="$HOME/.local/bin:$PATH"

say "Downloading local models (about 4 GB the first time)"
localagent setup

say "Checking everything"
localagent doctor || true

say "Done. Start it with:  localagent start"
