# tests/test_cli.py - tests for the switchboard.cli module.
#
# TDD: tests are written before the implementation (or in lock-step with it).
# All external calls (fetch_models, read_config, write_config, set_all_roles,
# restart_ccr) are monkeypatched -- no live network, no file I/O, no CCR process.
# ---------------------------------------------------------------------------

import sys
import pytest
from switchboard import cli
from switchboard.catalog import Model

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_MODEL_A = Model(
    id="deepseek/deepseek-chat",
    name="DeepSeek Chat",
    context_length=131072,
    prompt_price=0.0000002,   # 0.20 per million
    completion_price=0.0000008,  # 0.80 per million
)

_MODEL_B = Model(
    id="deepseek/deepseek-r1",
    name="DeepSeek R1",
    context_length=163840,
    prompt_price=0.0000007,   # 0.70 per million
    completion_price=0.0000025,  # 2.50 per million
)

# Large context model used as the primary acceptance target (Task 5 catalog).
_MODEL_V4 = Model(
    id="deepseek/deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    context_length=1048576,
    prompt_price=0.0000001,   # 0.10 per million
    completion_price=0.0000003,
)

# Small model: context below the 64K guard minimum (32K).
_MODEL_SMALL = Model(
    id="x/small",
    name="Tiny",
    context_length=32768,
    prompt_price=0.0000001,
    completion_price=0.0000002,
)

_MODELS_TWO = [_MODEL_A, _MODEL_B]

# Extended catalog used for Task-5 guard tests.
_MODELS_GUARD = [_MODEL_A, _MODEL_B, _MODEL_V4, _MODEL_SMALL]


@pytest.fixture(autouse=True)
def reset_markdown():
    """Reset the module-level _MARKDOWN flag between every test."""
    cli._MARKDOWN = False
    yield
    cli._MARKDOWN = False


# ---------------------------------------------------------------------------
# _print_table: markdown branch (direct unit test)
# ---------------------------------------------------------------------------


def test_print_table_markdown_branch(capsys):
    """_print_table with _MARKDOWN=True emits pipe-delimited markdown rows."""
    cli._MARKDOWN = True
    columns = [("COL_A", "left", 10), ("COL_B", "right", 5)]
    rows = [("foo", "bar"), ("baz", "qux")]
    cli._print_table(columns, rows)
    out = capsys.readouterr().out
    assert out == (
        "| COL_A | COL_B |\n"
        "| --- | --- |\n"
        "| foo | bar |\n"
        "| baz | qux |\n"
    )


# ---------------------------------------------------------------------------
# cmd_use  (Task 5: guarded behavior -- real validate_model, not stubbed)
# ---------------------------------------------------------------------------
# Catalog: _MODELS_GUARD contains one >=64K model (deepseek-v4-flash, 1M ctx),
# two >=64K models (deepseek-chat 131K, deepseek-r1 163K), and one too-small
# model (x/small, 32K).  The real guard runs; only fetch_models is patched.


def test_cmd_use_unknown_model_exits_1(monkeypatch, capsys):
    """cmd_use with a model not in catalog prints the guard reason + suggestions, exits 1.

    set_all_roles, ensure_apikey_blank, write_config, restart_ccr must NOT be called.
    The real validate_model runs (no stub on the guard).
    """
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_GUARD))
    set_all_roles_calls: list = []
    ensure_calls: list = []
    write_called: list = []
    restart_called: list = []
    monkeypatch.setattr(cli, "set_all_roles",
                        lambda cfg, mid, online=False: set_all_roles_calls.append((cfg, mid, online)) or cfg)
    monkeypatch.setattr(cli, "ensure_apikey_blank",
                        lambda cfg: ensure_calls.append(cfg) or cfg)
    monkeypatch.setattr(cli, "write_config", lambda cfg: write_called.append(cfg))
    monkeypatch.setattr(cli, "restart_ccr", lambda: restart_called.append(True))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_use("nope/nope")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    # Guard must print the reason (unknown id message)
    assert "'nope/nope' is not in the OpenRouter catalog." in out
    # Suggestions header must appear (there are valid models in catalog)
    assert "Nearest valid alternatives:" in out
    # None of the write-path functions must be invoked
    assert set_all_roles_calls == []
    assert ensure_calls == []
    assert write_called == []
    assert restart_called == []


