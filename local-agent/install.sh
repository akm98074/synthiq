#!/usr/bin/env bash
# LocalAIAgent installer for macOS (Apple Silicon recommended) and Linux.
# Windows: use install.ps1 instead.
#
# Run it WITHOUT sudo, from the folder containing the downloaded files:
#   bash install.sh localaiagent-0.16.2-py3-none-any.whl
set -euo pipefail
ORIG_PATH="$PATH"  # the PATH of the Terminal window that ran this script

say()  { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33mNote:\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31mError:\033[0m %s\n" "$*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
  die "Please don't run this with sudo. The app must be installed for your own user
       (it asks for your password itself when it needs it). Run instead:
         bash install.sh <path-to-localaiagent-*.whl>"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
find_wheel() {
  ls -t "$SCRIPT_DIR"/localaiagent-*.whl "$PWD"/localaiagent-*.whl 2>/dev/null | head -1 || true
}
WHEEL="${1:-$(find_wheel)}"
[ -n "$WHEEL" ] && [ -f "$WHEEL" ] || die "Can't find the localaiagent .whl file.
       Put install.sh and the .whl in the same folder, cd into it, and run:
         bash install.sh localaiagent-0.16.2-py3-none-any.whl"
WHEEL="$(cd "$(dirname "$WHEEL")" && pwd)/$(basename "$WHEEL")"

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
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

else
  # Linux
  PY="$(command -v python3 || true)"
  [ -n "$PY" ] && "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || die "Python 3.11 or newer is required (e.g. sudo apt install python3.12)."
  if ! command -v pipx >/dev/null 2>&1; then
    say "Installing pipx"
    if command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y pipx
    elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y pipx
    else "$PY" -m pip install --user pipx; fi
  fi
  pipx ensurepath >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v ollama >/dev/null 2>&1; then
    say "Installing Ollama with its official installer (https://ollama.com/install.sh)"
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  command -v bwrap >/dev/null 2>&1 || warn "for custom skills that run scripts, install bubblewrap (sudo apt install bubblewrap)."
fi

if ! curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  say "Starting Ollama in the background"
  { [ "$OS" = "Darwin" ] && brew services start ollama >/dev/null 2>&1; } \
    || { command -v systemctl >/dev/null 2>&1 && systemctl --user start ollama >/dev/null 2>&1; } \
    || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 \
    || die "Ollama didn't start. Open the Ollama app (or run 'ollama serve' in another window) and re-run."
fi

# Upgrading: stop a running agent first so the new version starts cleanly.
# Your data (~/Library/Application Support/LocalAIAgent) is kept.
EXISTING="$(command -v localagent 2>/dev/null || true)"
[ -n "$EXISTING" ] || { [ -x "$HOME/.local/bin/localagent" ] && EXISTING="$HOME/.local/bin/localagent"; } || true
if [ -n "$EXISTING" ]; then
  say "Found an existing install ($("$EXISTING" version 2>/dev/null || echo unknown)); stopping it if running"
  "$EXISTING" stop >/dev/null 2>&1 || true
fi

say "Installing LocalAIAgent from $(basename "$WHEEL")"
pipx install --force "$WHEEL"

# pipx puts the command in its bin dir (usually ~/.local/bin), which is often not
# on PATH in the Terminal window that ran this script. Use the full path here and
# link it into Homebrew's bin dir, which is already on PATH everywhere.
BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || true)"
[ -n "$BIN_DIR" ] || BIN_DIR="$HOME/.local/bin"
AGENT="$BIN_DIR/localagent"
[ -x "$AGENT" ] || die "pipx finished but $AGENT is missing. Please send the output above."

if [ "$OS" = "Darwin" ]; then
  BREW_BIN="$(brew --prefix)/bin"
  LINK="$BREW_BIN/localagent"
  if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
    ln -sf "$AGENT" "$LINK" 2>/dev/null && say "Linked $LINK -> $AGENT" \
      || warn "couldn't link into $BREW_BIN; use the full path below."
  else
    warn "$LINK exists and isn't a link; leaving it alone."
  fi
fi

if [ "$OS" = "Darwin" ]; then
  say "Creating the LocalAIAgent app (so macOS gives permissions to it, not to Terminal)"
  "$AGENT" app install || warn "couldn't create the app; the agent still runs from Terminal."
fi

if [ "$(uname -s)" = "Darwin" ]; then
  say "Adding the calendar and screen add-ons (EventKit, on-device text recognition)"
  pipx inject localaiagent "pyobjc-framework-EventKit>=10" || warn "calendar add-on failed; Calendar falls back to AppleScript."
  pipx inject localaiagent "pyobjc-framework-Vision>=10" "pyobjc-framework-Quartz>=10" \
    || warn "screen add-on failed; everything except screen context still works."
fi

say "Adding the cloud add-on (optional Claude escalation; unused until you add your own API key)"
pipx inject localaiagent "anthropic>=1.10" || warn "cloud add-on failed; everything else still works."

say "Adding the browser add-on (web tasks in the agent's own browser window)"
if pipx inject localaiagent "playwright>=1.45"; then
  "$AGENT" setup --no-pull --browser || warn "browser setup failed; run 'localagent setup --browser' later."
else
  warn "browser add-on failed to install; everything else still works."
fi

if [ "$OS" = "Linux" ]; then
  say "Adding the voice add-ons (faster-whisper speech recognition, pyttsx3 speech)"
  pipx inject localaiagent "faster-whisper>=1.0" "pyttsx3>=2.90" \
    || warn "voice add-ons failed; text chat still works."
  command -v espeak-ng >/dev/null 2>&1 || command -v espeak >/dev/null 2>&1 \
    || warn "for spoken replies install eSpeak (sudo apt install espeak-ng)."
fi

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  say "Adding the voice add-on (on-device speech recognition)"
  pipx inject localaiagent "mlx-whisper>=0.4" || warn "voice add-on failed to install; text chat still works."
fi

say "Downloading local models (about 4 GB the first time)"
"$AGENT" setup

if [ "${LOCALAGENT_VOICE:-1}" != "0" ] && { [ "$(uname -m)" = "arm64" ] || [ "$OS" = "Linux" ]; }; then
  say "Downloading the speech models (up to 1.6 GB the first time; skip with LOCALAGENT_VOICE=0)"
  "$AGENT" setup --no-pull --voice || warn "speech model download failed; run 'localagent setup --voice' later."
fi

say "Checking everything"
"$AGENT" doctor || true

echo
if PATH="$ORIG_PATH" command -v localagent >/dev/null 2>&1; then
  say "Done. Start the agent with:  localagent start"
else
  say "Done. Start the agent with:  $AGENT start"
  echo "    To make plain 'localagent' work, run:  pipx ensurepath, then open a new terminal window"
fi
