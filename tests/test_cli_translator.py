# test_cli_translator.py - CLI dispatch for the translator commands (sb setup / sb code).
#
# Hermetic: setup.run_setup and launch.run_code are monkeypatched; no proxy, no claude.

import sys

import pytest

from switchboard import cli, launch, setup
from switchboard.launch import LaunchResult
from switchboard.setup import SetupResult


def _ok_setup(**kwargs):
    return SetupResult(ok=True, steps=["engine 1.81.14 (present)"], message="ready -- `sb code` will use X")


class TestSetupDispatch:
    """`sb setup` routes to setup.run_setup and reports the outcome."""

    def test_routes_and_prints_ready(self, monkeypatch, capsys):
        calls = []
        def fake(**kwargs):
            calls.append(kwargs)
            return _ok_setup()
        monkeypatch.setattr(setup, "run_setup", fake)
        monkeypatch.setattr(sys, "argv", ["sb", "setup"])
        cli.main()
        assert len(calls) == 1
        out = capsys.readouterr().out
        assert "ready" in out and "1.81.14" in out

    def test_failure_exits_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr(setup, "run_setup", lambda **k: SetupResult(ok=False, steps=[], message="uv not found"))
        monkeypatch.setattr(sys, "argv", ["sb", "setup"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        assert "uv not found" in capsys.readouterr().out


def _ok_launch(arg=None, **kwargs):
    return LaunchResult(ok=True, exit_code=0, message="ok", env={}, notes=[], profile=None)


class TestCodeDispatch:
    """`sb code [<model>]` routes to launch.run_code and exits with claude's code."""

    def test_routes_model_arg_and_exits_zero(self, monkeypatch):
        seen = {}
        def fake(arg=None, **kwargs):
            seen["arg"] = arg
            return _ok_launch()
        monkeypatch.setattr(launch, "run_code", fake)
        monkeypatch.setattr(sys, "argv", ["sb", "code", "deepseek/deepseek-chat"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert seen["arg"] == "deepseek/deepseek-chat"
        assert exc.value.code == 0

    def test_no_arg_passes_none(self, monkeypatch):
        seen = {}
        def fake(arg=None, **kwargs):
            seen["arg"] = arg
            return _ok_launch()
        monkeypatch.setattr(launch, "run_code", fake)
        monkeypatch.setattr(sys, "argv", ["sb", "code"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert seen["arg"] is None
        assert exc.value.code == 0

    def test_propagates_claude_exit_code(self, monkeypatch):
        monkeypatch.setattr(
            launch, "run_code",
            lambda arg=None, **k: LaunchResult(ok=True, exit_code=3, message="ok", env={}, notes=[], profile=None),
        )
        monkeypatch.setattr(sys, "argv", ["sb", "code"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 3

    def test_failure_exits_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr(
            launch, "run_code",
            lambda arg=None, **k: LaunchResult(ok=False, exit_code=None, message="no active profile -- run `sb setup` first", env={}, notes=[], profile=None),
        )
        monkeypatch.setattr(sys, "argv", ["sb", "code"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        assert "sb setup" in capsys.readouterr().out
