# test_checks_v3.py - Tests for the v3 doctor checks (SPEC-004 R7).
#
# Pure-function tests: plain blob dicts + catalog lists, no I/O.
# ---------------------------------------------------------------------------

from switchboard.catalog import Model
from switchboard.checks_v3 import run_checks_v3

CAT = [
    Model("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", 1048576, 9e-08, 0.0),
    Model("z-ai/glm-4.6", "GLM 4.6", 202752, 4e-07, 0.0),
]

APPLIED_OK = "openrouter/deepseek/deepseek-v4-flash"


def _by_name(checks):
    """Index check results by name for readable assertions."""
    return {c.name: c for c in checks}


class TestRunChecksV3AllPass:
    """The healthy-store scenario."""

    def test_all_checks_pass(self, v3_blob):
        checks = run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, [])
        assert all(c.ok for c in checks), [c for c in checks if not c.ok]

    def test_canonical_check_names_present(self, v3_blob):
        names = [c.name for c in run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, [])]
        for expected in [
            "CCR running", "OpenRouter catalog", "v3 store", "claude-code profile",
            "model", "smallFastModel", "whitelist", "applied model",
            "APIKEY blank", "legacy config", "web search",
        ]:
            assert expected in names

    def test_websearch_informational_off(self, v3_blob):
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["web search"]
        assert c.ok and c.detail == "off"


class TestStoreUnreadable:
    """Store errors degrade to one failing check, not a traceback."""

    def test_store_check_fails_with_detail(self):
        checks = run_checks_v3(None, "no 'default' row", CAT, True, None, [])
        store = _by_name(checks)["v3 store"]
        assert not store.ok and "no 'default' row" in store.detail

    def test_blob_derived_checks_skipped(self):
        names = [c.name for c in run_checks_v3(None, "boom", CAT, True, None, [])]
        assert "claude-code profile" not in names
        assert "whitelist" not in names
        # environment-level checks still run
        assert "CCR running" in names and "legacy config" in names


class TestProfileAndModelChecks:
    """Profile presence, leak, whitelist, and parity checks."""

    def test_missing_profile_fails(self, v3_blob):
        v3_blob["profile"]["profiles"] = []
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, None, []))["claude-code profile"]
        assert not c.ok

    def test_disabled_profile_fails(self, v3_blob):
        v3_blob["profile"]["profiles"][0]["enabled"] = False
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["claude-code profile"]
        assert not c.ok and "disabled" in c.detail

    def test_anthropic_model_flagged_as_leak(self, v3_blob):
        v3_blob["profile"]["profiles"][0]["model"] = "openrouter/anthropic/claude-sonnet-4"
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["model"]
        assert not c.ok and "Anthropic" in c.detail

    def test_small_fast_checked_separately(self, v3_blob):
        v3_blob["profile"]["profiles"][0]["smallFastModel"] = "openrouter/anthropic/claude-haiku"
        by = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))
        assert by["model"].ok and not by["smallFastModel"].ok

    def test_model_not_in_whitelist_fails(self, v3_blob):
        v3_blob["Providers"][0]["models"] = ["z-ai/glm-4.6"]
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["whitelist"]
        assert not c.ok and "gateway" in c.detail.lower()


class TestParityCheck:
    """applied model (settings.json) vs store profile model."""

    def test_matching_applied_passes(self, v3_blob):
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["applied model"]
        assert c.ok

    def test_drift_fails_and_mentions_new_session(self, v3_blob):
        c = _by_name(
            run_checks_v3(v3_blob, None, CAT, True, "openrouter/z-ai/glm-4.6", [])
        )["applied model"]
        assert not c.ok and "session" in c.detail.lower()

    def test_missing_applied_fails(self, v3_blob):
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, None, []))["applied model"]
        assert not c.ok


class TestApikeyAndLegacy:
    """APIKEY blank discipline + legacy hygiene."""

    def test_nonblank_apikey_fails(self, v3_blob):
        v3_blob["APIKEY"] = "x"
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["APIKEY blank"]
        assert not c.ok

    def test_legacy_file_presence_fails_with_rotation_hint(self, v3_blob):
        checks = run_checks_v3(
            v3_blob, None, CAT, True, APPLIED_OK, ["~/.claude-code-router/config.json"]
        )
        c = _by_name(checks)["legacy config"]
        assert not c.ok
        assert "rotate" in c.detail.lower()
        assert "config.json" in c.detail

    def test_legacy_absent_passes(self, v3_blob):
        c = _by_name(run_checks_v3(v3_blob, None, CAT, True, APPLIED_OK, []))["legacy config"]
        assert c.ok
