# Installing Switchboard

Switchboard is a thin **control panel** that drives [claude-code-router (CCR)](https://github.com/musistudio/claude-code-router) to point Claude Code at an OpenRouter model. It has two install surfaces:

- **Claude Code plugin** — the `/catalog` and `/switchboard` slash commands, used *inside* a Claude Code session.
- **Terminal `sb` command** — used in a normal terminal, *outside* Claude Code.

Neither surface ships the routing engine or your API key — those are per-machine prerequisites (a secret should never travel inside a distributed plugin).

---

## 1. Prerequisites (once per machine)

| Prerequisite | Why | Install |
|---|---|---|
| **Python 3.12+** | The CLI and the slash commands run on it. | https://python.org or `winget install Python.Python.3.12` |
| **claude-code-router** | The actual routing engine; switchboard only reads/writes its config and restarts it. | `npm install -g @musistudio/claude-code-router` (needs Node) |
| **OpenRouter API key** | CCR uses it to reach the models. Lives in `~/.claude-code-router/config.json`, never in git. | https://openrouter.ai/keys |
| **uv** (optional) | Provides the venv + `rich` for pretty terminal tables. The tool works without it (plain text). | https://docs.astral.sh/uv |

---

## 2. Install the Claude Code plugin (slash commands)

From inside a Claude Code session:

```
/plugin marketplace add ekmungi/switchboard
/plugin install switchboard@switchboard
```

- Installs `/catalog` and `/switchboard`, portable across machines — the commands call `python "${CLAUDE_PLUGIN_ROOT}/switchboard.py" ...`, so there are no hardcoded paths.
- A **private** repo installs through your existing `gh`/git authentication (no extra setup if `gh auth status` is logged in).
- To test before pushing changes, add a local path instead: `/plugin marketplace add ./path/to/switchboard`.

### The CCR-only `SessionStart` hook

The plugin ships one hook (`hooks/ccr_precheck.sh`) wired to `SessionStart`. A plugin hook fires in *every* session it is enabled in (Claude Code has no concept of CCR), so the hook **self-gates**:

1. It checks `ANTHROPIC_BASE_URL`. `ccr code` points Claude Code at the local loopback proxy (`http://127.0.0.1:<port>`); a normal session uses `https://api.anthropic.com`. If it is **not** a loopback address, the hook exits immediately with no output.
2. Under CCR, it runs `switchboard.py doctor` as a pre-flight. If everything is healthy (`exit 0`) it stays silent. Only when a check **fails** does it print the failing lines, which Claude Code injects into the session as context.

Net effect: **the hook is invisible in regular Claude Code sessions and in healthy CCR sessions; it only speaks up when a CCR session has a real problem** (CCR down, non-blank APIKEY, a sub-64K or Haiku role).

### Coexistence with user-level commands

If you previously had `~/.claude/commands/catalog.md` / `switchboard.md`, both they and the plugin's copies stay available (Claude Code does not auto-shadow commands). Delete the user-level files after installing the plugin to avoid duplicates.

---

## 3. Install the terminal `sb` command (bootstrap script)

Clone the repo and run the installer from it:

```bash
# Windows (PowerShell)
git clone https://github.com/ekmungi/switchboard
cd switchboard
.\install.ps1

# macOS / Linux
git clone https://github.com/ekmungi/switchboard
cd switchboard
./install.sh
```

The installer is **safe and idempotent**. It:

1. Checks Python / uv / ccr are present (warns with install hints if not).
2. Runs `uv sync` (if uv is present) to build the venv with `rich`.
3. Scaffolds `~/.claude-code-router/config.json` **only if it does not already exist** — with `APIKEY: ""`, `webSearch` without `:online`, all roles on a default ≥64K model, and `api_key: "PASTE_YOUR_OPENROUTER_KEY_HERE"`. It never overwrites an existing config and never writes a real secret.
4. Adds an `sb` function to your shell profile (PowerShell `$PROFILE` / `~/.bashrc` / `~/.zshrc`), keyed by a marker so re-runs don't duplicate it.

Then:

```bash
# 1. paste your OpenRouter key into ~/.claude-code-router/config.json (Providers[0].api_key)
# 2. open a NEW terminal (reloads the profile)
sb doctor          # should report all checks, or tell you what's missing
sb list deepseek   # browse the catalog
sb use deepseek/deepseek-v4-flash   # pin a model (guarded; restarts CCR)
```

---

## 4. Verify

- `sb doctor` → all `[PASS]` once CCR is running and your key is in place.
- `/switchboard doctor` inside a Claude Code session → same report.
- Start a CCR session (`ccr code`) → if anything is misconfigured, the pre-flight hook surfaces it at session start.

---

## 5. Uninstall

- **Plugin:** `/plugin uninstall switchboard@switchboard` then `/plugin marketplace remove switchboard`.
- **Terminal `sb`:** delete the `# switchboard:sb` block from your shell profile.
- **CCR config / key:** delete `~/.claude-code-router/config.json` (this removes your key too).