def test_cmd_use_too_small_model_exits_1(monkeypatch, capsys):
    """cmd_use with a model whose context < 64K prints the guard reason, exits 1.

    The real validate_model runs and catches the too-small context failure.
    set_all_roles, ensure_apikey_blank, write_config, restart_ccr must NOT be called.
    """
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_GUARD))
    set_all_roles_calls: list = []
    ensure_calls: list = []
    write_called: list = []
    restart_called: list = []
    monkeypatch.setattr(cli, "set_all_roles",
                        lambda cfg, mid, online=False: set_all_roles_calls.append((cfg, mid, online)) or cfg)
    monkeypatch.setattr(cli, "ensure_apikey_blank",
                        lambda cfg: ensure_calls.append(cfg) or cfg)
    monkeypatch.setattr(cli, "write_config", lambda cfg: write_called.append(cfg))
    monkeypatch.setattr(cli, "restart_ccr", lambda: restart_called.append(True))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_use("x/small")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    # Guard reason must mention the context size using thousands-separator format
    assert "32,768" in out
    assert "minimum" in out
    assert set_all_roles_calls == []
    assert ensure_calls == []
    assert write_called == []
    assert restart_called == []


def test_cmd_use_valid_model_uses_online_false(monkeypatch, capsys):
    """cmd_use with a valid >=64K model calls set_all_roles(online=False), not True.

    This is the deliberate Task-5 safety change: webSearch is set WITHOUT :online
    by default so there is no surprise web billing.  ensure_apikey_blank is also
    called, and write_config is called before restart_ccr.
    """
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_GUARD))

    dummy_cfg: dict = {"Router": {}}
    after_roles_cfg: dict = {"Router": {"default": "openrouter,deepseek/deepseek-v4-flash"}}
    after_apikey_cfg: dict = {**after_roles_cfg, "APIKEY": ""}

    call_log: list = []

    def fake_read_config() -> dict:
        """Return a dummy config."""
        return dummy_cfg

    def fake_set_all_roles(cfg: dict, model_id: str, online: bool = False) -> dict:
        """Record arguments; return a modified config."""
        call_log.append(("set_all_roles", model_id, online))
        return after_roles_cfg

    def fake_ensure_apikey_blank(cfg: dict) -> dict:
        """Record call; return config with APIKEY blanked."""
        call_log.append(("ensure_apikey_blank",))
        return after_apikey_cfg

    def fake_write_config(cfg: dict) -> None:
        """Record the config passed in."""
        call_log.append(("write_config", cfg))

    def fake_restart_ccr() -> None:
        """Record the restart call."""
        call_log.append(("restart_ccr",))

    monkeypatch.setattr(cli, "read_config", fake_read_config)
    monkeypatch.setattr(cli, "set_all_roles", fake_set_all_roles)
    monkeypatch.setattr(cli, "ensure_apikey_blank", fake_ensure_apikey_blank)
    monkeypatch.setattr(cli, "write_config", fake_write_config)
    monkeypatch.setattr(cli, "restart_ccr", fake_restart_ccr)

    cli.cmd_use("deepseek/deepseek-v4-flash")

    out = capsys.readouterr().out

    # Confirmation must mention the model, context size, and background role
    assert "deepseek/deepseek-v4-flash" in out
    assert "1,048,576" in out or "1048576" in out
    assert "background" in out

    # set_all_roles must be called with online=False (the safety default)
    assert call_log[0] == ("set_all_roles", "deepseek/deepseek-v4-flash", False)

    # ensure_apikey_blank must be called after set_all_roles
    assert call_log[1] == ("ensure_apikey_blank",)

    # write_config must be called with the result of ensure_apikey_blank
    assert call_log[2] == ("write_config", after_apikey_cfg)

    # restart_ccr must be called last
    assert call_log[3] == ("restart_ccr",)

    # Total call count
    assert len(call_log) == 4


# ---------------------------------------------------------------------------
# cmd_current
# ---------------------------------------------------------------------------

# Shared router used for cmd_current tests.
_ROUTER_CURRENT = {
    "default": "openrouter,deepseek/deepseek-chat",
    "background": "openrouter,deepseek/deepseek-chat",
    "think": "openrouter,deepseek/deepseek-chat",
    "longContext": "openrouter,deepseek/deepseek-chat",
    "webSearch": "openrouter,deepseek/deepseek-chat:online",
    "longContextThreshold": 200000,  # should NOT appear as a row
}
_CFG_CURRENT = {"APIKEY": "", "Router": _ROUTER_CURRENT}


