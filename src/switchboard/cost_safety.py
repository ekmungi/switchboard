# cost_safety.py - The single guard that keeps every tier routed to a cheap model.
#
# With ANTHROPIC_BASE_URL set, ALL of Claude Code's traffic -- main answer,
# background/small-fast helper, and every spawned subagent -- flows through the
# proxy. So a profile must never map a tier to a Claude-priced anthropic/* model,
# nor use a passthrough wildcard, or a long multi-agent session silently leaks
# metered Claude pricing (SPEC-005 R3a). Both the config generator (write time) and
# `sb doctor` (audit time, R5a) decide safety through this one predicate, so the two
# can never drift.

CLAUDE_PRICED_PREFIX: str = "anthropic/"
"""Provider prefix of Claude-priced OpenRouter models -- forbidden as any tier target."""


def unsafe_reason(target: str) -> str | None:
    """Return why *target* is cost-unsafe as a routing destination, or None if safe.

    Unsafe shapes:
      - empty / whitespace: no model resolved.
      - anthropic/*: Claude-priced -- every subagent/background call would bill
        metered Claude pricing through OpenRouter.
      - '*' or '.../*': a passthrough wildcard -- forwards whatever model string
        arrives, defeating the explicit cheap mapping.

    Args:
        target: The OpenRouter model id a tier (or the catch-all) maps to.

    Returns:
        A human-readable reason string when unsafe, else None.
    """
    if not target or not target.strip():
        return "empty model target"
    if target.startswith(CLAUDE_PRICED_PREFIX):
        return f"Claude-priced model {target!r} (anthropic/* leaks metered pricing)"
    if target == "*" or target.endswith("/*"):
        return f"passthrough wildcard {target!r} (forwards arbitrary models)"
    return None


def is_safe(target: str) -> bool:
    """Return True iff *target* is a safe (cheap, concrete) routing destination."""
    return unsafe_reason(target) is None
