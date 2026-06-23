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
# cmd_list: markdown output -- exact byte guard for /catalog
# ---------------------------------------------------------------------------


def test_cmd_list_md_output_exact(monkeypatch, capsys):
    """cmd_list in markdown mode produces byte-for-byte identical output for /catalog.

    Sorted ascending by $IN/M: deepseek-chat (0.20) before deepseek-r1 (0.70).
    """
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_TWO))
    cli._MARKDOWN = True

    cli.cmd_list("deepseek")

    out = capsys.readouterr().out
    expected = (
        "\n"
        "2 model(s) matching 'deepseek':\n"
        "Switch in a session:         /model openrouter,<MODEL>\n"
        "Web search (append :online): /model openrouter,<MODEL>:online\n"
        "Set as default (terminal):   sb use <MODEL>\n"
        "\n"
        "| MODEL  (paste after 'openrouter,') | CTX | $IN/M | $OUT/M |\n"
        "| --- | --- | --- | --- |\n"
        "| deepseek/deepseek-chat | 131072 | 0.20 | 0.80 |\n"
        "| deepseek/deepseek-r1 | 163840 | 0.70 | 2.50 |\n"
    )
    assert out == expected


def test_cmd_list_no_query_calls_providers(monkeypatch, capsys):
    """cmd_list with empty query delegates to cmd_providers."""
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_TWO))
    cli._MARKDOWN = True

    cli.cmd_list("")

    out = capsys.readouterr().out
    # providers header line must appear; model table must not
    assert "providers," in out
    assert "MODEL  (paste after" not in out


# ---------------------------------------------------------------------------
# cmd_providers: markdown output -- exact byte guard
# ---------------------------------------------------------------------------


def test_cmd_providers_md_output_exact(capsys):
    """cmd_providers in markdown mode emits the correct header, hint, and table."""
    cli._MARKDOWN = True

    # Two models from same provider; one extra from a second provider.
    model_extra = Model(
        id="openai/gpt-4o",
        name="GPT-4o",
        context_length=128000,
        prompt_price=0.0000025,
        completion_price=0.000010,
    )
    models = [_MODEL_A, _MODEL_B, model_extra]

    cli.cmd_providers(models)

    out = capsys.readouterr().out
    # deepseek has 2 models (listed first by count desc), openai has 1
    expected = (
        "\n"
        "2 providers, 3 models total.\n"
        "See a company's models:  sb list <PROVIDER>   (e.g. sb list deepseek)\n"
        "\n"
        "| PROVIDER | MODELS |\n"
        "| --- | --- |\n"
        "| deepseek | 2 |\n"
        "| openai | 1 |\n"
    )
    assert out == expected


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
    # background context warning
    assert "background" in out
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
    """--md sets _MARKDOWN=True and is not passed down to the subcommand.

    We monkeypatch cmd_list to capture the call; args it receives must not
    contain '--md'.
    """
    captured = []

    def fake_cmd_list(query):
        """Capture the query arg."""
        captured.append(query)

    monkeypatch.setattr(sys, "argv", ["switchboard", "list", "--md"])
    monkeypatch.setattr(cli, "fetch_models", lambda: [])
    monkeypatch.setattr(cli, "cmd_list", fake_cmd_list)

    cli.main()

    assert cli._MARKDOWN is True
    # cmd_list was called with the remaining arg (empty string default)
    assert captured == [""]


def test_main_list_dispatches_with_query(monkeypatch):
    """main() with 'list <query>' dispatches to cmd_list with the correct query."""
    captured = []

    def fake_cmd_list(query):
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
