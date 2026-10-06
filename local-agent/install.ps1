# LocalAIAgent installer for Windows 10/11.
# Run it from PowerShell (not as Administrator), in the folder with the downloaded files:
#   powershell -ExecutionPolicy Bypass -File install.ps1 localaiagent-0.16.1-py3-none-any.whl
param([string]$Wheel = "")
$ErrorActionPreference = "Stop"

function Say($m)  { Write-Host "==> $m" -ForegroundColor Green }
function Warn($m) { Write-Host "Note: $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "Error: $m" -ForegroundColor Red; exit 1 }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Die "Please run this in a normal (not Administrator) PowerShell window, so the app installs for your user."
}

if (-not $Wheel) {
  $Wheel = Get-ChildItem -Path $PSScriptRoot, (Get-Location) -Filter "localaiagent-*.whl" -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Wheel -or -not (Test-Path $Wheel)) {
  Die "Can't find the localaiagent .whl file. Put install.ps1 and the .whl in the same folder and run:
       powershell -ExecutionPolicy Bypass -File install.ps1 localaiagent-0.16.1-py3-none-any.whl"
}
$Wheel = (Resolve-Path $Wheel).Path

if (-not (Have winget)) { Die "winget is required (App Installer from the Microsoft Store)." }

# Python 3.11+
$py = $null
foreach ($c in @("py", "python")) {
  if (Have $c) {
    $args3 = if ($c -eq "py") { @("-3", "-c") } else { @("-c") }
    & $c @args3 "import sys; sys.exit(sys.version_info < (3, 11))" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
  }
}
if (-not $py) {
  Say "Installing Python 3.12"
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  Refresh-Path
  $py = "py"
}
$pyArgs = if ($py -eq "py") { @("-3") } else { @() }

if (-not (Have pipx)) {
  Say "Installing pipx"
  & $py @pyArgs -m pip install --user --upgrade pipx
  & $py @pyArgs -m pipx ensurepath | Out-Null
  Refresh-Path
}
function Pipx { & $py @pyArgs -m pipx @args }

if (-not (Have ollama)) {
  Say "Installing Ollama"
  winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
  Refresh-Path
}

function Ollama-Up { try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null; $true } catch { $false } }
if (-not (Ollama-Up)) {
  Say "Starting Ollama in the background"
  Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "serve"
  for ($i = 0; $i -lt 30 -and -not (Ollama-Up); $i++) { Start-Sleep -Seconds 1 }
  if (-not (Ollama-Up)) { Die "Ollama didn't start. Open the Ollama app from the Start menu and re-run." }
}

# Upgrading: stop a running agent first. Your data (%LOCALAPPDATA%\LocalAIAgent) is kept.
if (Have localagent) {
  Say "Found an existing install; stopping it if running"
  try { localagent stop | Out-Null } catch { }
}

Say "Installing LocalAIAgent from $(Split-Path $Wheel -Leaf)"
Pipx install --force "$Wheel"
if ($LASTEXITCODE -ne 0) { Die "pipx install failed. Please send the output above." }

$binDir = (Pipx environment --value PIPX_BIN_DIR)
if (-not $binDir) { $binDir = Join-Path $HOME ".local\bin" }
$agent = Join-Path $binDir "localagent.exe"
if (-not (Test-Path $agent)) { Die "pipx finished but $agent is missing. Please send the output above." }

Say "Adding the cloud add-on (optional Claude escalation; unused until you add your own API key)"
Pipx inject localaiagent "anthropic>=1.10"; if ($LASTEXITCODE -ne 0) { Warn "cloud add-on failed; everything else still works." }

Say "Adding the browser add-on (web tasks in your own Chrome)"
Pipx inject localaiagent "playwright>=1.45"
if ($LASTEXITCODE -eq 0) {
  & $agent setup --no-pull --browser; if ($LASTEXITCODE -ne 0) { Warn "browser setup failed; run 'localagent setup --browser' later." }
} else { Warn "browser add-on failed to install; everything else still works." }

Say "Adding the voice add-ons (faster-whisper speech recognition, Windows speech output)"
Pipx inject localaiagent "faster-whisper>=1.0" "pyttsx3>=2.90"
if ($LASTEXITCODE -ne 0) { Warn "voice add-ons failed; text chat still works." }

Say "Downloading local models (about 4 GB the first time)"
& $agent setup

if ($env:LOCALAGENT_VOICE -ne "0") {
  Say "Downloading the speech models (skip with `$env:LOCALAGENT_VOICE='0')"
  & $agent setup --no-pull --voice; if ($LASTEXITCODE -ne 0) { Warn "speech model download failed; run 'localagent setup --voice' later." }
}

Say "Checking everything"
& $agent doctor

Write-Host ""
Say "Done. Open a new PowerShell window and start the agent with:  localagent start"
Write-Host "    (or right now:  & '$agent' start)"
