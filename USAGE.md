# Switchboard — how to use it (the whole thing)

## 1. Start Claude Code on an open (OpenRouter) model
In a terminal:
```
ccr code
```
This launches Claude Code running on an OpenRouter model instead of Anthropic.

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
sb use deepseek/deepseek-v4-flash    # set this model as default + restart CCR
sb current                           # show the current model and full health status
sb doctor                            # pass/fail health check; exits non-zero on failure
sb websearch on                      # enable web-augmented answers (appends :online, billed extra)
sb websearch off                     # disable :online suffix (default)
sb sync                              # audit: do CCR sessions see your MCP servers? (read-only)
sb sync --apply                      # mirror missing/changed user-scope MCP servers into the CCR scope
sb sync --prune                      # ...and also remove switchboard-added servers you deleted on the CC side
```

### Command details

**`sb use <model>`** — GUARDED: the model must exist in the OpenRouter catalog and have
at least 64K context. If validation fails, the command exits 1 (no config writes, no
CCR restart) and prints the nearest valid alternatives. On success: all CCR roles
(default, background, think, longContext, webSearch) are pinned to the model;
webSearch is set WITHOUT `:online`; the top-level APIKEY is kept blank.

**`sb current`** — prints the CCR routing table plus: effective model, CCR-running
state, APIKEY-blank state, web-search state, and any WARNINGS (e.g. role mismatch,
model below 64K, stale catalog).

**`sb doctor`** — structured pass/fail output for every health check. Exit code 0 =
all pass; exit code 1 = at least one failure. Use in scripts or CI to gate on health.

**`sb websearch on|off`** — toggles the `:online` suffix on the webSearch CCR role and
restarts CCR. Turning it on enables web-augmented answers but incurs extra billing from
OpenRouter. The `sb use` command always resets this to `off`.

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
