# test_ccr_v3.py - Tests for the pure CCR v3 blob accessors/updaters (SPEC-004 R2-R5).
#
# Pure-function tests over the sanitized conftest blob: no I/O, no store.
# ---------------------------------------------------------------------------

import pytest

from switchboard import ccr_v3


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


class TestClaudeProfile:
    """Tests for claude_profile()."""

    def test_finds_claude_code_profile(self, v3_blob):
        """Returns the profiles[] entry whose agent is claude-code."""
        prof = ccr_v3.claude_profile(v3_blob)
        assert prof["id"] == "default-claude-code"

    def test_returns_none_when_absent(self):
        """Returns None when no claude-code profile exists."""
        assert ccr_v3.claude_profile({"profile": {"profiles": []}}) is None
        assert ccr_v3.claude_profile({}) is None


class TestStoreModelId:
    """Tests for store_model_id() / small_fast_id()."""

    def test_strips_provider_prefix(self, v3_blob):
        """'openrouter/deepseek/x' -> 'deepseek/x' (bare OpenRouter id)."""
        assert ccr_v3.store_model_id(v3_blob) == "deepseek/deepseek-v4-flash"

    def test_strips_online_suffix(self, v3_blob):
        """A ':online' suffix is not part of the bare id."""
        ccr_v3.claude_profile(v3_blob)["model"] += ":online"
        assert ccr_v3.store_model_id(v3_blob) == "deepseek/deepseek-v4-flash"

    def test_none_when_no_profile(self):
        """Returns None when there is no claude-code profile."""
        assert ccr_v3.store_model_id({}) is None

    def test_small_fast_id(self, v3_blob):
        """small_fast_id strips the same way from smallFastModel."""
        assert ccr_v3.small_fast_id(v3_blob) == "deepseek/deepseek-v4-flash"


class TestWebsearchOnline:
    """Tests for websearch_online_v3()."""

    def test_false_without_suffix(self, v3_blob):
        assert ccr_v3.websearch_online_v3(v3_blob) is False

    def test_true_with_suffix(self, v3_blob):
        ccr_v3.claude_profile(v3_blob)["model"] += ":online"
        assert ccr_v3.websearch_online_v3(v3_blob) is True

    def test_true_when_only_small_fast_has_suffix(self, v3_blob):
        """A stray ':online' on smallFastModel alone still counts as ON."""
        ccr_v3.claude_profile(v3_blob)["smallFastModel"] += ":online"
        assert ccr_v3.websearch_online_v3(v3_blob) is True


class TestRouterSummary:
    """Tests for router_summary()."""

    def test_summarizes_builtins_rules_fallback(self, v3_blob):
        s = ccr_v3.router_summary(v3_blob)
        assert s == {"builtin": ["claude-code", "codex"], "rules": 0, "fallback": "off"}

    def test_degrades_on_missing_router(self):
        s = ccr_v3.router_summary({})
        assert s == {"builtin": [], "rules": 0, "fallback": "off"}


class TestAppliedModel:
    """Tests for applied_model() over a settings.json dict."""

    def test_reads_env_anthropic_model(self):
        settings = {"env": {"ANTHROPIC_MODEL": "openrouter/deepseek/deepseek-v4-flash"}}
        assert ccr_v3.applied_model(settings) == "openrouter/deepseek/deepseek-v4-flash"

    def test_none_when_absent(self):
        assert ccr_v3.applied_model({}) is None
        assert ccr_v3.applied_model({"env": {}}) is None


# ---------------------------------------------------------------------------
# Updaters (immutable)
# ---------------------------------------------------------------------------


