# test_claude_scopes.py - Tests for the Claude config-surface readers and audit helpers.
#
# All tests are hermetic: file reads go through tmp_path, no real config touched.
# ---------------------------------------------------------------------------

import json

from switchboard import claude_scopes


# ---------------------------------------------------------------------------
# load_json
# ---------------------------------------------------------------------------


class TestLoadJson:
    """Tests for load_json()."""

    def test_returns_data_and_no_error_for_valid_file(self, tmp_path):
        """Parses a valid JSON file and returns (data, None)."""
        p = tmp_path / "x.json"
        p.write_text(json.dumps({"a": 1}), encoding="utf-8")
        data, err = claude_scopes.load_json(p)
        assert data == {"a": 1}
        assert err is None

    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        """Missing file is not an error: returns ({}, None)."""
        data, err = claude_scopes.load_json(tmp_path / "missing.json")
        assert data == {}
        assert err is None

    def test_returns_error_string_for_malformed_json(self, tmp_path):
        """Malformed JSON returns ({}, <error string>) instead of raising."""
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        data, err = claude_scopes.load_json(p)
        assert data == {}
        assert err is not None and "bad.json" in err


# ---------------------------------------------------------------------------
# mcp_servers
# ---------------------------------------------------------------------------


class TestMcpServers:
    """Tests for mcp_servers()."""

    def test_extracts_top_level_mcp_servers(self):
        """Returns the mcpServers object from a state dict."""
        state = {"mcpServers": {"a": {"command": "x"}}, "other": 1}
        assert claude_scopes.mcp_servers(state) == {"a": {"command": "x"}}

    def test_returns_empty_dict_when_key_absent(self):
        """A state file with no mcpServers key yields {}."""
        assert claude_scopes.mcp_servers({"projects": {}}) == {}

    def test_returns_empty_dict_for_non_dict_value(self):
        """A malformed (non-dict) mcpServers value yields {} rather than crashing."""
        assert claude_scopes.mcp_servers({"mcpServers": ["broken"]}) == {}


# ---------------------------------------------------------------------------
# Surface audit helpers (pure: dicts in, strings/None out)
# ---------------------------------------------------------------------------


class TestSettingsWarns:
    """Tests for settings_warns()."""

    def test_flags_ccr_managed_env_block_and_apikey_helper(self):
        """Detects CCR base-URL env vars and apiKeyHelper as WARN strings."""
        settings = {
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3456"},
            "apiKeyHelper": r"C:\x\ccr-key.cmd",
        }
        warns = claude_scopes.settings_warns(settings)
        assert len(warns) == 2
        assert any("ANTHROPIC_BASE_URL" in w for w in warns)
        assert any("apiKeyHelper" in w for w in warns)

    def test_clean_settings_produce_no_warns(self):
        """Settings without CCR markers yield an empty list."""
        assert claude_scopes.settings_warns({"env": {"FOO": "1"}}) == []


class TestLegacyCcrWarn:
    """Tests for legacy_ccr_warn()."""

    def test_warns_when_legacy_config_present_with_key(self):
        """A legacy config containing a Providers api_key mentions rotation."""
        legacy = {"Providers": [{"api_key": "sk-or-v1-xyz"}]}
        warn = claude_scopes.legacy_ccr_warn(legacy)
        assert warn is not None
        assert "inert" in warn.lower()
        assert "rotate" in warn.lower()
        # The key value itself must never leak into the message.
        assert "sk-or-v1-xyz" not in warn

    def test_warns_without_rotation_when_no_key(self):
        """A keyless legacy config still warns (inert file) but not about rotation."""
        warn = claude_scopes.legacy_ccr_warn({"Router": {}})
        assert warn is not None and "inert" in warn.lower()
        assert "rotate" not in warn.lower()

    def test_none_when_legacy_config_absent(self):
        """No legacy file (empty dict) means no warning."""
        assert claude_scopes.legacy_ccr_warn({}) is None


class TestConnectorsInfo:
    """Tests for connectors_info()."""

    def test_reports_not_portable_when_no_oauth_in_target(self):
        """Target scope without oauthAccount gets the not-portable INFO."""
        info = claude_scopes.connectors_info({"projects": {}})
        assert info is not None and "not portable" in info.lower()

    def test_none_when_target_has_oauth(self):
        """Target scope with an account link needs no connector INFO."""
        assert claude_scopes.connectors_info({"oauthAccount": {"id": "x"}}) is None


class TestPluginsInfo:
    """Tests for plugins_info()."""

    def test_counts_enabled_plugins(self):
        """Reports how many plugins pass through natively."""
        settings = {"enabledPlugins": {"a@m": True, "b@m": True}}
        info = claude_scopes.plugins_info(settings)
        assert "2" in info

    def test_zero_when_no_plugins_key(self):
        """Missing enabledPlugins reports zero."""
        assert "0" in claude_scopes.plugins_info({})
