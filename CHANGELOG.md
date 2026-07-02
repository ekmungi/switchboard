# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] - 2026-07-02

### P-004: v3-compatible control panel (SPEC-004)

#### Added

- **CCR store auto-detection** (`detect_store()`): when the CCR v3 SQLite store
  (`%APPDATA%/claude-code-router/config.sqlite`) exists, `sb use` / `current` /
  `doctor` / `websearch` drive it; pre-v3 machines keep the legacy role-based
  `~/.claude-code-router/config.json` behavior unchanged.
- New modules: `ccr_store.py` (guarded SQLite read/write: read-only URI loads,
  whole-blob targeted-merge writes under `BEGIN IMMEDIATE`, in-store backup row
  `default.switchboard-bak`, refreshed `updated_at`), `ccr_v3.py` (pure blob
  accessors/updaters over the claude-code launch profile + provider whitelist),
  `ccr_lifecycle.py` (daemon probe, `reload_gateway()` = `ccr stop`+`ccr start`
  for CLI-managed daemons / app-restart instruction for Electron-owned ones),
  `checks_v3.py` + `health_v3.py` (v3 doctor checks and status/warning lines).
- `sb use` on v3 pins the claude-code profile's `model` AND `smallFastModel`
  (no small/fast leak), ensures the provider-whitelist entry (gateway reload
  only when it changed), keeps APIKEY blank, and states that the change lands
  at the NEXT CCR-launched session (CCR re-applies the profile at launch).
  Prints a clobber advisory while the CCR app/daemon is running.
- `sb current` on v3 shows store model, smallFastModel, the APPLIED
  `env.ANTHROPIC_MODEL` from `~/.claude/settings.json` with an explicit
  in-sync/DRIFT verdict, daemon/APIKEY/web-search state, and a Router summary
  (builtins/rules/fallback).
- `sb doctor` on v3 checks: store readable, profile enabled+set, model &
  smallFastModel leak/catalog/context, whitelist membership, applied-vs-store
  parity, APIKEY blank, **legacy hygiene** (FAILs while the inert legacy
  config.json/.bak files still exist -- rotate the key, then delete), MCP
  parity, web-search state.
- `sb websearch` on v3: `on` is refused with an explanation (v3 has no scoped
  webSearch role; `:online` would bill ALL traffic), `off` strips a stray
  `:online` suffix (no-op reported without writing).
- 101 new hermetic pytest tests (317 total): temp SQLite stores with a fake
  key, injected subprocess/socket seams, store-detection pinned to `legacy`
  in the pre-v3 test suite for hermeticity on v3 machines.

#### Fixed

- The control panel silently no-opped on CCR v3: it read/wrote the legacy
  `config.json`, which v3 ignores (config moved to SQLite; ISS-002, grounded
  in R-006 against the live store and CCR v3.0.5 source). `sb current` now
  reports live state; `sb use` writes the store CCR actually reads. The
  secret `Providers[].api_key` is round-tripped byte-for-byte and never
  printed; the pre-write blob backup stays inside the same SQLite store.

#### Security

- Verified live: two full write round-trips preserved the provider api_key
  hash exactly; no blob contents are ever printed or copied outside the store.

---

### P-003: `sync` — CC→CCR context audit + user-scope MCP mirror (SPEC-003)

#### Added

- `sb sync` subcommand (`sync [--apply] [--prune]`):
  - Read-only audit of which Claude Code context surfaces reach CCR-launched
    sessions: per-server MCP diff (user scope `~/.claude.json` vs the CCR
    `CLAUDE_CONFIG_DIR` scope `~/.claude/.claude.json`), plugin passthrough,
    global CLAUDE.md, plus WARNs for the CCR-managed `settings.json` env block
    and the inert legacy `~/.claude-code-router/config.json` (CCR v3 stores
    config in SQLite). Exit 1 on actionable drift.
  - `--apply`: mirrors drifted user-scope MCP servers (stdio and http/sse) into
    the CCR scope via `claude mcp add-json --scope user` under
    `CLAUDE_CONFIG_DIR` — Claude's own writer; live state files are never
    hand-edited; no CCR restart needed. Updates run remove + re-add (add-json
    refuses to overwrite). Idempotent: a second apply is a no-op.
  - `--prune`: removes only servers recorded in switchboard's sync manifest
    (`~/.claude/.switchboard-sync-manifest.json`); user-added CCR-scope servers
    are reported, never deleted.
  - Secret hygiene: env values, http headers, and key-like fields are never
    printed (reports show names only).
- New modules: `claude_scopes.py` (config-surface readers + audit helpers),
  `mcp_sync.py` (pure diff engine: normalize/fingerprint/build_plan/redact),
  `sync_apply.py` (claude CLI runner + manifest), `sync_cmd.py` (orchestration).
