#!/usr/bin/env bash
# install.sh - bootstrap switchboard on a new macOS/Linux machine.
# Safe + idempotent: never overwrites an existing CCR config, never duplicates the
# sb function, never writes a secret. Run from the cloned repo: ./install.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
echo "== Switchboard installer =="
echo "repo: $REPO"
echo

have() { command -v "$1" >/dev/null 2>&1; }

# 1. Python 3.12+ (required)
if have python3; then echo "[ok]   $(python3 --version)"
elif have python; then echo "[ok]   $(python --version)"
else echo "[warn] Python not found. Install Python 3.12+ and re-run." ; fi

# 2. uv (recommended: venv + rich for pretty tables)
if have uv; then
  echo "[ok]   uv present - syncing project venv..."
  ( cd "$REPO" && uv sync >/dev/null )
else
  echo "[warn] uv not found (https://docs.astral.sh/uv). The tool still works on plain Python."
fi

# 3. Node + claude-code-router (the routing ENGINE)
if have ccr; then echo "[ok]   ccr (claude-code-router) present"
else echo "[warn] ccr not found. Install the engine:  npm install -g @musistudio/claude-code-router" ; fi

# 4. CCR config scaffold (only if absent - NEVER overwrite or inject a key)
CFG_DIR="$HOME/.claude-code-router"
CFG="$CFG_DIR/config.json"
if [ -f "$CFG" ]; then
  echo "[ok]   CCR config exists at $CFG - left untouched"
else
  mkdir -p "$CFG_DIR"
  cat > "$CFG" <<'JSON'
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
JSON
  echo "[new]  scaffolded $CFG"
  echo "       -> EDIT it and paste your OpenRouter key into Providers[0].api_key"
fi

# 5. sb terminal command (idempotent: keyed by a marker; appended to the shell rc)
RC="${HOME}/.bashrc"; [ -n "${ZSH_VERSION:-}" ] && RC="${HOME}/.zshrc"
case "${SHELL:-}" in */zsh) RC="${HOME}/.zshrc";; esac
MARKER="# switchboard:sb"
touch "$RC"
if grep -qF "$MARKER" "$RC"; then
  echo "[ok]   sb function already in $RC"
else
  {
    echo ""
    echo "$MARKER  (added by switchboard/install.sh)"
    echo "sb() { uv run --project \"$REPO\" python \"$REPO/switchboard.py\" \"\$@\"; }"
  } >> "$RC"
  echo "[new]  added 'sb' function to $RC"
fi

echo
echo "== Next steps =="
echo "1. Put your OpenRouter key in $CFG (Providers[0].api_key)."
echo "2. Open a NEW terminal (or 'source $RC'), then run:  sb doctor"
echo "3. For the Claude Code slash commands, install the plugin (see README 'Install as a Claude Code plugin')."
