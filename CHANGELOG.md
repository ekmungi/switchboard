# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
- 156 pytest tests covering all modules.

#### Changed

- `sb use` now validates before writing (was write-on-any-input).
- `sb current` now shows a full status block (was model-only).
- `/catalog` slash command output preserved byte-for-byte (`sb list [keyword] --md`).

#### Architecture notes

- Every source module in `src/switchboard/` is under the 200-line limit (largest: `health.py` at 197).
- All data transforms are non-mutating (frozen dataclasses / new dicts).
- The `--md` flag is the only path that emits markdown; all other output is plain text for terminal readability.
