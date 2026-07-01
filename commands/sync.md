---
description: Audit Claude Code -> CCR context routing and mirror user-scope MCP servers into CCR's config scope (fixes MCP servers missing in CCR sessions)
argument-hint: "[--apply | --prune]  (empty = read-only audit)"
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/switchboard.py" sync $ARGUMENTS`

The block above was produced by the switchboard tool and is a sync/audit report.
Your only job is to reproduce it for me EXACTLY:

- Output every single line. Do NOT truncate, summarize, sample, or drop any lines.
- Keep all formatting (columns, spacing, [SYNC]/[DRIFT]/[WARN]/[INFO] markers) exactly as printed.
- Add NO commentary, preamble, or closing remarks before or after.
- If the output is empty, reply with exactly: (no output)
