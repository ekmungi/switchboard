#!/usr/bin/env bash
# SessionStart pre-flight for switchboard.
#
# GATE: this hook fires at the start of EVERY Claude Code session the plugin is
# enabled in (Claude Code has no concept of CCR), so it self-gates: it only does
# anything when Claude Code is actually routed THROUGH claude-code-router (CCR),
# i.e. its ANTHROPIC_BASE_URL points at the local loopback proxy that `ccr code`
# sets (http://127.0.0.1:<port>). A normal Anthropic session has
# ANTHROPIC_BASE_URL=https://api.anthropic.com (or unset) and exits silently here.
#
# WHEN IT FIRES (CCR session): it reuses `switchboard.py doctor` as the pre-flight.
# doctor exits 0 when everything is healthy (CCR running, APIKEY blank, every role
# on a >=64K in-catalog model, no Anthropic/Haiku leak), in which case this hook
# stays silent. Only when a check FAILS does it print the failing lines, which
# Claude Code injects into the session as context.
set -u

case "${ANTHROPIC_BASE_URL:-}" in
  *127.0.0.1*|*localhost*) : ;;   # CCR session -> run the pre-flight below
  *) exit 0 ;;                     # regular Anthropic session -> do nothing, silently
esac

# Find a Python; if none, do nothing (never break a session over a missing prereq).
PY="$(command -v python || command -v python3)" || exit 0

# doctor: exit 0 = all healthy -> stay silent (no context noise).
if out="$("$PY" "${CLAUDE_PLUGIN_ROOT}/switchboard.py" doctor 2>/dev/null)"; then
  exit 0
fi

# A check failed: surface only the FAIL lines into the session.
echo "Switchboard pre-flight (CCR session) flagged issues:"
printf '%s\n' "$out" | grep -F '[FAIL]'
echo "Fix: sb use <model>  |  sb websearch off  |  run /switchboard doctor for details."
exit 0
