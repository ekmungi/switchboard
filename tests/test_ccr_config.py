# tests/test_ccr_config.py - tests for the switchboard.ccr_config module.
#
# TDD: tests are written before the implementation. Run `uv run pytest` to verify.
# All tests are hermetic -- no real file I/O, no real CCR process, no real network.
# ---------------------------------------------------------------------------

import json
import os
import socket
from unittest.mock import MagicMock

import pytest

from switchboard import ccr_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_with_router(**extra_router_keys) -> dict:
    """Return a minimal cfg dict with a Router section plus optional extra keys."""
    router = {
        "default": "openrouter,deepseek/deepseek-chat",
        "background": "openrouter,deepseek/deepseek-chat",
        "think": "openrouter,deepseek/deepseek-r1",
        "longContext": "openrouter,deepseek/deepseek-chat",
        "webSearch": "openrouter,deepseek/deepseek-chat",
        "longContextThreshold": 200000,
        "image": "",
    }
    router.update(extra_router_keys)
    return {
        "LOG": False,
        "HOST": "127.0.0.1",
        "PORT": 3456,
        "APIKEY": "old-key",
        "Providers": [{"name": "openrouter", "api_key": "SECRET"}],
        "Router": router,
    }


# ---------------------------------------------------------------------------
# set_all_roles
# ---------------------------------------------------------------------------