class TestSetProfileModel:
    """Tests for set_profile_model()."""

    def test_sets_model_and_small_fast(self, v3_blob):
        """Both model and smallFastModel get '<provider>/<id>' (no leak)."""
        new = ccr_v3.set_profile_model(v3_blob, "z-ai/glm-4.6")
        prof = ccr_v3.claude_profile(new)
        assert prof["model"] == "openrouter/z-ai/glm-4.6"
        assert prof["smallFastModel"] == "openrouter/z-ai/glm-4.6"

    def test_does_not_mutate_input(self, v3_blob):
        """The original blob is untouched (immutability contract)."""
        ccr_v3.set_profile_model(v3_blob, "z-ai/glm-4.6")
        assert ccr_v3.claude_profile(v3_blob)["model"] == "openrouter/deepseek/deepseek-v4-flash"

    def test_other_profiles_and_keys_preserved(self, v3_blob):
        """The codex profile and unknown keys ride along verbatim."""
        new = ccr_v3.set_profile_model(v3_blob, "z-ai/glm-4.6")
        assert new["profile"]["profiles"][1] == v3_blob["profile"]["profiles"][1]
        assert new["someUnknownKey"] == v3_blob["someUnknownKey"]

    def test_raises_without_claude_profile(self):
        """No claude-code profile -> ValueError (nothing to pin)."""
        with pytest.raises(ValueError):
            ccr_v3.set_profile_model({"profile": {"profiles": []}}, "m/x")


class TestEnsureWhitelisted:
    """Tests for ensure_whitelisted()."""

    def test_appends_missing_model(self, v3_blob):
        new, changed = ccr_v3.ensure_whitelisted(v3_blob, "openai/gpt-4o-mini")
        assert changed is True
        assert "openai/gpt-4o-mini" in new["Providers"][0]["models"]
        # input untouched
        assert "openai/gpt-4o-mini" not in v3_blob["Providers"][0]["models"]

    def test_noop_when_present(self, v3_blob):
        new, changed = ccr_v3.ensure_whitelisted(v3_blob, "z-ai/glm-4.6")
        assert changed is False
        assert new["Providers"][0]["models"] == v3_blob["Providers"][0]["models"]

    def test_preserves_api_key_verbatim(self, v3_blob):
        new, _ = ccr_v3.ensure_whitelisted(v3_blob, "openai/gpt-4o-mini")
        assert new["Providers"][0]["api_key"] == v3_blob["Providers"][0]["api_key"]

    def test_raises_without_matching_provider(self, v3_blob):
        """preferredProvider names a provider that does not exist -> ValueError."""
        broken = {**v3_blob, "preferredProvider": "nope"}
        with pytest.raises(ValueError):
            ccr_v3.ensure_whitelisted(broken, "m/x")


class TestProviderModels:
    """Tests for provider_models()."""

    def test_returns_whitelist_copy(self, v3_blob):
        models = ccr_v3.provider_models(v3_blob)
        assert models == ["deepseek/deepseek-v4-flash", "z-ai/glm-4.6"]
        models.append("mutated")  # a copy: the blob must not change
        assert "mutated" not in v3_blob["Providers"][0]["models"]

    def test_none_when_provider_missing(self, v3_blob):
        assert ccr_v3.provider_models({**v3_blob, "preferredProvider": "nope"}) is None


class TestSetApikeyBlank:
    """Tests for set_apikey_blank()."""

    def test_forces_blank(self, v3_blob):
        dirty = {**v3_blob, "APIKEY": "something"}
        assert ccr_v3.set_apikey_blank(dirty)["APIKEY"] == ""

    def test_does_not_mutate_input(self, v3_blob):
        dirty = {**v3_blob, "APIKEY": "something"}
        ccr_v3.set_apikey_blank(dirty)
        assert dirty["APIKEY"] == "something"


class TestStripOnline:
    """Tests for strip_online()."""

    def test_strips_suffix_from_both_fields(self, v3_blob):
        prof = ccr_v3.claude_profile(v3_blob)
        prof["model"] += ":online"
        prof["smallFastModel"] += ":online"
        new, changed = ccr_v3.strip_online(v3_blob)
        assert changed is True
        assert ccr_v3.claude_profile(new)["model"] == "openrouter/deepseek/deepseek-v4-flash"
        assert ccr_v3.claude_profile(new)["smallFastModel"] == "openrouter/deepseek/deepseek-v4-flash"

    def test_noop_when_absent(self, v3_blob):
        new, changed = ccr_v3.strip_online(v3_blob)
        assert changed is False
        assert ccr_v3.claude_profile(new)["model"] == ccr_v3.claude_profile(v3_blob)["model"]

    def test_noop_without_profile(self):
        new, changed = ccr_v3.strip_online({})
        assert changed is False
