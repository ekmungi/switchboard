---
description: Browse/search the OpenRouter model catalog (via switchboard)
argument-hint: "[optional keyword, e.g. deepseek; empty = all providers]"
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/switchboard.py" list $ARGUMENTS --md`

The block above was produced by the switchboard tool and is already a COMPLETE markdown
table. Your only job is to reproduce it for me EXACTLY:

- Output every single row. Do NOT truncate, summarize, sample, or drop any rows.
- Keep it as a markdown table; do not change columns, values, order, or formatting.
- Echo the plain lines above the table (the count and the switch hints) verbatim too.
- Add NO commentary, preamble, or closing remarks before or after.
- If the table is empty, reply with exactly: no matches
