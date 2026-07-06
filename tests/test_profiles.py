# test_profiles.py - Tier-map profile storage + engine wiring (SPEC-005 R3/R3a).
#
# A profile is the tier map: main + small/fast -> OpenRouter model ids, plus a
# concrete cheap catch-all. Hermetic: all storage under tmp_path.

import pytest

from switchboard import profiles
from switchboard.profiles import Profile, ProfileError
from switchboard.translator_engine import LiteLLMEngine


class TestDefaultProfile:
    """Tests for default_profile()."""

    def test_catch_all_defaults_to_small_fast(self):
        """The catch-all defaults to the cheapest tier (small/fast) when unset."""
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
        assert p.catch_all == "deepseek/deepseek-chat"
        assert p.main == "z-ai/glm-4.6" and p.port == 4000 and p.name == "default"

    def test_explicit_catch_all_kept(self):
        p = profiles.default_profile("z-ai/glm-4.6", "z-ai/glm-4.6", catch_all="deepseek/deepseek-chat")
        assert p.catch_all == "deepseek/deepseek-chat"


class TestTierMap:
    """Tests for tier_map() and its wiring into the engine config generator."""

    def test_maps_main_and_small_fast_explicitly(self):
        """Both tiers appear as explicit entries (no passthrough)."""
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
        tm = profiles.tier_map(p)
        assert tm == {"z-ai/glm-4.6": "z-ai/glm-4.6", "deepseek/deepseek-chat": "deepseek/deepseek-chat"}

    def test_generates_valid_engine_config(self, tmp_path):
        """The profile's tier map + catch-all produce a cost-safe engine config."""
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
        cfg = LiteLLMEngine(engine_dir=tmp_path).generate_config(profiles.tier_map(p), p.catch_all)
        assert "model: openrouter/z-ai/glm-4.6" in cfg
        assert 'model_name: "*"' in cfg
        assert "openrouter/*" not in cfg


class TestModelEnv:
    """Tests for model_env()."""

    def test_sets_both_anthropic_model_vars(self):
        """sb code uses this to steer which strings Claude Code emits per tier."""
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
        assert profiles.model_env(p) == {
            "ANTHROPIC_MODEL": "z-ai/glm-4.6",
            "ANTHROPIC_SMALL_FAST_MODEL": "deepseek/deepseek-chat",
        }


class TestUnsafeTiers:
    """Tests for unsafe_tiers() - the R5a audit doctor reuses."""

    def test_empty_for_safe_profile(self):
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
        assert profiles.unsafe_tiers(p) == []

    def test_flags_anthropic_main(self):
        p = Profile(name="x", main="anthropic/claude-3-5-sonnet", small_fast="deepseek/deepseek-chat", catch_all="deepseek/deepseek-chat")
        flagged = profiles.unsafe_tiers(p)
        assert any(label == "main" for label, _ in flagged)

    def test_flags_passthrough_catch_all(self):
        p = Profile(name="x", main="z-ai/glm-4.6", small_fast="z-ai/glm-4.6", catch_all="openrouter/*")
        assert any(label == "catch_all" for label, _ in profiles.unsafe_tiers(p))


class TestSaveLoad:
    """Tests for save() / load()."""

    def test_roundtrips_a_profile(self, tmp_path):
        path = tmp_path / "profile.json"
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat", port=4100)
        profiles.save(p, path)
        assert profiles.load(path) == p

    def test_save_refuses_unsafe_profile(self, tmp_path):
        """R3a defense in depth: an unsafe profile is never persisted."""
        path = tmp_path / "profile.json"
        bad = Profile(name="x", main="anthropic/claude-3-haiku", small_fast="deepseek/deepseek-chat", catch_all="deepseek/deepseek-chat")
        with pytest.raises(ProfileError):
            profiles.save(bad, path)
        assert not path.exists()

    def test_load_none_when_absent(self, tmp_path):
        assert profiles.load(tmp_path / "nope.json") is None

    def test_load_raises_on_corrupt_json(self, tmp_path):
        path = tmp_path / "profile.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ProfileError):
            profiles.load(path)
