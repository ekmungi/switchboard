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
| `sb use <model>` | GUARDED: pin all CCR roles (including background) to the given model and restart CCR. Refuses if the model is unknown or has fewer than 64K context tokens; prints the nearest valid alternatives. Sets `webSearch` without `:online` (no surprise billing). Keeps the top-level APIKEY blank. |
| `sb current` | Show the effective model, which CCR roles are set, whether CCR is running, APIKEY-blank state, web-search state, and any health WARNINGS. |
| `sb doctor` | Run a pass/fail health check suite; exits non-zero if any check fails. Checks CCR reachability, catalog access, APIKEY-blank, role consistency, and web-search state. |
| `sb websearch on\|off` | Toggle the `:online` suffix on the `webSearch` role and restart CCR. `on` = web-augmented answers (billed extra); `off` = plain model. |

### Slash commands

- `/catalog [keyword]` — browse the OpenRouter catalog from inside a Claude Code session (calls `sb list --md`).
- `/switchboard [subcommand]` — run any control-panel command from inside a session (`current`, `doctor`, `use <model>`, `websearch on|off`, `list [keyword]`).

## Architecture

Routing tool: **claude-code-router (CCR)**. Switchboard reads and writes
`~/.claude-code-router/config.json` and manages CCR lifecycle.

Source lives in `src/switchboard/` (catalog, ccr_config, guard, health, checks,
browse, render, cli modules) with a thin `switchboard.py` entry shim.
