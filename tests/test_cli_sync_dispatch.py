# test_cli_sync_dispatch.py - Dispatch test: `switchboard sync ...` routes to cmd_sync.
# ---------------------------------------------------------------------------

import sys

from switchboard import cli


class TestSyncDispatch:
    """main() routes the sync subcommand with its remaining args."""

    def test_sync_routes_with_args(self, monkeypatch):
        """`switchboard sync --apply` calls cmd_sync(['--apply'])."""
        got = {}
        monkeypatch.setattr(cli, "cmd_sync", lambda argv: got.update({"argv": argv}))
        monkeypatch.setattr(sys, "argv", ["switchboard", "sync", "--apply"])
        cli.main()
        assert got["argv"] == ["--apply"]

    def test_sync_routes_with_no_args(self, monkeypatch):
        """Bare `switchboard sync` calls cmd_sync([])."""
        got = {}
        monkeypatch.setattr(cli, "cmd_sync", lambda argv: got.update({"argv": argv}))
        monkeypatch.setattr(sys, "argv", ["switchboard", "sync"])
        cli.main()
        assert got["argv"] == []
