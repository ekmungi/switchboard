# install.ps1 - bootstrap switchboard on a new Windows machine.
# Safe + idempotent: never overwrites an existing CCR config, never duplicates the
# sb function, never writes a secret. Run from the cloned repo: .\install.ps1
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
Write-Host "== Switchboard installer ==" -ForegroundColor Cyan
Write-Host "repo: $Repo`n"

function Have($name) { $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }

# 1. Python 3.12+ (required: the CLI and the slash commands run on it)
if (Have python) {
    $pv = (python --version 2>&1)
    Write-Host "[ok]   $pv"
} else {
    Write-Warning "Python not found on PATH. Install Python 3.12+ (https://python.org) and re-run."
}

# 2. uv (recommended: provides the venv + rich for pretty terminal tables)
if (Have uv) {
    Write-Host "[ok]   uv present - syncing project venv..."
    Push-Location $Repo; uv sync | Out-Null; Pop-Location
} else {
    Write-Warning "uv not found. Install it (https://docs.astral.sh/uv) for pretty tables; the tool still works on plain Python."
}

# 3. Node + claude-code-router (the routing ENGINE - switchboard only drives it)
if (Have ccr) {
    Write-Host "[ok]   ccr (claude-code-router) present"
} else {
    Write-Warning "ccr not found. Install the engine:  npm install -g @musistudio/claude-code-router"
}

# 4. CCR config scaffold (only if absent - NEVER overwrite or inject a key)
$cfgDir = Join-Path $HOME ".claude-code-router"
$cfg    = Join-Path $cfgDir "config.json"
if (Test-Path $cfg) {
    Write-Host "[ok]   CCR config exists at $cfg - left untouched"
} else {
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    $template = @'
{
  "LOG": false,
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "",
  "API_TIMEOUT_MS": 600000,
  "Providers": [
    {
      "name": "openrouter",
      "api_base_url": "https://openrouter.ai/api/v1/chat/completions",
      "api_key": "PASTE_YOUR_OPENROUTER_KEY_HERE",
      "models": ["deepseek/deepseek-v4-flash"],
      "transformer": { "use": ["openrouter"] }
    }
  ],
  "Router": {
    "default": "openrouter,deepseek/deepseek-v4-flash",
    "background": "openrouter,deepseek/deepseek-v4-flash",
    "think": "openrouter,deepseek/deepseek-v4-flash",
    "longContext": "openrouter,deepseek/deepseek-v4-flash",
    "longContextThreshold": 200000,
    "webSearch": "openrouter,deepseek/deepseek-v4-flash",
    "image": ""
  }
}
'@
    Set-Content -Path $cfg -Value $template -Encoding utf8
    Write-Host "[new]  scaffolded $cfg" -ForegroundColor Yellow
    Write-Host "       -> EDIT it and paste your OpenRouter key into Providers[0].api_key" -ForegroundColor Yellow
}

# 5. sb terminal command (idempotent: only added once, keyed by a marker)
$marker = "# switchboard:sb"
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Force -Path $PROFILE | Out-Null }
if (Select-String -Path $PROFILE -Pattern ([regex]::Escape($marker)) -Quiet) {
    Write-Host "[ok]   sb function already in your PowerShell profile"
} else {
    $fn = @"

$marker  (added by switchboard/install.ps1)
function sb { uv run --project "$Repo" python "$Repo\switchboard.py" `@args }
"@
    Add-Content -Path $PROFILE -Value $fn
    Write-Host "[new]  added 'sb' function to $PROFILE" -ForegroundColor Yellow
}

Write-Host "`n== Next steps ==" -ForegroundColor Cyan
Write-Host "1. Put your OpenRouter key in $cfg (Providers[0].api_key)."
Write-Host "2. Open a NEW PowerShell window (reloads the profile), then run:  sb doctor"
Write-Host "3. For the Claude Code slash commands, install the plugin (see README 'Install as a Claude Code plugin')."
