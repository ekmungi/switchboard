# Switchboard — how to use it (the whole thing)

## 0. Clean translator (recommended) — `sb setup` once, then `sb code`

The current path runs a managed local translator (embedded LiteLLM) so Claude Code uses
the full OpenRouter catalog with nothing written to your global config.

```
sb setup                        # once: pinned engine + key + default profile + proxy + tool-use gate
sb code                         # launch claude on the default model via the local proxy
sb code z-ai/glm-4.6            # ...or choose a model for this session (switches the main tier)
sb stop                         # stop the local proxy daemon (waits for the port to free)
sb doctor                       # engine pin, proxy, cost-safety, nothing-global, tool-use gate
claude                          # plain claude = your Max subscription, untouched
```

- **Key:** `sb setup` reads `OPENROUTER_API_KEY` from `~/.env_claude`, or prompts once
  and appends it there. It never lands in `~/.claude/settings.json` and is never printed.
- **Reused daemon:** the proxy (loopback `127.0.0.1:4000` by default) starts once and is
  reused across `sb code` launches. Closing `claude` leaves the proxy running for the next
  launch; run `sb stop` to shut it down explicitly (it waits for the port to be released).
- **Model switch:** `sb code <model>` persists the new main tier, regenerates the proxy
  config, and restarts the proxy. `anthropic/*` and passthrough wildcards are refused
  (they'd leak metered Claude pricing).
- **Cached-login gotcha (R-007):** if Claude Code still uses Max instead of the proxy,
  run `/logout` inside it once — a cached login can override `ANTHROPIC_BASE_URL`.

Everything below (`ccr`, `sb use`, in-session `/model openrouter,...`) is the **legacy
CCR-driving path**, retained but **deprecated**.

---

## 1. (Legacy CCR) Start Claude Code on an open (OpenRouter) model
In a terminal (CCR v3: launch a profile by name or id; `ccr code` was v1/v2):
```
ccr default-claude-code
```
...or open the Claude Code profile from the CCR desktop app. Either way Claude
Code runs on the OpenRouter model pinned in the profile instead of Anthropic.

## 2. Switch models WHILE inside a session
Type this in the session (copy the MODEL from `sb list`):
```
/model openrouter,deepseek/deepseek-v4-flash
```
For web search, append `:online`:
```
/model openrouter,deepseek/deepseek-v4-flash:online
```

## 3. See or change models (in a normal terminal, NOT inside Claude)

```
sb list                              # show all companies (providers) + model counts
sb list deepseek                     # drill into one company's models (+ switch hints)
sb list qwen                         # ...or search by any keyword
sb use deepseek/deepseek-v4-flash    # pin this model (v3: launch profile; legacy: all roles)
sb current                           # show the live model/routing state and full health status
sb doctor                            # pass/fail health check; exits non-zero on failure
sb websearch on                      # legacy only; refused on v3 (would bill ALL traffic)
sb websearch off                     # strip the :online suffix (default state)
sb sync                              # audit: do CCR sessions see your MCP servers? (read-only)
sb sync --apply                      # mirror missing/changed user-scope MCP servers into the CCR scope
sb sync --prune                      # ...and also remove switchboard-added servers you deleted on the CC side
```

### Command details

Switchboard auto-detects the CCR generation: **v3** (config in SQLite at
`%APPDATA%/claude-code-router/config.sqlite`) or **legacy** (role-based
`~/.claude-code-router/config.json`). Same commands either way.

**`sb use <model>`** — GUARDED: the model must exist in the OpenRouter catalog and have
at least 64K context. If validation fails, the command exits 1 (no config writes) and
prints the nearest valid alternatives. On success (v3): the claude-code launch
profile's `model` AND `smallFastModel` are pinned in the SQLite store (no small/fast
leak), the model is added to the provider whitelist if missing (gateway reload only
then), and the change lands at the NEXT CCR-launched session — CCR re-applies the
profile at launch. On legacy: all CCR roles are pinned + CCR restarted. Both paths
keep the top-level APIKEY blank. A pre-write copy of the whole config is kept in the
store itself (`default.switchboard-bak` row) as a rollback safety net.

**`sb current`** — v3: store model, smallFastModel, the APPLIED `ANTHROPIC_MODEL`
from `~/.claude/settings.json` with an in-sync/DRIFT verdict, daemon/APIKEY/web-search
state, and a Router summary (builtins/rules/fallback). Legacy: the role table plus
effective model and WARNINGS.

**`sb doctor`** — structured pass/fail output for every health check. Exit code 0 =
all pass; exit code 1 = at least one failure. On v3 the suite covers: store readable,
profile enabled + model set, model/smallFastModel leak+catalog+context checks,
whitelist membership, applied-vs-store parity, APIKEY blank, MCP parity, and a
**legacy-hygiene** check that keeps failing while the inert old
`~/.claude-code-router/config.json` (+ `.bak` copies) still exist — rotate the
OpenRouter key they contain, then delete them.

**`sb websearch on|off`** — legacy: toggles the `:online` suffix on the webSearch CCR
role and restarts CCR. v3: `on` is REFUSED — v3 has no scoped webSearch role, so
`:online` would be billed on ALL traffic, not just web-search requests; `off` strips a
stray suffix if some other tool set one.

**`sb sync [--apply|--prune]`** — CCR launches its Claude Code sessions with
`CLAUDE_CONFIG_DIR=~/.claude`, so those sessions read their user-scope MCP servers from
`~/.claude/.claude.json` — NOT from `~/.claude.json` where yours are defined. Result:
MCP servers you add on the Claude side silently don't exist in CCR sessions. `sb sync`
audits every context surface (MCP by scope, plugins, CLAUDE.md, settings warnings) and,
with `--apply`, mirrors the missing/changed servers into the CCR scope using
`claude mcp add-json` (Claude's own writer — nothing is hand-edited, CCR internals are
never touched, and no CCR restart is needed). Servers appear in the NEXT CCR-launched
session. Run it from a plain session, a CCR session, or the terminal — identical result.
Whenever you add a new MCP server, plugin, or connector on the Claude side, just run
`/switchboard:sync --apply` (or `sb sync --apply`) once.

(If `sb` is not found, open a NEW terminal so the profile reloads, or use the full form:
`uv run --project "%USERPROFILE%\Dev\switchboard" python "%USERPROFILE%\Dev\switchboard\switchboard.py" list`.)
Note: switchboard is a uv project (`.venv` lives in the repo); `sb` runs it via `uv run`.

## 4. Go back to normal Claude (Anthropic)
Just run:
```
claude
```
Plain `claude` = Anthropic, untouched. `ccr code` = OpenRouter. Two separate worlds.

## Known limitation
- **Web search / reading web pages is unreliable on open models.** For web research,
  use normal `claude`. (Web search is an Anthropic-native feature and does not fully
  work through OpenRouter; appending `:online` to a model gives web-augmented answers
  but bills extra.)