class TestSetAllRoles:
    """Tests for set_all_roles()."""

    MODEL = "anthropic/claude-3-5-sonnet"

    def test_sets_all_five_roles(self):
        """Every role in ROLES is set to openrouter,<model>."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        for role in ccr_config.ROLES:
            assert result["Router"][role] == f"openrouter,{self.MODEL}"

    def test_websearch_no_online_when_online_false(self):
        """With online=False, webSearch must NOT end with ':online'."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL, online=False)
        assert result["Router"]["webSearch"] == f"openrouter,{self.MODEL}"
        assert not result["Router"]["webSearch"].endswith(":online")

    def test_websearch_online_suffix_when_online_true(self):
        """With online=True, webSearch must end with ':online'."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL, online=True)
        assert result["Router"]["webSearch"] == f"openrouter,{self.MODEL}:online"

    def test_other_roles_not_online_when_online_true(self):
        """With online=True, only webSearch gets ':online'; all other roles do not."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL, online=True)
        for role in ccr_config.ROLES:
            if role == "webSearch":
                continue
            assert not result["Router"][role].endswith(":online"), (
                f"Role '{role}' should not end with ':online'"
            )

    def test_preserves_longcontext_threshold(self):
        """longContextThreshold in Router must survive the update."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["Router"]["longContextThreshold"] == 200000

    def test_preserves_image_key(self):
        """image key in Router must survive the update."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["Router"]["image"] == ""

    def test_preserves_arbitrary_router_key(self):
        """Unrecognised Router keys are left intact."""
        cfg = _cfg_with_router(customKey="custom-value")
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["Router"]["customKey"] == "custom-value"

    def test_does_not_mutate_input(self):
        """Input cfg must not be modified in place."""
        cfg = _cfg_with_router()
        original_router = dict(cfg["Router"])
        ccr_config.set_all_roles(cfg, self.MODEL)
        assert cfg["Router"] == original_router

    def test_does_not_touch_top_level_keys(self):
        """Top-level keys (LOG, HOST, PORT, APIKEY, Providers) are untouched."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["LOG"] == cfg["LOG"]
        assert result["HOST"] == cfg["HOST"]
        assert result["PORT"] == cfg["PORT"]
        assert result["APIKEY"] == cfg["APIKEY"]
        # Providers reference must not be changed (we do not even inspect it)
        assert result["Providers"] is cfg["Providers"]


# ---------------------------------------------------------------------------
# set_websearch_online
# ---------------------------------------------------------------------------


class TestSetWebsearchOnline:
    """Tests for set_websearch_online()."""

    BASE_VALUE = "openrouter,deepseek/deepseek-chat"

    def _cfg(self) -> dict:
        """Return cfg with a plain webSearch (no :online)."""
        cfg = _cfg_with_router()
        cfg["Router"]["webSearch"] = self.BASE_VALUE
        return cfg

    def test_adds_online_suffix_when_true(self):
        """on=True appends ':online' to the existing webSearch value."""
        cfg = self._cfg()
        result = ccr_config.set_websearch_online(cfg, on=True)
        assert result["Router"]["webSearch"] == f"{self.BASE_VALUE}:online"

    def test_removes_online_suffix_when_false(self):
        """on=False strips ':online' from the webSearch value."""
        cfg = _cfg_with_router()
        cfg["Router"]["webSearch"] = f"{self.BASE_VALUE}:online"
        result = ccr_config.set_websearch_online(cfg, on=False)
        assert result["Router"]["webSearch"] == self.BASE_VALUE

    def test_round_trips(self):
        """on=True then on=False returns to the original base value."""
        cfg = self._cfg()
        enabled = ccr_config.set_websearch_online(cfg, on=True)
        restored = ccr_config.set_websearch_online(enabled, on=False)
        assert restored["Router"]["webSearch"] == self.BASE_VALUE

    def test_idempotent_true(self):
        """Calling on=True twice does not double-append ':online'."""
        cfg = self._cfg()
        once = ccr_config.set_websearch_online(cfg, on=True)
        twice = ccr_config.set_websearch_online(once, on=True)
        assert twice["Router"]["webSearch"] == f"{self.BASE_VALUE}:online"

    def test_idempotent_false(self):
        """Calling on=False when already plain does not corrupt the value."""
        cfg = self._cfg()
        result = ccr_config.set_websearch_online(cfg, on=False)
        assert result["Router"]["webSearch"] == self.BASE_VALUE

    def test_does_not_mutate_input(self):
        """Input cfg must not be modified in place."""
        cfg = self._cfg()
        original_ws = cfg["Router"]["webSearch"]
        ccr_config.set_websearch_online(cfg, on=True)
        assert cfg["Router"]["webSearch"] == original_ws

    def test_preserves_other_router_keys(self):
        """Other Router keys (longContextThreshold, etc.) are untouched."""
        cfg = self._cfg()
        result = ccr_config.set_websearch_online(cfg, on=True)
        assert result["Router"]["longContextThreshold"] == 200000


# ---------------------------------------------------------------------------
# ensure_apikey_blank
# ---------------------------------------------------------------------------


class TestEnsureApikeyBlank:
    """Tests for ensure_apikey_blank()."""

    def test_sets_apikey_to_empty_string(self):
        """APIKEY must be set to '' regardless of its previous value."""
        cfg = _cfg_with_router()
        cfg["APIKEY"] = "some-old-key"
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["APIKEY"] == ""

    def test_already_blank_stays_blank(self):
        """If APIKEY is already blank, result must still be ''."""
        cfg = _cfg_with_router()
        cfg["APIKEY"] = ""
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["APIKEY"] == ""

    def test_leaves_providers_untouched(self):
        """Providers list must not be modified (secret api_key inside)."""
        cfg = _cfg_with_router()
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["Providers"] is cfg["Providers"]

    def test_leaves_other_keys_untouched(self):
        """Non-APIKEY top-level keys must survive."""
        cfg = _cfg_with_router()
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["HOST"] == cfg["HOST"]
        assert result["PORT"] == cfg["PORT"]
        assert result["Router"] == cfg["Router"]

    def test_does_not_mutate_input(self):
        """Input cfg must not be modified in place."""
        cfg = _cfg_with_router()
        cfg["APIKEY"] = "secret"
        ccr_config.ensure_apikey_blank(cfg)
        assert cfg["APIKEY"] == "secret"


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
        # Must be parseable and equal
        assert json.loads(raw) == payload
        # Must use 2-space indent
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
        # If shell=True were passed as keyword it would raise TypeError since our mock
        # does not accept it -- this test confirms it was NOT passed.
        assert len(calls) == 1
