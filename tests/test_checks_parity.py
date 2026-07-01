# test_checks_parity.py - Tests for the doctor MCP-parity check (SPEC-003 R8).
# ---------------------------------------------------------------------------

from switchboard import mcp_sync
from switchboard.checks import mcp_parity_check

STDIO = {"type": "stdio", "command": "x"}


class TestMcpParityCheck:
    """Tests for mcp_parity_check()."""

    def test_passes_when_no_drift(self):
        """Matching scopes produce ok=True with the mirrored count."""
        plan = mcp_sync.build_plan({"a": STDIO}, {"a": dict(STDIO)}, {})
        check = mcp_parity_check(plan)
        assert check.ok is True
        assert "1" in check.detail

    def test_fails_with_drift_count(self):
        """Adds/updates surface as a failing check naming the drifted count."""
        plan = mcp_sync.build_plan({"a": STDIO, "b": STDIO}, {}, {})
        check = mcp_parity_check(plan)
        assert check.ok is False
        assert "2" in check.detail and "sb sync" in check.detail