def test_cmd_current_shows_all_five_roles_once(monkeypatch, capsys):
    """cmd_current shows exactly the five ROLES each exactly once in the table.

    webSearch must NOT appear twice (regression guard).  The status block adds
    extra lines but each role name must still appear exactly once overall.
    """
    monkeypatch.setattr(cli, "read_config", lambda: _CFG_CURRENT)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_TWO))
    monkeypatch.setattr(cli, "ccr_running", lambda: False)
    cli._MARKDOWN = True

    cli.cmd_current()

    out = capsys.readouterr().out
    # Each role appears exactly once (in the table rows; the status block does
    # not repeat role names).
    for role in ["default", "background", "think", "longContext", "webSearch"]:
        assert out.count(role) == 1, f"role '{role}' appeared != 1 time"
    # Non-role key must not appear as a row
    assert "longContextThreshold" not in out


def test_cmd_current_no_router_prints_warning(monkeypatch, capsys):
    """cmd_current with empty Router prints the 'No Router config found' warning."""
    monkeypatch.setattr(cli, "read_config", lambda: {})

    cli.cmd_current()

    out = capsys.readouterr().out
    assert "No Router config found at" in out


def test_cmd_current_good_config_shows_effective_model_and_no_warnings(monkeypatch, capsys):
    """cmd_current with all roles on a >=64K catalog model shows effective model.

    For a perfectly healthy config the WARNINGS block must NOT appear.
    """
    # All five roles on deepseek-chat (131K context, in catalog), APIKEY blank.
    router_all_chat = {
        "default": "openrouter,deepseek/deepseek-chat",
        "background": "openrouter,deepseek/deepseek-chat",
        "think": "openrouter,deepseek/deepseek-chat",
        "longContext": "openrouter,deepseek/deepseek-chat",
        "webSearch": "openrouter,deepseek/deepseek-chat",
    }
    cfg = {"APIKEY": "", "Router": router_all_chat}

    monkeypatch.setattr(cli, "read_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_TWO))
    monkeypatch.setattr(cli, "ccr_running", lambda: True)

    cli.cmd_current()

    out = capsys.readouterr().out
    assert "deepseek/deepseek-chat" in out
    assert "Effective model" in out
    assert "WARNINGS:" not in out


def test_cmd_current_broken_config_shows_warnings(monkeypatch, capsys):
    """cmd_current with a small-context role and non-blank APIKEY shows WARNINGS block."""
    # background role on a too-small model (32K), APIKEY non-blank.
    router_broken = {
        "default": "openrouter,deepseek/deepseek-chat",
        "background": "openrouter,x/small",
        "think": "openrouter,deepseek/deepseek-chat",
        "longContext": "openrouter,deepseek/deepseek-chat",
        "webSearch": "openrouter,deepseek/deepseek-chat",
    }
    cfg = {"APIKEY": "sk-leaked", "Router": router_broken}

    monkeypatch.setattr(cli, "read_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_GUARD))
    monkeypatch.setattr(cli, "ccr_running", lambda: False)

    cli.cmd_current()

    out = capsys.readouterr().out
    assert "WARNINGS:" in out
    # background must appear at least twice: once in the routing table row and once
    # in the WARNINGS block (proving the warning specifically references that role).
    assert out.count("background") >= 2, (
        f"Expected 'background' >= 2 times (table + warning), got {out.count('background')}"
    )
    # APIKEY warning
    assert "APIKEY" in out


def test_cmd_current_catalog_fetch_error_does_not_crash(monkeypatch, capsys):
    """cmd_current degrades gracefully when fetch_models raises an exception."""
    def _boom():
        raise RuntimeError("network error")

    monkeypatch.setattr(cli, "read_config", lambda: _CFG_CURRENT)
    monkeypatch.setattr(cli, "fetch_models", _boom)
    monkeypatch.setattr(cli, "ccr_running", lambda: False)

    cli.cmd_current()  # must NOT raise

    out = capsys.readouterr().out
    assert "Current CCR routing" in out
    assert "offline" in out.lower() or "unavailable" in out.lower()


# ---------------------------------------------------------------------------
# cmd_doctor
# ---------------------------------------------------------------------------

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

    # Must not raise SystemExit
    cli.cmd_doctor()

    out = capsys.readouterr().out
    assert "Switchboard doctor:" in out
    assert "[PASS]" in out
    assert "[FAIL]" not in out


def test_cmd_doctor_failing_check_raises_sysexit_1(monkeypatch, capsys):
    """cmd_doctor exits with code 1 when at least one check fails."""
    monkeypatch.setattr(cli, "ccr_running", lambda: True)
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_CATALOG_DOCTOR))
    # APIKEY non-blank -> APIKEY check fails
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

    # Should not raise an unhandled exception; catalog unavailable -> catalog check fails -> exit 1
    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_doctor()

    assert exc_info.value.code == 1


