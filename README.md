# Switchboard

Run the Claude Code CLI on **any OpenRouter model** through a **managed local
translator** — one-command setup, nothing written to your global config, and plain
`claude` (Max) left untouched.

## Quick start (clean translator — recommended)

Switchboard runs its own local Anthropic→OpenAI translator (embedded LiteLLM, pinned)
so Claude Code can talk to the full OpenRouter catalog. Nothing global is touched: the
proxy binds loopback only, the key stays in `~/.env_claude`, and `sb code` sets the
redirect only in the child `claude` process.

```
sb setup                       # once: pinned engine + key + default profile + proxy + tool-use gate
sb code                        # launch claude on the default OpenRouter model via the local proxy
sb code deepseek/deepseek-chat # ...or pick a model for this session (switches the main tier)
sb doctor                      # health: engine pin, proxy, cost-safety, nothing-global, tool-use gate
claude                         # plain claude = your Max subscription, untouched
```

`sb setup` prompts once for an OpenRouter key (or reads it from `~/.env_claude`),
installs the pinned engine into a switchboard-owned venv (no toolchain step), and ends
either "ready" or with a clear failure. Requires **uv** and **Python 3.12+**.

**Cost-safety:** every tier (including background/subagent calls) maps to an explicit
cheap OpenRouter model with a concrete cheap catch-all — never a passthrough, never a
Claude-priced `anthropic/*` model — so a long multi-agent session can't silently leak
metered Claude pricing. `sb doctor` asserts this.

> The older **CCR-driving** path (`sb use` / `current` / `websearch`, below) is
> **deprecated** but still works while the clean translator is proven on-device.

## Objective (project background)

1. Prove an OpenRouter model can drive Claude Code; measure setup complexity.
2. Determine whether existing skills, slash commands, MCP servers, hooks, and
   subagents still work under a non-Claude model (the compatibility matrix).
3. Build an ergonomic model switch (in-session and / or per-session profiles).

## Install on a new machine

Switchboard has two install surfaces — Claude Code **slash commands** and the terminal **`sb`** command — both sitting on prerequisites you provide once per machine.

**For the clean translator (recommended):**
- **Python 3.12+** and **uv** (`sb setup` installs the pinned engine into its own venv).
- An **OpenRouter API key** in `~/.env_claude` as `OPENROUTER_API_KEY=...` (or let `sb setup` prompt once and write it). Then just run `sb setup`.

**For the legacy CCR-driving path only (deprecated):**
- **claude-code-router** (the routing engine): `npm install -g @musistudio/claude-code-router`.
- An **OpenRouter API key** placed in `~/.claude-code-router/config.json` (kept out of git; the installer scaffolds that file with a placeholder for you to fill).

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

**Clean translator (recommended):**

| Command | Description |
|---------|-------------|
| `sb setup` | One-command, idempotent: installs the pinned engine into a switchboard-owned venv, resolves the OpenRouter key (prompt once → `~/.env_claude`), generates a default profile, starts the local proxy, and runs the tool-use gate. Ends "ready" or a clear failure. |
| `sb code [<model>]` | Ensure the proxy is up (daemon reused) and launch `claude` against it via a per-session env — nothing written to `settings.json`. Optional model switches the main tier (refuses `anthropic/*` / passthrough). |
| `sb doctor` | With the translator set up: engine-pin, proxy health, cost-safety (no `anthropic/*`, no passthrough), nothing-global (`settings.json` clean), a real tool-use round-trip, and a spend-cap advisory. |

**Legacy (CCR-driving, deprecated):**

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

**Clean translator (primary).** Switchboard runs a **managed local
Anthropic→OpenAI translator** — embedded **LiteLLM, pinned `litellm==1.81.14`**
(engine chosen and locked by a Windows viability + tool-use spike, R-008) — in a
switchboard-owned uv venv under `~/.switchboard`. The proxy binds `127.0.0.1` only.
`sb code` points Claude Code at it via a **per-session** `ANTHROPIC_BASE_URL` (the
child process env only — `settings.json` is never touched), so plain `claude` keeps
using your Max subscription. The generated proxy config maps every tier to an explicit
cheap OpenRouter model with a concrete cheap catch-all (cost-safe by construction). On
Windows the engine is spawned with `PYTHONUTF8=1` (its startup banner crashes under
cp1252 when its output is redirected).

Translator modules (`src/switchboard/`): `translator_engine` (engine interface +
LiteLLM adapter), `translator_lifecycle` (proxy daemon on loopback + reuse),
`cost_safety` (the shared R3a/R5a guard), `profiles`, `keystore`, `setup`, `launch`,
`verify` (tool-use gate), `translator_checks` (doctor), `paths`.

**Legacy CCR-driving (deprecated).** The earlier path drives **claude-code-router
(CCR)**: switchboard auto-detects the CCR config store — **v3** (SQLite blob at
`%APPDATA%/claude-code-router/config.sqlite`, guarded targeted-merge writes with an
in-store backup; provider api key round-tripped untouched, never printed) or **pre-v3**
(role-based `~/.claude-code-router/config.json` + `ccr restart`). Modules: catalog,
ccr_config, ccr_store, ccr_v3, ccr_lifecycle, guard, health, health_v3, checks,
checks_v3, browse, render, cli, cli_v3, claude_scopes, mcp_sync, sync_apply, sync_cmd —
with a thin `switchboard.py` entry shim. This path is retained but will be removed once
the clean translator is proven on-device.

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
