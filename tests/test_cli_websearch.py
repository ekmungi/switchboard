# test_cli_websearch.py - Tests for cli.cmd_websearch (on/off/round-trip/invalid).
#
# All external calls (read_config, write_config, restart_ccr) are monkeypatched.
# set_websearch_online runs for real (pure function, already tested in test_ccr_config.py).
# ---------------------------------------------------------------------------

import copy
import sys

import pytest
from switchboard import cli

# ---------------------------------------------------------------------------
# Base config used by websearch tests: webSearch has NO :online suffix initially.
# ---------------------------------------------------------------------------

_CFG_WEBSEARCH_BASE = {
    "Router": {
        "default": "openrouter,deepseek/deepseek-v4-flash",
        "background": "openrouter,deepseek/deepseek-v4-flash",
        "think": "openrouter,deepseek/deepseek-v4-flash",
        "longContext": "openrouter,deepseek/deepseek-v4-flash",
        "webSearch": "openrouter,deepseek/deepseek-v4-flash",
    }
}


def _make_websearch_patches(monkeypatch, initial_cfg: dict) -> tuple:
    """Patch read_config, write_config, restart_ccr on the cli module.

    Returns (written_cfgs, restart_calls) lists that accumulate side-effects.
    set_websearch_online is NOT patched; it runs for real (pure function).
    """
    written_cfgs: list = []
    restart_calls: list = []

    monkeypatch.setattr(cli, "read_config", lambda: dict(initial_cfg))
    monkeypatch.setattr(cli, "write_config", lambda cfg: written_cfgs.append(cfg))
    monkeypatch.setattr(cli, "restart_ccr", lambda: restart_calls.append(True))

    return written_cfgs, restart_calls


def test_cmd_websearch_on_adds_online_suffix(monkeypatch, capsys):
    """cmd_websearch('on') appends :online to webSearch, writes config, restarts CCR.

    The real set_websearch_online runs; only read_config/write_config/restart_ccr
    are patched.  The printed line must show the new ...:online value.
    """
    written_cfgs, restart_calls = _make_websearch_patches(monkeypatch, _CFG_WEBSEARCH_BASE)

    cli.cmd_websearch("on")

    assert len(written_cfgs) == 1
    assert len(restart_calls) == 1

    new_ws = written_cfgs[0]["Router"]["webSearch"]
    assert new_ws.endswith(":online"), f"Expected :online suffix, got: {new_ws!r}"

    out = capsys.readouterr().out
    assert ":online" in out


def test_cmd_websearch_off_removes_online_suffix(monkeypatch, capsys):
    """cmd_websearch('off') strips :online from webSearch, writes config, restarts CCR.

    Starting config has :online already present; after 'off' it must be absent.
    """
    cfg_with_online = {
        "Router": {
            "default": "openrouter,deepseek/deepseek-v4-flash",
            "background": "openrouter,deepseek/deepseek-v4-flash",
            "think": "openrouter,deepseek/deepseek-v4-flash",
            "longContext": "openrouter,deepseek/deepseek-v4-flash",
            "webSearch": "openrouter,deepseek/deepseek-v4-flash:online",
        }
    }
    written_cfgs, restart_calls = _make_websearch_patches(monkeypatch, cfg_with_online)

    cli.cmd_websearch("off")

    assert len(written_cfgs) == 1
    assert len(restart_calls) == 1

    new_ws = written_cfgs[0]["Router"]["webSearch"]
    assert not new_ws.endswith(":online"), f"Expected :online removed, got: {new_ws!r}"

    out = capsys.readouterr().out
    assert ":online" not in out


def test_cmd_websearch_round_trip(monkeypatch):
    """AC5 round-trip: on then off returns webSearch to the exact original value.

    Drives cmd_websearch twice using a mutable 'current config' stand-in so the
    second call reads the cfg written by the first.  set_websearch_online runs for
    real; only I/O side-effects are patched.
    """
    original_ws = "openrouter,deepseek/deepseek-v4-flash"
    current_cfg = {
        "Router": {
            "default": original_ws,
            "background": original_ws,
            "think": original_ws,
            "longContext": original_ws,
            "webSearch": original_ws,
        }
    }

    state: list = [current_cfg]

    def fake_read() -> dict:
        """Return the most recently written cfg (deep copy to avoid aliasing)."""
        return copy.deepcopy(state[0])

    def fake_write(cfg: dict) -> None:
        """Capture write and advance the current state."""
        state[0] = cfg

    monkeypatch.setattr(cli, "read_config", fake_read)
    monkeypatch.setattr(cli, "write_config", fake_write)
    monkeypatch.setattr(cli, "restart_ccr", lambda: None)

    cli.cmd_websearch("on")
    assert state[0]["Router"]["webSearch"].endswith(":online")

    cli.cmd_websearch("off")
    assert state[0]["Router"]["webSearch"] == original_ws, (
        f"Round-trip failed: expected {original_ws!r}, got {state[0]['Router']['webSearch']!r}"
    )


def test_cmd_websearch_invalid_state_exits_1(monkeypatch):
    """cmd_websearch with an invalid state exits 1 without touching config or CCR.

    read_config, write_config, and restart_ccr must NOT be called.
    """
    read_calls: list = []
    written_cfgs: list = []
    restart_calls: list = []

    monkeypatch.setattr(cli, "read_config", lambda: read_calls.append(True) or {})
    monkeypatch.setattr(cli, "write_config", lambda cfg: written_cfgs.append(cfg))
    monkeypatch.setattr(cli, "restart_ccr", lambda: restart_calls.append(True))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_websearch("maybe")

    assert exc_info.value.code == 1
    assert read_calls == [], "read_config must not be called on invalid state"
    assert written_cfgs == [], "write_config must not be called on invalid state"
    assert restart_calls == [], "restart_ccr must not be called on invalid state"


def test_main_websearch_dispatches_on(monkeypatch):
    """main() with 'websearch on' calls cmd_websearch('on') exactly once."""
    calls: list = []
    monkeypatch.setattr(sys, "argv", ["switchboard", "websearch", "on"])
    monkeypatch.setattr(cli, "cmd_websearch", lambda state: calls.append(state))

    cli.main()

    assert calls == ["on"]


def test_main_websearch_dispatches_off(monkeypatch):
    """main() with 'websearch off' calls cmd_websearch('off') exactly once."""
    calls: list = []
    monkeypatch.setattr(sys, "argv", ["switchboard", "websearch", "off"])
    monkeypatch.setattr(cli, "cmd_websearch", lambda state: calls.append(state))

    cli.main()

    assert calls == ["off"]


def test_main_websearch_no_state_exits_1(monkeypatch, capsys):
    """main() with 'websearch' and no state arg falls through to usage + exit 1.

    'websearch' with no second arg does NOT match the dispatch guard
    (``len(args) > 1`` is False), so it hits the else branch.
    """
    monkeypatch.setattr(sys, "argv", ["switchboard", "websearch"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Usage:" in out
