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

_MODELS_TWO = [_MODEL_A, _MODEL_B]


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
# cmd_use
# ---------------------------------------------------------------------------


def test_cmd_use_unknown_model_exits_1(monkeypatch, capsys):
    """cmd_use with an unknown model_id prints error and exits 1.

    write_config and restart_ccr must NOT be called.
    """
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_TWO))
    write_called = []
    restart_called = []
    monkeypatch.setattr(cli, "write_config", lambda cfg: write_called.append(cfg))
    monkeypatch.setattr(cli, "restart_ccr", lambda: restart_called.append(True))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_use("openai/gpt-4-turbo")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "'openai/gpt-4-turbo' is not in the OpenRouter catalog." in out
    assert "Try: sb list openai" in out
    assert write_called == []
    assert restart_called == []


def test_cmd_use_known_model_sets_all_roles(monkeypatch, capsys):
    """cmd_use with a valid model_id calls set_all_roles(online=True), write_config, restart_ccr."""
    monkeypatch.setattr(cli, "fetch_models", lambda: list(_MODELS_TWO))

    dummy_cfg = {"Router": {}}
    updated_cfg = {"Router": {"default": "openrouter,deepseek/deepseek-chat"}}

    set_all_roles_calls = []

    def fake_read_config():
        """Return a dummy config."""
        return dummy_cfg

    def fake_set_all_roles(cfg, model_id, online=False):
        """Record arguments and return an updated config."""
        set_all_roles_calls.append((cfg, model_id, online))
        return updated_cfg

    write_calls = []
    restart_calls = []
    monkeypatch.setattr(cli, "read_config", fake_read_config)
    monkeypatch.setattr(cli, "set_all_roles", fake_set_all_roles)
    monkeypatch.setattr(cli, "write_config", lambda cfg: write_calls.append(cfg))
    monkeypatch.setattr(cli, "restart_ccr", lambda: restart_calls.append(True))

    cli.cmd_use("deepseek/deepseek-chat")

    out = capsys.readouterr().out
    expected = "Pinned all roles to deepseek/deepseek-chat (webSearch -> deepseek/deepseek-chat:online).\n"
    assert out == expected

    # set_all_roles must be called with online=True
    assert len(set_all_roles_calls) == 1
    _, called_model, called_online = set_all_roles_calls[0]
    assert called_model == "deepseek/deepseek-chat"
    assert called_online is True

    # write_config gets the updated cfg returned by set_all_roles
    assert write_calls == [updated_cfg]
    # restart_ccr was invoked
    assert restart_calls == [True]


# ---------------------------------------------------------------------------
# cmd_current
# ---------------------------------------------------------------------------


def test_cmd_current_shows_all_five_roles_once(monkeypatch, capsys):
    """cmd_current shows exactly the five ROLES, each exactly once.

    webSearch must NOT appear twice (regression guard for ROLES + ['webSearch'] bug).
    """
    router = {
        "default": "openrouter,deepseek/deepseek-chat",
        "background": "openrouter,deepseek/deepseek-chat",
        "think": "openrouter,deepseek/deepseek-chat",
        "longContext": "openrouter,deepseek/deepseek-chat",
        "webSearch": "openrouter,deepseek/deepseek-chat:online",
        "longContextThreshold": 200000,  # should NOT appear as a row
    }
    monkeypatch.setattr(cli, "read_config", lambda: {"Router": router})
    cli._MARKDOWN = True

    cli.cmd_current()

    out = capsys.readouterr().out
    # Exactly one occurrence of each role
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
