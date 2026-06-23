# test_cli_use.py - Tests for cli.cmd_use (guard refusal + success path).
#
# All external calls (fetch_models, set_all_roles, ensure_apikey_blank,
# write_config, restart_ccr) are monkeypatched -- no live network, no file I/O.
# ---------------------------------------------------------------------------

import pytest
from switchboard import cli
from switchboard.catalog import Model

# ---------------------------------------------------------------------------
# Shared catalog fixtures used by cmd_use tests
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

_MODELS_GUARD = [_MODEL_A, _MODEL_B, _MODEL_V4, _MODEL_SMALL]


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
    assert "'nope/nope' is not in the OpenRouter catalog." in out
    assert "Nearest valid alternatives:" in out
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

    assert "deepseek/deepseek-v4-flash" in out
    assert "1,048,576" in out or "1048576" in out
    assert "background" in out

    assert call_log[0] == ("set_all_roles", "deepseek/deepseek-v4-flash", False)
    assert call_log[1] == ("ensure_apikey_blank",)
    assert call_log[2] == ("write_config", after_apikey_cfg)
    assert call_log[3] == ("restart_ccr",)
    assert len(call_log) == 4
