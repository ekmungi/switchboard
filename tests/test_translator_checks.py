# test_translator_checks.py - `sb doctor` for the clean translator (SPEC-005 R5/R5a).
#
# Hermetic: pure checks take resolved values; gather_checks takes injected probes;
# settings.json read from tmp_path. No proxy, no subprocess, no network.

from switchboard import translator_checks as tc
from switchboard.translator_engine import PIN
from switchboard.verify import GateResult
from switchboard import profiles

SAFE = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
GATE_OK = GateResult(ok=True, non_streaming=True, streaming=True, detail="ok")


def _names(checks):
    return {c.name: c for c in checks}


class TestRunTranslatorChecks:
    """Tests for the pure check builder."""

    def test_all_green_when_healthy(self):
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=True, profile=SAFE, settings_polluted=False, gate=GATE_OK
        )
        assert all(c.ok for c in checks)
        names = _names(checks)
        assert "engine pinned" in names and "tool-use gate" in names

    def test_flags_wrong_engine_version(self):
        checks = tc.run_translator_checks(
            installed_version="1.99.0", proxy_up=True, profile=SAFE, settings_polluted=False, gate=GATE_OK
        )
        assert _names(checks)["engine pinned"].ok is False

    def test_flags_missing_engine(self):
        checks = tc.run_translator_checks(
            installed_version=None, proxy_up=True, profile=SAFE, settings_polluted=False, gate=GATE_OK
        )
        assert _names(checks)["engine pinned"].ok is False

    def test_flags_proxy_down(self):
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=False, profile=SAFE, settings_polluted=False, gate=None
        )
        assert _names(checks)["proxy health"].ok is False

    def test_flags_cost_unsafe_profile(self):
        """R5a: a tier resolving to anthropic/* fails the cost-safety check."""
        bad = profiles.Profile(name="x", main="anthropic/claude-3-5-sonnet", small_fast="deepseek/deepseek-chat", catch_all="deepseek/deepseek-chat")
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=True, profile=bad, settings_polluted=False, gate=GATE_OK
        )
        cs = _names(checks)["cost-safety"]
        assert cs.ok is False and "main" in cs.detail

    def test_flags_settings_pollution(self):
        """R5: an ANTHROPIC_BASE_URL env block in settings.json means something global was touched."""
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=True, profile=SAFE, settings_polluted=True, gate=GATE_OK
        )
        assert _names(checks)["nothing global"].ok is False

    def test_gate_fails_when_not_run(self):
        """No gate result (proxy down) is a failed, not skipped-as-pass, gate check."""
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=False, profile=SAFE, settings_polluted=False, gate=None
        )
        assert _names(checks)["tool-use gate"].ok is False

    def test_gate_reflects_failed_round_trip(self):
        bad_gate = GateResult(ok=False, non_streaming=True, streaming=False, detail="streaming dropped args")
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=True, profile=SAFE, settings_polluted=False, gate=bad_gate
        )
        assert _names(checks)["tool-use gate"].ok is False

    def test_spend_cap_is_informational(self):
        checks = tc.run_translator_checks(
            installed_version=PIN, proxy_up=True, profile=SAFE, settings_polluted=False, gate=GATE_OK
        )
        assert _names(checks)["spend cap"].ok is True


class TestSettingsHasProxyEnv:
    """Tests for settings_has_proxy_env(path)."""

    def test_true_when_env_block_redirects_base_url(self, tmp_path):
        s = tmp_path / "settings.json"
        s.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"}}', encoding="utf-8")
        assert tc.settings_has_proxy_env(s) is True

    def test_false_when_no_env_block(self, tmp_path):
        s = tmp_path / "settings.json"
        s.write_text('{"model": "sonnet"}', encoding="utf-8")
        assert tc.settings_has_proxy_env(s) is False

    def test_false_when_settings_absent(self, tmp_path):
        assert tc.settings_has_proxy_env(tmp_path / "nope.json") is False

    def test_false_on_corrupt_settings(self, tmp_path):
        s = tmp_path / "settings.json"
        s.write_text("{not json", encoding="utf-8")
        assert tc.settings_has_proxy_env(s) is False


class TestGatherChecks:
    """Tests for gather_checks() - resolves live inputs via injected probes."""

    def test_wires_probes_into_checks(self, tmp_path):
        class FakeEngine:
            def installed_version(self, run):
                return PIN
        settings = tmp_path / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        checks = tc.gather_checks(
            SAFE,
            engine=FakeEngine(),
            health=lambda host, port: True,
            gate_fn=lambda base_url, model: GATE_OK,
            settings_path=settings,
        )
        assert all(c.ok for c in checks)

    def test_skips_gate_when_proxy_down(self, tmp_path):
        """When health says down, the gate is not called (nothing to test)."""
        class FakeEngine:
            def installed_version(self, run):
                return PIN
        called = []
        checks = tc.gather_checks(
            SAFE,
            engine=FakeEngine(),
            health=lambda host, port: False,
            gate_fn=lambda base_url, model: called.append(1) or GATE_OK,
            settings_path=tmp_path / "settings.json",
        )
        assert called == []  # gate not run when proxy is down
        assert _names(checks)["proxy health"].ok is False
