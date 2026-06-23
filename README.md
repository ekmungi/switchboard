# Switchboard

Connect the Claude Code harness to non-Anthropic open models via **OpenRouter**, and
switch between Anthropic and OpenRouter models (ideally mid-session).

## Objective

1. Prove an OpenRouter model can drive Claude Code; measure setup complexity.
2. Determine whether existing skills, slash commands, MCP servers, hooks, and
   subagents still work under a non-Claude model (the compatibility matrix).
3. Build an ergonomic model switch (in-session and / or per-session profiles).

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
