---
description: Switchboard control panel: show/guard the OpenRouter model driving Claude Code (current/doctor/use/websearch)
argument-hint: "[current | doctor | use <model> | websearch on|off | list <keyword>]  (empty = usage/help)"
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/switchboard.py" $ARGUMENTS`

The block above was produced by the switchboard tool and is a status or health report.
Your only job is to reproduce it for me EXACTLY:

- Output every single line. Do NOT truncate, summarize, sample, or drop any lines.
- Keep all formatting (table columns, spacing, PASS/FAIL markers) exactly as printed.
- Add NO commentary, preamble, or closing remarks before or after.
- If the output is empty, reply with exactly: (no output)
