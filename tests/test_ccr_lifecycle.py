# test_ccr_lifecycle.py - Tests for v3 daemon probing + gateway reload (SPEC-004 R6/R9).
#
# Hermetic: socket monkeypatched, subprocess runner injected, tmp_path service.json.
# ---------------------------------------------------------------------------

import socket
from unittest.mock import MagicMock

from switchboard import ccr_lifecycle


# ---------------------------------------------------------------------------
# ccr_running
# ---------------------------------------------------------------------------


class TestCcrRunning:
    """Tests for ccr_running(host, port)."""

    def test_true_when_connection_succeeds(self, monkeypatch):
        """Returns True when the TCP probe connects."""
        monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: MagicMock())
        assert ccr_lifecycle.ccr_running("127.0.0.1", 3456) is True

    def test_false_on_oserror(self, monkeypatch):
        """Returns False when the probe raises OSError."""
        def _fail(addr, timeout):
            raise OSError("refused")
        monkeypatch.setattr(socket, "create_connection", _fail)
        assert ccr_lifecycle.ccr_running("127.0.0.1", 3456) is False

    def test_probes_given_host_port(self, monkeypatch):
        """The provided host/port reach the socket call unchanged."""
        captured = {}
        def _capture(addr, timeout):
            captured["addr"] = addr
            return MagicMock()
        monkeypatch.setattr(socket, "create_connection", _capture)
        ccr_lifecycle.ccr_running("10.0.0.9", 4242)
        assert captured["addr"] == ("10.0.0.9", 4242)


# ---------------------------------------------------------------------------
# service_owned
# ---------------------------------------------------------------------------


class TestServiceOwned:
    """Tests for service_owned()."""

    def test_true_when_service_json_exists(self, tmp_path, monkeypatch):
        """A CONFIGDIR service.json means a `ccr start`-managed daemon."""
        svc = tmp_path / "service.json"
        svc.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ccr_lifecycle, "SERVICE_PATH", svc)
        assert ccr_lifecycle.service_owned() is True

    def test_false_when_absent(self, tmp_path, monkeypatch):
        """No service.json: daemon is Electron-app-owned or not running."""
        monkeypatch.setattr(ccr_lifecycle, "SERVICE_PATH", tmp_path / "service.json")
        assert ccr_lifecycle.service_owned() is False


# ---------------------------------------------------------------------------
# reload_gateway
# ---------------------------------------------------------------------------


class TestReloadGateway:
    """Tests for reload_gateway()."""

    def test_service_owned_runs_stop_then_start_windows(self, tmp_path, monkeypatch):
        """Windows: `cmd /c ccr stop` then `cmd /c ccr start`, check=False."""
        svc = tmp_path / "service.json"
        svc.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ccr_lifecycle, "SERVICE_PATH", svc)
        calls = []
        runner = lambda args, check: calls.append((args, check))
        lines = ccr_lifecycle.reload_gateway(run=runner, platform_name="nt")
        assert calls == [
            (["cmd", "/c", "ccr", "stop"], False),
            (["cmd", "/c", "ccr", "start"], False),
        ]
        assert any("reload" in line.lower() for line in lines)

    def test_service_owned_posix_vector(self, tmp_path, monkeypatch):
        """POSIX: bare `ccr stop` / `ccr start`."""
        svc = tmp_path / "service.json"
        svc.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ccr_lifecycle, "SERVICE_PATH", svc)
        calls = []
        runner = lambda args, check: calls.append(args)
        ccr_lifecycle.reload_gateway(run=runner, platform_name="posix")
        assert calls == [["ccr", "stop"], ["ccr", "start"]]

    def test_app_owned_instructs_instead_of_running(self, tmp_path, monkeypatch):
        """No service.json: nothing is executed; user gets the app-restart line."""
        monkeypatch.setattr(ccr_lifecycle, "SERVICE_PATH", tmp_path / "service.json")
        calls = []
        runner = lambda args, check: calls.append(args)
        lines = ccr_lifecycle.reload_gateway(run=runner, platform_name="nt")
        assert calls == []
        assert any("restart the Claude Code Router app" in line for line in lines)


# ---------------------------------------------------------------------------
# app_advisory
# ---------------------------------------------------------------------------


class TestAppAdvisory:
    """Tests for app_advisory()."""

    def test_advisory_when_daemon_up(self):
        """A reachable daemon during a write yields the UI-clobber advisory."""
        line = ccr_lifecycle.app_advisory(True)
        assert line is not None and "UI" in line

    def test_none_when_daemon_down(self):
        assert ccr_lifecycle.app_advisory(False) is None
