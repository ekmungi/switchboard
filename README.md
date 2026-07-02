# Switchboard

Connect the Claude Code harness to non-Anthropic open models via **OpenRouter**, and
switch between Anthropic and OpenRouter models (ideally mid-session).

## Objective

1. Prove an OpenRouter model can drive Claude Code; measure setup complexity.
2. Determine whether existing skills, slash commands, MCP servers, hooks, and
   subagents still work under a non-Claude model (the compatibility matrix).
3. Build an ergonomic model switch (in-session and / or per-session profiles).

## Install on a new machine

Switchboard has two install surfaces — Claude Code **slash commands** and the terminal **`sb`** command — both sitting on prerequisites you provide once per machine.

**Prerequisites (not shipped — switchboard only *drives* the engine, it isn't the engine):**
- **Python 3.12+** (the CLI and slash commands run on it).
- **claude-code-router** (the routing engine): `npm install -g @musistudio/claude-code-router`.
- An **OpenRouter API key** placed in `~/.claude-code-router/config.json` (kept out of git; the installer scaffolds that file with a placeholder for you to fill).
- Optional: **uv** (for pretty terminal tables via `rich`; the tool still works on plain Python).

### A. As a Claude Code plugin (the slash commands, fully portable)

From inside a Claude Code session:
```
/plugin marketplace add ekmungi/switchboard
/plugin install switchboard@switchboard
```
This installs `/catalog` and `/switchboard` on any machine. The plugin bundles the Python and resolves its own location via `${CLAUDE_PLUGIN_ROOT}` (no hardcoded paths). Its `SessionStart` hook runs a health pre-flight **only when the session is routed through CCR** (detected via `ANTHROPIC_BASE_URL` pointing at the local loopback proxy) and stays silent in a normal Anthropic session. A private repo installs through your existing `gh`/git auth.

> Already have user-level `~/.claude/commands/catalog.md` / `switchboard.md`? Remove them after installing the plugin so the commands don't appear twice.

### B. The terminal `sb` command (bootstrap script)

```
# Windows (PowerShell)
git clone https://github.com/ekmungi/switchboard; cd switchboard; .\install.ps1

# macOS / Linux
git clone https://github.com/ekmungi/switchboard && cd switchboard && ./install.sh
```
The installer checks prerequisites, runs `uv sync`, scaffolds the CCR config (key placeholder only — it never writes or overwrites a secret), and adds an `sb` function to your shell profile. It is **safe to re-run** (idempotent). Then paste your OpenRouter key into `~/.claude-code-router/config.json` and run `sb doctor`.

Full walkthrough, the CCR-only hook explained, and troubleshooting: see [INSTALL.md](INSTALL.md).

## Commands (control panel)

All commands run via the `sb` alias (or `uv run python switchboard.py`).

| Command | Description |
|---------|-------------|
| `sb list [keyword]` | Browse the OpenRouter catalog. No keyword: list all providers. With keyword: models matching that provider or term. The `/catalog` slash command runs this with `--md` for a markdown table. |
| `sb use <model>` | GUARDED: pin CCR to the given model. Refuses if the model is unknown or has fewer than 64K context tokens; prints the nearest valid alternatives. On CCR v3 it pins the claude-code launch profile's `model` + `smallFastModel` in the SQLite store (no small/fast leak; takes effect at the next CCR-launched session; whitelists the model for the gateway if needed). On legacy CCR it pins all roles and restarts CCR. Keeps the top-level APIKEY blank either way. |
| `sb current` | Show the live routing state. On v3: store model, smallFastModel, the APPLIED `ANTHROPIC_MODEL` from settings.json with an in-sync/DRIFT verdict, daemon/APIKEY/web-search state, and a Router summary. On legacy: the role table + effective model and health WARNINGS. |
| `sb doctor` | Run a pass/fail health check suite; exits non-zero if any check fails. On v3 adds: store readable, profile enabled, whitelist membership, applied-vs-store parity, and a legacy-hygiene check that FAILs while the inert old config.json/.bak files still exist (rotate the key, then delete them). |
| `sb websearch on\|off` | Web-search (`:online`) control. On v3, `on` is refused -- there is no scoped webSearch role anymore, so `:online` would bill ALL traffic; `off` strips a stray suffix. On legacy CCR it toggles the `webSearch` role and restarts CCR. |
| `sb sync [--apply\|--prune]` | Audit which Claude Code context surfaces route into CCR-launched sessions (MCP servers per scope, plugins, CLAUDE.md, settings warnings) and mirror user-scope MCP servers into CCR's `CLAUDE_CONFIG_DIR` scope. No flag = read-only report (exit 1 on drift). `--apply` mirrors drifted servers via `claude mcp add-json` (no CCR restart needed; servers appear in the next CCR session). `--prune` also removes servers switchboard previously added that are gone from the source. Secrets (env values, headers) are never printed. |

### Slash commands

- `/catalog [keyword]` — browse the OpenRouter catalog from inside a Claude Code session (calls `sb list --md`).
- `/switchboard [subcommand]` — run any control-panel command from inside a session (`current`, `doctor`, `use <model>`, `websearch on|off`, `list [keyword]`, `sync [--apply|--prune]`).
- `/switchboard:sync [--apply|--prune]` — the CC→CCR context audit + MCP mirror as its own command. Works identically from a plain Claude Code session and a CCR-launched session (the fix targets Claude's own config files, so where you run it from doesn't matter).

## Architecture

Routing tool: **claude-code-router (CCR)**. Switchboard auto-detects the CCR
config store: **v3** keeps everything in one SQLite blob
(`%APPDATA%/claude-code-router/config.sqlite`) and switchboard drives the
claude-code launch profile there (guarded targeted-merge writes with an
in-store backup row; the provider api key is round-tripped untouched and never
printed); **pre-v3** machines keep the original role-based
`~/.claude-code-router/config.json` handling and `ccr restart` lifecycle.

Source lives in `src/switchboard/` (catalog, ccr_config, ccr_store, ccr_v3,
ccr_lifecycle, guard, health, health_v3, checks, checks_v3, browse, render,
cli, cli_v3, claude_scopes, mcp_sync, sync_apply, sync_cmd modules) with a
thin `switchboard.py` entry shim.

**MCP-in-CCR note (CCR v3):** CCR launches claude sessions with
`CLAUDE_CONFIG_DIR=~/.claude`, which relocates the user-scope state file to
`~/.claude/.claude.json` — so user-scope MCP servers from `~/.claude.json` silently
vanish in CCR sessions. `sb sync` closes that gap by mirroring them via
`claude mcp add-json` (Claude's own writer; never hand-edits live state files, never
touches CCR internals). Also note: on CCR v3 the legacy
`~/.claude-code-router/config.json` is inert (config moved to SQLite) — the control
panel now drives the SQLite store directly, and `sb doctor` keeps failing its
legacy-hygiene check until the old file (and its `.bak` copies) are deleted after
rotating the key they contain.
