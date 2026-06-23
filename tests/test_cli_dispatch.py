# test_cli_dispatch.py - Tests for cli.main() dispatch, --md flag, and _print_table markdown.
#
# All external calls (cmd_list, cmd_current, cmd_use, cmd_websearch, cmd_doctor,
# fetch_models) are monkeypatched -- no live network, no file I/O.
# ---------------------------------------------------------------------------

import sys

import pytest
from switchboard import cli


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
# main: basic dispatch
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
