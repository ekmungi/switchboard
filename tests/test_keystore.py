# test_keystore.py - OpenRouter key sourced from ~/.env_claude (SPEC-005 R6).
#
# Hermetic: every test writes its own env file under tmp_path; a FAKE key value is
# used throughout. The real ~/.env_claude is never read and no secret is asserted.

import pytest

from switchboard import keystore
from switchboard.keystore import KeystoreError

FAKE = "sk-or-v1-FAKEKEY000"


class TestReadKey:
    """Tests for read_key(name, path, environ)."""

    def test_reads_plain_key_value(self, tmp_path):
        """The real ~/.env_claude shape: plain KEY=value, no export, no quotes."""
        env = tmp_path / ".env_claude"
        env.write_text(f"MD_VAULT=/x\nOPENROUTER_API_KEY={FAKE}\nOPENAI_API_KEY=other\n", encoding="utf-8")
        assert keystore.read_key("OPENROUTER_API_KEY", path=env, environ={}) == FAKE

    def test_handles_export_quotes_and_comments(self, tmp_path):
        """Tolerates `export`, surrounding quotes, blank lines, and # comments."""
        env = tmp_path / ".env_claude"
        env.write_text(
            "# a comment\n\nexport OPENROUTER_API_KEY=\"%s\"\n" % FAKE, encoding="utf-8"
        )
        assert keystore.read_key("OPENROUTER_API_KEY", path=env, environ={}) == FAKE

    def test_matches_exact_name_not_substring(self, tmp_path):
        """A different key that contains the name as a substring is not returned."""
        env = tmp_path / ".env_claude"
        env.write_text(f"NOT_OPENROUTER_API_KEY=wrong\nOPENROUTER_API_KEY={FAKE}\n", encoding="utf-8")
        assert keystore.read_key("OPENROUTER_API_KEY", path=env, environ={}) == FAKE

    def test_none_when_absent_everywhere(self, tmp_path):
        """Missing from both the file and the environ -> None (no crash)."""
        env = tmp_path / ".env_claude"
        env.write_text("OPENAI_API_KEY=other\n", encoding="utf-8")
        assert keystore.read_key("OPENROUTER_API_KEY", path=env, environ={}) is None

    def test_falls_back_to_environ_when_file_missing(self, tmp_path):
        """When the file does not exist, an exported OPENROUTER_API_KEY is used."""
        missing = tmp_path / "nope.env"
        assert keystore.read_key("OPENROUTER_API_KEY", path=missing, environ={"OPENROUTER_API_KEY": FAKE}) == FAKE

    def test_file_takes_precedence_over_environ(self, tmp_path):
        """The file is the source of truth (R6); it wins over a stale environ value."""
        env = tmp_path / ".env_claude"
        env.write_text(f"OPENROUTER_API_KEY={FAKE}\n", encoding="utf-8")
        assert keystore.read_key("OPENROUTER_API_KEY", path=env, environ={"OPENROUTER_API_KEY": "stale"}) == FAKE


class TestRequireKey:
    """Tests for require_key(name, path, environ)."""

    def test_returns_key_when_present(self, tmp_path):
        env = tmp_path / ".env_claude"
        env.write_text(f"OPENROUTER_API_KEY={FAKE}\n", encoding="utf-8")
        assert keystore.require_key("OPENROUTER_API_KEY", path=env, environ={}) == FAKE

    def test_raises_keystore_error_when_missing(self, tmp_path):
        """A missing key is a setup-blocking error, surfaced (not silently None)."""
        env = tmp_path / ".env_claude"
        env.write_text("", encoding="utf-8")
        with pytest.raises(KeystoreError):
            keystore.require_key("OPENROUTER_API_KEY", path=env, environ={})


class TestEnvFilePath:
    """Tests for env_file_path()."""

    def test_defaults_to_home_env_claude(self):
        from pathlib import Path
        assert keystore.env_file_path() == Path.home() / ".env_claude"
