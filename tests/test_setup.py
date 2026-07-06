# test_setup.py - One-command `sb setup` orchestration (SPEC-005 R1).
#
# Hermetic: every collaborator (uv check, engine, proxy start, tool-use gate, key
# prompt) is injected; all storage under tmp_path; fake key value throughout.

from switchboard import setup
from switchboard.setup import SetupResult
from switchboard.translator_engine import InstallResult, PIN
from switchboard.translator_lifecycle import ProxyStatus
from switchboard.verify import GateResult
from switchboard import paths, profiles

FAKE_KEY = "sk-or-v1-FAKEKEY000"


class FakeEngine:
    """Engine stub exposing just what setup drives (install + config-gen)."""

    def __init__(self):
        self.installed = False

    def ensure_installed(self, run):
        self.installed = True
        return InstallResult(action="installed", version=PIN)

    def generate_config(self, tier_map, catch_all):
        return "GENERATED-CONFIG\n"


def ok_start(engine, **kwargs):
    return ProxyStatus(running=True, pid=4321, host=kwargs["host"], port=kwargs["port"])


def ok_gate(base_url, model, **kwargs):
    return GateResult(ok=True, non_streaming=True, streaming=True, detail="ok")


def run_setup(tmp_path, **overrides):
    """Invoke run_setup with hermetic defaults, overridable per test."""
    env = overrides.pop("env_path", None) or (tmp_path / ".env_claude")
    if not env.exists():
        env.write_text(f"OPENROUTER_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    kwargs = dict(
        root=tmp_path,
        engine=FakeEngine(),
        env_path=env,
        have_uv=lambda: True,
        prompt=lambda msg: FAKE_KEY,
        start=ok_start,
        gate=ok_gate,
    )
    kwargs.update(overrides)
    return setup.run_setup(**kwargs)


class TestRunSetup:
    """Tests for run_setup()."""

    def test_happy_path_ends_ready_and_writes_artifacts(self, tmp_path):
        """A clean run installs, writes profile + config, starts, gates -> ready."""
        result = run_setup(tmp_path)
        assert isinstance(result, SetupResult)
        assert result.ok is True and "ready" in result.message.lower()
        # A default profile and an engine config were persisted.
        assert paths.active_profile_path(tmp_path).exists()
        cfg = paths.proxy_config_path(tmp_path)
        assert cfg.exists() and cfg.read_text(encoding="utf-8") == "GENERATED-CONFIG\n"

    def test_fails_clearly_when_uv_missing(self, tmp_path):
        """No uv -> a clear failure before any proxy work."""
        result = run_setup(tmp_path, have_uv=lambda: False)
        assert result.ok is False and "uv" in result.message.lower()

    def test_prompts_once_and_persists_key_when_absent(self, tmp_path):
        """No key in the env file -> prompt once and append it (never printed)."""
        env = tmp_path / ".env_claude"
        env.write_text("MD_VAULT=/x\n", encoding="utf-8")  # no OPENROUTER key
        asked = []
        result = run_setup(
            tmp_path, env_path=env,
            prompt=lambda msg: asked.append(msg) or FAKE_KEY,
        )
        assert result.ok is True
        assert len(asked) == 1  # prompted exactly once
        assert f"OPENROUTER_API_KEY={FAKE_KEY}" in env.read_text(encoding="utf-8")

    def test_fails_when_key_prompt_is_empty(self, tmp_path):
        """An empty key at the prompt is a clear failure, not a blank persisted key."""
        env = tmp_path / ".env_claude"
        env.write_text("", encoding="utf-8")
        result = run_setup(tmp_path, env_path=env, prompt=lambda msg: "  ")
        assert result.ok is False and "key" in result.message.lower()

    def test_fails_when_proxy_not_ready(self, tmp_path):
        """If the proxy never becomes ready, setup reports failure (no false ready)."""
        def down_start(engine, **kwargs):
            return ProxyStatus(running=False, pid=1, host=kwargs["host"], port=kwargs["port"])
        result = run_setup(tmp_path, start=down_start)
        assert result.ok is False and "proxy" in result.message.lower()

    def test_fails_when_gate_fails(self, tmp_path):
        """A model that fails the tool-use gate blocks 'ready' and surfaces the detail."""
        def bad_gate(base_url, model, **kwargs):
            return GateResult(ok=False, non_streaming=True, streaming=False, detail="streaming dropped args")
        result = run_setup(tmp_path, gate=bad_gate)
        assert result.ok is False and "gate" in result.message.lower()

    def test_idempotent_reuses_existing_profile(self, tmp_path):
        """Re-running keeps an existing (customized) profile instead of overwriting it."""
        existing = profiles.default_profile("z-ai/glm-4.6", "z-ai/glm-4.6", port=4100)
        profiles.save(existing, paths.active_profile_path(tmp_path))
        result = run_setup(tmp_path)
        assert result.ok is True
        assert profiles.load(paths.active_profile_path(tmp_path)) == existing

    def test_reports_failure_when_engine_install_raises(self, tmp_path):
        """A live install failure (EngineError) becomes a clear failure, not a traceback (R1)."""
        from switchboard.translator_engine import EngineError

        class BoomEngine:
            def ensure_installed(self, run):
                raise EngineError("uv pip install failed")
            def generate_config(self, tier_map, catch_all):
                return "x"
        result = run_setup(tmp_path, engine=BoomEngine())
        assert result.ok is False and "install" in result.message.lower()

    def test_reports_failure_on_corrupt_existing_profile(self, tmp_path):
        """A corrupt profile.json on re-run yields a clear failure, not a ProfileError crash."""
        pp = paths.active_profile_path(tmp_path)
        pp.parent.mkdir(parents=True, exist_ok=True)
        pp.write_text("{bad json", encoding="utf-8")
        result = run_setup(tmp_path)
        assert result.ok is False
