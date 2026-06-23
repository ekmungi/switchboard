# test_ccr_config_io.py - Tests for read_config, write_config, ccr_running, restart_ccr.
#
# All tests are hermetic -- no real file I/O beyond tmp_path, no real CCR process.
# ---------------------------------------------------------------------------

import json
import socket
from unittest.mock import MagicMock

from switchboard import ccr_config


# ---------------------------------------------------------------------------
# read_config
# ---------------------------------------------------------------------------


class TestReadConfig:
    """Tests for read_config()."""

    def test_returns_empty_dict_when_file_missing(self, tmp_path, monkeypatch):
        """Returns {} when CONFIG_PATH does not exist."""
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", tmp_path / "config.json")
        assert ccr_config.read_config() == {}

    def test_parses_json_when_file_present(self, tmp_path, monkeypatch):
        """Reads and parses a valid JSON config file."""
        config_file = tmp_path / "config.json"
        payload = {"HOST": "127.0.0.1", "PORT": 3456, "Router": {"default": "openrouter,model"}}
        config_file.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", config_file)
        result = ccr_config.read_config()
        assert result == payload

    def test_reads_utf8_encoding(self, tmp_path, monkeypatch):
        """Handles UTF-8 encoded files correctly."""
        config_file = tmp_path / "config.json"
        payload = {"note": "café"}
        config_file.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", config_file)
        assert ccr_config.read_config()["note"] == "café"


# ---------------------------------------------------------------------------
# write_config
# ---------------------------------------------------------------------------


class TestWriteConfig:
    """Tests for write_config()."""

    def test_writes_pretty_json(self, tmp_path, monkeypatch):
        """Writes 2-space-indented JSON to CONFIG_PATH."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", config_file)
        payload = {"HOST": "127.0.0.1", "PORT": 3456}
        ccr_config.write_config(payload)
        raw = config_file.read_text(encoding="utf-8")
        assert json.loads(raw) == payload
        assert '  "PORT"' in raw

    def test_round_trips_via_read_config(self, tmp_path, monkeypatch):
        """write_config then read_config round-trips the dict exactly."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", config_file)
        payload = {"HOST": "127.0.0.1", "PORT": 3456, "Router": {"default": "openrouter,model"}}
        ccr_config.write_config(payload)
        assert ccr_config.read_config() == payload


# ---------------------------------------------------------------------------
# ccr_running
# ---------------------------------------------------------------------------


class TestCcrRunning:
    """Tests for ccr_running()."""

    def test_returns_true_when_connection_succeeds(self, tmp_path, monkeypatch):
        """Returns True when create_connection does not raise.

        Uses a MagicMock return value so the ``with`` statement's
        __enter__/__exit__ protocol is satisfied without touching the network.
        CONFIG_PATH is redirected to a non-existent temp path so read_config()
        returns {} (defaults) and no real config file is read.
        """
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: MagicMock())
        assert ccr_config.ccr_running() is True

    def test_returns_false_when_oserror(self, tmp_path, monkeypatch):
        """Returns False when create_connection raises OSError.

        CONFIG_PATH is redirected to a non-existent temp path so read_config()
        returns {} (defaults) and no real config file is read.
        """
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", tmp_path / "config.json")
        def _fail(addr, timeout):
            raise OSError("connection refused")
        monkeypatch.setattr(socket, "create_connection", _fail)
        assert ccr_config.ccr_running() is False

    def test_uses_host_port_from_config(self, tmp_path, monkeypatch):
        """Passes the HOST/PORT from config to create_connection."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"HOST": "10.0.0.1", "PORT": 9999}), encoding="utf-8")
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", config_file)
        captured = {}
        def _capture(addr, timeout):
            captured["addr"] = addr
            return MagicMock()
        monkeypatch.setattr(socket, "create_connection", _capture)
        ccr_config.ccr_running()
        assert captured["addr"] == ("10.0.0.1", 9999)

    def test_uses_defaults_when_config_missing(self, tmp_path, monkeypatch):
        """Falls back to 127.0.0.1:3456 when config has no HOST/PORT."""
        monkeypatch.setattr(ccr_config, "CONFIG_PATH", tmp_path / "config.json")
        captured = {}
        def _capture(addr, timeout):
            captured["addr"] = addr
            return MagicMock()
        monkeypatch.setattr(socket, "create_connection", _capture)
        ccr_config.ccr_running()
        assert captured["addr"] == ("127.0.0.1", 3456)


# ---------------------------------------------------------------------------
# restart_ccr
# ---------------------------------------------------------------------------


class TestRestartCcr:
    """Tests for restart_ccr()."""

    def test_windows_cmd_vector(self, monkeypatch):
        """On Windows (os.name == 'nt'), calls cmd /c ccr restart."""
        captured = {}
        monkeypatch.setattr(ccr_config.os, "name", "nt")
        monkeypatch.setattr(ccr_config.subprocess, "run",
                            lambda args, check: captured.update({"args": args, "check": check}))
        ccr_config.restart_ccr()
        assert captured["args"] == ["cmd", "/c", "ccr", "restart"]
        assert captured["check"] is False

    def test_posix_cmd_vector(self, monkeypatch):
        """On POSIX (os.name != 'nt'), calls ccr restart directly."""
        captured = {}
        monkeypatch.setattr(ccr_config.os, "name", "posix")
        monkeypatch.setattr(ccr_config.subprocess, "run",
                            lambda args, check: captured.update({"args": args, "check": check}))
        ccr_config.restart_ccr()
        assert captured["args"] == ["ccr", "restart"]
        assert captured["check"] is False

    def test_no_shell_true(self, monkeypatch):
        """subprocess.run is called without shell=True (keyword not passed)."""
        calls = []
        monkeypatch.setattr(ccr_config.os, "name", "nt")
        monkeypatch.setattr(ccr_config.subprocess, "run",
                            lambda args, check: calls.append({"args": args, "check": check}))
        ccr_config.restart_ccr()
        assert len(calls) == 1
