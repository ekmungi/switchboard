# test_cli_current.py - Tests for cli.cmd_current (routing table, status block, offline note).
#
# All external calls (fetch_models, read_config, ccr_running) are monkeypatched.
# ---------------------------------------------------------------------------

import pytest
from switchboard import cli
from switchboard.catalog import Model

# ---------------------------------------------------------------------------
# Shared catalog fixtures used by cmd_current tests
# ---------------------------------------------------------------------------

_MODEL_A = Model(
    id="deepseek/deepseek-chat",
    name="DeepSeek Chat",
    context_length=131072,
    prompt_price=0.0000002,
    completion_price=0.0000008,
)

_MODEL_B = Model(
    id="deepseek/deepseek-r1",
    name="DeepSeek R1",
    context_length=163840,
    prompt_price=0.0000007,
    completion_price=0.0000025,
)

_MODEL_V4 = Model(
    id="deepseek/deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    context_length=1048576,
    prompt_price=0.0000001,
    completion_price=0.0000003,
)

_MODEL_SMALL = Model(
    id="x/small",
    name="Tiny",
    context_length=32768,
    prompt_price=0.0000001,
    completion_price=0.0000002,
)

_MODELS_TWO = [_MODEL_A, _MODEL_B]
_MODELS_GUARD = [_MODEL_A, _MODEL_B, _MODEL_V4, _MODEL_SMALL]

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
    for role in ["default", "background", "think", "longContext", "webSearch"]:
        assert out.count(role) == 1, f"role '{role}' appeared != 1 time"
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
    assert out.count("background") >= 2, (
        f"Expected 'background' >= 2 times (table + warning), got {out.count('background')}"
    )
    assert "APIKEY" in out


def test_cmd_current_catalog_fetch_error_does_not_crash(monkeypatch, capsys):
    """cmd_current degrades gracefully when fetch_models raises an exception.

    The offline note must appear AFTER the status block lines.
    """
    def _boom():
        raise RuntimeError("network error")

    monkeypatch.setattr(cli, "read_config", lambda: _CFG_CURRENT)
    monkeypatch.setattr(cli, "fetch_models", _boom)
    monkeypatch.setattr(cli, "ccr_running", lambda: False)

    cli.cmd_current()  # must NOT raise

    out = capsys.readouterr().out
    assert "Current CCR routing" in out
    assert "offline" in out.lower() or "unavailable" in out.lower()
    # Offline note must appear AFTER the status block (after "Effective model")
    note_idx = out.lower().find("offline") if "offline" in out.lower() else out.lower().find("unavailable")
    status_idx = out.find("Effective model")
    assert note_idx > status_idx, (
        "Offline note must appear after the status block, not before it"
    )