- `sb doctor` gains an `MCP parity (CCR scope)` check.
- `/switchboard:sync` slash command (`commands/sync.md`); `sync` added to the
  `/switchboard` argument hint. Works identically in plain and CCR sessions.
- 48 new pytest tests (216 total), all hermetic; includes an ASCII-output
  regression test for Windows cp1252 consoles.

#### Fixed

- `/switchboard` showed no description or argument hint in the CLI: its
  frontmatter `description` contained an unquoted `: ` (invalid YAML —
  "mapping values are not allowed here"), so the whole frontmatter failed to
  parse and Claude Code got no command metadata. Previously misattributed to a
  CCR client limitation. Also quoted `/catalog`'s `argument-hint`, which
  unquoted parsed as a YAML flow *list* instead of a string. All three command
  files now YAML-validate. (Plugin 0.3.1.)
- User-scope MCP servers (markitdown, yt-transcribe, chrome-devtools,
  smart-memory, plane, obsidian-vault) were invisible in sessions launched by
  the CCR v3 Electron app / `ccr` CLI, because CCR sets
  `CLAUDE_CONFIG_DIR=~/.claude` and the user scope relocates to
  `~/.claude/.claude.json` (ISS-001; root-caused in R-005 against CCR v3.0.5
  source). `sb sync --apply` closes the gap.

---

## [Unreleased] - 2026-06-23

### P-002: Modular refactor and control-panel commands

#### Added

- `src/switchboard/` package with purpose-separated modules:
  - `catalog.py` -- OpenRouter API fetch and `Model` dataclass
  - `ccr_config.py` -- read/write `~/.claude-code-router/config.json`, role management, CCR lifecycle
  - `guard.py` -- `validate_model`: refuses unknown models and models below 64K context; returns nearest alternatives
  - `health.py` -- `status_lines`: effective model, CCR running, APIKEY-blank, web-search state, WARNINGS
  - `checks.py` -- `run_checks` / `format_checks`: structured pass/fail health checks
  - `browse.py` -- `cmd_list`: catalog browse with provider grouping
  - `render.py` -- shared table renderer (plain and `--md` markdown modes)
  - `cli.py` -- dispatch layer: `cmd_use`, `cmd_current`, `cmd_doctor`, `cmd_websearch`, `main`
- Thin `switchboard.py` entry shim (delegates to `src/switchboard/cli.main`).
- `sb use <model>` guard: rejects models not in the live catalog or with fewer than 64K context tokens; prints alternatives on failure; on success pins all CCR roles (including `background`), keeps APIKEY blank, sets webSearch without `:online`.
- `sb doctor` subcommand: structured pass/fail health checks, exits non-zero on any failure.
- `sb websearch on|off` subcommand: toggles `:online` suffix on the webSearch CCR role and restarts CCR.
- Enhanced `sb current`: full routing table plus effective model, CCR-running state, APIKEY-blank state, web-search state, and WARNINGS.
- `/switchboard` slash command at `~/.claude/commands/switchboard.md`: runs any control-panel subcommand from inside a Claude Code session.
- 157 pytest tests covering all modules.

#### Packaging / distribution

- Claude Code **plugin** layout so the repo installs via `/plugin marketplace add ekmungi/switchboard` + `/plugin install switchboard@switchboard`: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and `commands/{catalog,switchboard}.md` that resolve their own path via `${CLAUDE_PLUGIN_ROOT}` (no hardcoded paths).
- `SessionStart` hook (`hooks/ccr_precheck.sh`) that self-gates on `ANTHROPIC_BASE_URL`: it runs a `doctor` pre-flight **only when the session is routed through CCR** (loopback proxy) and surfaces only failing checks; it is silent in a normal Anthropic session and in a healthy CCR session.
- `install.ps1` / `install.sh` bootstrap scripts: prerequisite checks, `uv sync`, idempotent CCR-config scaffold (placeholder key, blank APIKEY, webSearch without `:online` — never overwrites an existing config or writes a secret), and an `sb` shell function.
- `INSTALL.md` walkthrough.

#### Changed

- `sb use` now validates before writing (was write-on-any-input).
- `sb current` now shows a full status block (was model-only).
- `/catalog` slash command output preserved byte-for-byte (`sb list [keyword] --md`).

#### Architecture notes

- Every source module in `src/switchboard/` is under the 200-line limit (largest: `health.py` at 197).
- All data transforms are non-mutating (frozen dataclasses / new dicts).
- The `--md` flag is the only path that emits markdown; all other output is plain text for terminal readability.