def test_main_doctor_dispatches(monkeypatch):
    """main() with 'doctor' calls cmd_doctor exactly once."""
    calls = []
    monkeypatch.setattr(sys, "argv", ["switchboard", "doctor"])
    monkeypatch.setattr(cli, "cmd_doctor", lambda: calls.append(True))

    cli.main()

    assert calls == [True]


# ---------------------------------------------------------------------------
# main: flag and dispatch
# ---------------------------------------------------------------------------


def test_main_no_args_prints_usage(monkeypatch, capsys):
    """main() with no arguments prints the module docstring."""
    monkeypatch.setattr(sys, "argv", ["switchboard"])

    cli.main()

    out = capsys.readouterr().out
    assert "Usage:" in out


def test_main_unknown_cmd_exits_1(monkeypatch, capsys):
    """main() with an unrecognised command prints usage and exits 1."""
    monkeypatch.setattr(sys, "argv", ["switchboard", "bogus"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_main_md_flag_sets_markdown_and_stripped(monkeypatch):
    """--md sets _MARKDOWN=True and is passed as the markdown arg to cmd_list.

    We monkeypatch cmd_list to capture the call; the query arg must be the
    empty string (no --md leaked into the query position).
    """
    captured = []

    def fake_cmd_list(query, markdown=False):
        """Capture the query and markdown args."""
        captured.append((query, markdown))

    monkeypatch.setattr(sys, "argv", ["switchboard", "list", "--md"])
    monkeypatch.setattr(cli, "fetch_models", lambda: [])
    monkeypatch.setattr(cli, "cmd_list", fake_cmd_list)

    cli.main()

    assert cli._MARKDOWN is True
    # cmd_list was called with query="" and markdown=True
    assert captured == [("", True)]


def test_main_list_dispatches_with_query(monkeypatch):
    """main() with 'list <query>' dispatches to cmd_list with the correct query."""
    captured = []

    def fake_cmd_list(query, markdown=False):
        """Capture the query arg."""
        captured.append(query)

    monkeypatch.setattr(sys, "argv", ["switchboard", "list", "deepseek"])
    monkeypatch.setattr(cli, "cmd_list", fake_cmd_list)

    cli.main()

    assert captured == ["deepseek"]


def test_main_current_dispatches(monkeypatch):
    """main() with 'current' calls cmd_current exactly once."""
    calls = []
    monkeypatch.setattr(sys, "argv", ["switchboard", "current"])
    monkeypatch.setattr(cli, "cmd_current", lambda: calls.append(True))

    cli.main()

    assert calls == [True]


def test_main_use_dispatches_with_model(monkeypatch):
    """main() with 'use <model>' calls cmd_use with the model id."""
    calls = []
    monkeypatch.setattr(sys, "argv", ["switchboard", "use", "deepseek/deepseek-chat"])
    monkeypatch.setattr(cli, "cmd_use", lambda mid: calls.append(mid))

    cli.main()

    assert calls == ["deepseek/deepseek-chat"]


# ---------------------------------------------------------------------------
# cmd_websearch
# ---------------------------------------------------------------------------

# Base config used by websearch tests: webSearch has NO :online suffix initially.
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
    set_websearch_online is NOT patched; it runs for real (pure function, already tested).
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

    # Exactly one write and one restart
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

    # Track the last written cfg so each read_config call returns the latest state.
    state: list = [current_cfg]

    def fake_read() -> dict:
        """Return the most recently written cfg."""
        return dict(state[0])

    def fake_write(cfg: dict) -> None:
        """Capture write and advance the current state."""
        state[0] = cfg

    monkeypatch.setattr(cli, "read_config", fake_read)
    monkeypatch.setattr(cli, "write_config", fake_write)
    monkeypatch.setattr(cli, "restart_ccr", lambda: None)

    # Turn ON -- webSearch must gain :online
    cli.cmd_websearch("on")
    assert state[0]["Router"]["webSearch"].endswith(":online")

    # Turn OFF -- webSearch must return to the exact original value
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


# ---------------------------------------------------------------------------
# main: websearch dispatch
# ---------------------------------------------------------------------------


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
