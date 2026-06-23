# test_cli_doctor.py - Tests for cli.cmd_doctor (pass/fail health checks via CLI).
#
# All external calls (fetch_models, read_config, ccr_running) are monkeypatched.
# ---------------------------------------------------------------------------

import pytest
from switchboard import cli
from switchboard.catalog import Model

# ---------------------------------------------------------------------------
# Shared catalog fixtures used by cmd_doctor tests
# ---------------------------------------------------------------------------

_MODEL_V4 = Model(
    id="deepseek/deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    context_length=1048576,
    prompt_price=0.0000001,
    completion_price=0.0000003,
)

# Shared catalog for doctor tests: all-good models, large context.
_CATALOG_DOCTOR = [_MODEL_V4]

# A known-good router for doctor tests: all roles -> v4-flash, no :online.
_ROUTER_DOCTOR_GOOD = {
    "default": "openrouter,deepseek/deepseek-v4-flash",
    "background": "openrouter,deepseek/deepseek-v4-flash",
    "think": "openrouter,deepseek/deepseek-v4-flash",
    "longContext": "openrouter,deepseek/deepseek-v4-flash",
    "webSearch": "openrouter,deepseek/deepseek-v4-flash",
}
_CFG_DOCTOR_GOOD = {"APIKEY": "", "Router": _ROUTER_DOCTOR_GOOD}


def test_cmd_doctor_all_pass_prints_pass_lines_and_no_sysexit(monkeypatch, capsys):
    """cmd_doctor with all-ok checks prints [PASS] lines and does not call sys.exit."""
    monkeypatch.setattr(cli, "ccr_running", lambda: True)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_CATALOG_DOCTOR))
    monkeypatch.setattr(cli, "read_config", lambda: _CFG_DOCTOR_GOOD)

    cli.cmd_doctor()

    out = capsys.readouterr().out
    assert "Switchboard doctor:" in out
    assert "[PASS]" in out
    assert "[FAIL]" not in out


def test_cmd_doctor_failing_check_raises_sysexit_1(monkeypatch, capsys):
    """cmd_doctor exits with code 1 when at least one check fails."""
    monkeypatch.setattr(cli, "ccr_running", lambda: True)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_CATALOG_DOCTOR))
    cfg = {"APIKEY": "sk-leaked", "Router": _ROUTER_DOCTOR_GOOD}
    monkeypatch.setattr(cli, "read_config", lambda: cfg)

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_doctor()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out


def test_cmd_doctor_ccr_down_shows_fail_line(monkeypatch, capsys):
    """cmd_doctor shows [FAIL] for CCR running when ccr_up is False."""
    monkeypatch.setattr(cli, "ccr_running", lambda: False)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_CATALOG_DOCTOR))
    monkeypatch.setattr(cli, "read_config", lambda: _CFG_DOCTOR_GOOD)

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_doctor()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "[FAIL] CCR running" in out


def test_cmd_doctor_fetch_error_degrades_gracefully(monkeypatch, capsys):
    """cmd_doctor handles fetch_models exceptions by treating catalog as empty."""
    monkeypatch.setattr(cli, "ccr_running", lambda: True)
    monkeypatch.setattr(cli, "fetch_models", lambda: (_ for _ in ()).throw(RuntimeError("net")))
    monkeypatch.setattr(cli, "read_config", lambda: _CFG_DOCTOR_GOOD)

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_doctor()

    assert exc_info.value.code == 1


def test_main_doctor_dispatches(monkeypatch):
    """main() with 'doctor' calls cmd_doctor exactly once."""
    import sys
    calls = []
    monkeypatch.setattr(sys, "argv", ["switchboard", "doctor"])
    monkeypatch.setattr(cli, "cmd_doctor", lambda: calls.append(True))

    cli.main()

    assert calls == [True]
