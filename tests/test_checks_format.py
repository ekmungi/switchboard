# test_checks_format.py - Tests for the Check dataclass and format_checks.
#
# Pure logic tests -- no network, filesystem, or CCR process.
# ---------------------------------------------------------------------------

import pytest
from switchboard.checks import Check, format_checks


# ---------------------------------------------------------------------------
# Check dataclass
# ---------------------------------------------------------------------------


def test_check_is_frozen():
    """Check is a frozen dataclass -- attempts to set attributes raise FrozenInstanceError."""
    c = Check(name="foo", ok=True, detail="bar")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        c.ok = False  # type: ignore[misc]


def test_check_fields():
    """Check stores name, ok, and detail correctly."""
    c = Check(name="CCR running", ok=False, detail="not reachable")
    assert c.name == "CCR running"
    assert c.ok is False
    assert c.detail == "not reachable"


# ---------------------------------------------------------------------------
# format_checks
# ---------------------------------------------------------------------------


def test_format_checks_pass_line():
    """format_checks emits [PASS] lines for ok=True checks."""
    checks = [Check(name="CCR running", ok=True, detail="reachable")]
    lines = format_checks(checks)
    assert lines == ["[PASS] CCR running: reachable"]


def test_format_checks_fail_line():
    """format_checks emits [FAIL] lines for ok=False checks."""
    checks = [Check(name="CCR running", ok=False, detail="not reachable")]
    lines = format_checks(checks)
    assert lines == ["[FAIL] CCR running: not reachable"]


def test_format_checks_multiple():
    """format_checks returns one line per check, in order."""
    checks = [
        Check(name="a", ok=True, detail="good"),
        Check(name="b", ok=False, detail="bad"),
    ]
    lines = format_checks(checks)
    assert len(lines) == 2
    assert lines[0].startswith("[PASS]")
    assert lines[1].startswith("[FAIL]")
