# test_translator_engine.py - Engine interface + LiteLLM adapter (SPEC-005 R2/R3a/R9/R11).
#
# Hermetic: no venv is created and no network is touched. The subprocess runner is
# injected (a recorder returning canned results); the venv python is faked as a file.

import subprocess

import pytest

from switchboard.translator_engine import (
    EngineConfigError,
    EngineError,
    InstallResult,
    LiteLLMEngine,
    PIN,
)


class FakeProc:
    """Minimal stand-in for a subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def recorder(results):
    """Return a subprocess.run-like callable that records argv and returns queued procs.

    Args:
        results: list of FakeProc returned in order per call (last one repeats).
    """
    calls = []

    def _run(argv, **kwargs):
        calls.append(list(argv))
        return results[min(len(calls) - 1, len(results) - 1)]

    _run.calls = calls
    return _run


def nt_engine(engine_dir):
    return LiteLLMEngine(engine_dir=engine_dir, platform_name="nt")


def posix_engine(engine_dir):
    return LiteLLMEngine(engine_dir=engine_dir, platform_name="posix")


# ---------------------------------------------------------------------------
# generate_config - the cost-safety crown jewel (R3a)
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    """Tests for LiteLLMEngine.generate_config(tier_map, catch_all)."""

    def _cfg(self, tmp_path, tier_map, catch_all):
        return nt_engine(tmp_path).generate_config(tier_map, catch_all)

    def test_maps_every_tier_and_prefixes_openrouter(self, tmp_path):
        """Each Claude-tier string becomes a model_name mapping to openrouter/<id>."""
        out = self._cfg(
            tmp_path,
            {"claude-sonnet-4": "deepseek/deepseek-chat", "claude-3-5-haiku": "z-ai/glm-4.6"},
            "deepseek/deepseek-chat",
        )
        assert 'model_name: "claude-sonnet-4"' in out
        assert 'model_name: "claude-3-5-haiku"' in out
        assert "model: openrouter/deepseek/deepseek-chat" in out
        assert "model: openrouter/z-ai/glm-4.6" in out
        assert "api_key: os.environ/OPENROUTER_API_KEY" in out
        assert "drop_params: true" in out

    def test_emits_concrete_catch_all_not_passthrough(self, tmp_path):
        """The '*' catch-all maps to a CONCRETE cheap model, never openrouter/*."""
        out = self._cfg(tmp_path, {"claude-sonnet-4": "z-ai/glm-4.6"}, "deepseek/deepseek-chat")
        assert 'model_name: "*"' in out
        # The catch-all target is the concrete catch_all model, prefixed for OpenRouter.
        assert "model: openrouter/deepseek/deepseek-chat" in out
        # The forbidden passthrough wildcard must never appear.
        assert "openrouter/*" not in out

    def test_rejects_anthropic_tier_target(self, tmp_path):
        """A tier mapping to a Claude-priced anthropic/* model is refused (R3a)."""
        with pytest.raises(EngineConfigError):
            self._cfg(
                tmp_path,
                {"claude-sonnet-4": "anthropic/claude-3-5-sonnet"},
                "deepseek/deepseek-chat",
            )

    def test_rejects_anthropic_catch_all(self, tmp_path):
        """A Claude-priced catch-all is refused (subagent/background leak)."""
        with pytest.raises(EngineConfigError):
            self._cfg(tmp_path, {"claude-sonnet-4": "z-ai/glm-4.6"}, "anthropic/claude-3-haiku")

    def test_rejects_passthrough_wildcard_catch_all(self, tmp_path):
        """A passthrough wildcard catch-all (openrouter/*) is refused (R3a)."""
        with pytest.raises(EngineConfigError):
            self._cfg(tmp_path, {"claude-sonnet-4": "z-ai/glm-4.6"}, "openrouter/*")

    def test_rejects_bare_wildcard_tier_target(self, tmp_path):
        """A bare '*' tier target is refused."""
        with pytest.raises(EngineConfigError):
            self._cfg(tmp_path, {"claude-sonnet-4": "*"}, "deepseek/deepseek-chat")

    def test_rejects_empty_tier_map(self, tmp_path):
        """An empty tier map is refused: every tier must resolve explicitly."""
        with pytest.raises(EngineConfigError):
            self._cfg(tmp_path, {}, "deepseek/deepseek-chat")

    def test_rejects_empty_target(self, tmp_path):
        """A blank model target is refused."""
        with pytest.raises(EngineConfigError):
            self._cfg(tmp_path, {"claude-sonnet-4": "  "}, "deepseek/deepseek-chat")

    def test_catch_all_entry_comes_after_concrete_tiers(self, tmp_path):
        """LiteLLM matches model_list top-down: the '*' catch-all MUST be last, or
        it shadows every concrete tier and routes all traffic through one model."""
        out = self._cfg(
            tmp_path,
            {"claude-sonnet-4": "z-ai/glm-4.6", "claude-3-5-haiku": "deepseek/deepseek-chat"},
            "deepseek/deepseek-chat",
        )
        star_idx = out.index('model_name: "*"')
        last_concrete = max(
            out.index('model_name: "claude-sonnet-4"'),
            out.index('model_name: "claude-3-5-haiku"'),
        )
        assert star_idx > last_concrete


# ---------------------------------------------------------------------------
# spawn_argv / spawn_env - launch vector (R11)
# ---------------------------------------------------------------------------


class TestSpawnArgv:
    """Tests for LiteLLMEngine.spawn_argv."""

    def test_windows_uses_scripts_litellm_exe(self, tmp_path):
        """Windows launches the venv's Scripts/litellm.exe with config/host/port."""
        argv = nt_engine(tmp_path).spawn_argv(tmp_path / "proxy.yaml", "127.0.0.1", 4000)
        assert argv[0].endswith("Scripts\\litellm.exe") or argv[0].endswith("Scripts/litellm.exe")
        assert "--config" in argv and "--host" in argv and "--port" in argv
        assert "127.0.0.1" in argv and "4000" in argv

    def test_posix_uses_bin_litellm(self, tmp_path):
        """POSIX launches the venv's bin/litellm (separator normalized for host)."""
        argv = posix_engine(tmp_path).spawn_argv(tmp_path / "proxy.yaml", "127.0.0.1", 4000)
        assert argv[0].replace("\\", "/").endswith("bin/litellm")


class TestSpawnEnv:
    """Tests for LiteLLMEngine.spawn_env."""

    def test_sets_pythonutf8_and_key(self, tmp_path):
        """R11: PYTHONUTF8=1 plus the OpenRouter key are added to the base env."""
        env = nt_engine(tmp_path).spawn_env({"PATH": "x"}, "sk-or-test")
        assert env["PYTHONUTF8"] == "1"
        assert env["OPENROUTER_API_KEY"] == "sk-or-test"
        assert env["PATH"] == "x"

    def test_does_not_mutate_base_env(self, tmp_path):
        """Immutability: the caller's env dict is left untouched."""
        base = {"PATH": "x"}
        nt_engine(tmp_path).spawn_env(base, "sk-or-test")
        assert base == {"PATH": "x"}

    def test_scrubs_inherited_anthropic_vars(self, tmp_path):
        """The proxy is an OpenRouter translator: it must never inherit ANTHROPIC_*
        (a self-referential BASE_URL or stray Claude key would risk a loopback)."""
        base = {
            "PATH": "x",
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
            "ANTHROPIC_API_KEY": "sk-ant",
        }
        env = nt_engine(tmp_path).spawn_env(base, "sk-or")
        assert "ANTHROPIC_BASE_URL" not in env and "ANTHROPIC_API_KEY" not in env
        assert env["PYTHONUTF8"] == "1" and env["OPENROUTER_API_KEY"] == "sk-or"
        assert env["PATH"] == "x"
        assert base["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000"  # base untouched


# ---------------------------------------------------------------------------
# installed_version / ensure_installed - the pinned-engine adapter (R7/R9)
# ---------------------------------------------------------------------------


class TestInstalledVersion:
    """Tests for LiteLLMEngine.installed_version."""

    def test_none_when_venv_absent(self, tmp_path):
        """No venv python on disk -> not installed, and the runner is never called."""
        run = recorder([FakeProc(stdout=PIN)])
        assert nt_engine(tmp_path).installed_version(run) is None
        assert run.calls == []

    def test_returns_version_when_import_succeeds(self, tmp_path):
        """With a venv python present, the reported litellm version is returned."""
        eng = nt_engine(tmp_path)
        _touch_python(eng)
        run = recorder([FakeProc(returncode=0, stdout=PIN + "\n")])
        assert eng.installed_version(run) == PIN

    def test_none_when_import_fails(self, tmp_path):
        """A non-zero import probe means litellm is not importable -> None."""
        eng = nt_engine(tmp_path)
        _touch_python(eng)
        run = recorder([FakeProc(returncode=1, stderr="ModuleNotFoundError")])
        assert eng.installed_version(run) is None

    def test_none_when_import_prints_nothing(self, tmp_path):
        """A zero-exit probe that prints nothing is not a real version -> None
        (so doctor's pinned-version check never treats '' as installed)."""
        eng = nt_engine(tmp_path)
        _touch_python(eng)
        run = recorder([FakeProc(returncode=0, stdout="   ")])
        assert eng.installed_version(run) is None

    def test_probe_reads_distribution_metadata_not_dunder_version(self, tmp_path):
        """litellm exposes no __version__ attribute (it overrides __getattr__ to raise),
        so the probe MUST read the installed distribution metadata."""
        eng = nt_engine(tmp_path)
        _touch_python(eng)
        run = recorder([FakeProc(returncode=0, stdout=PIN)])
        eng.installed_version(run)
        probe = " ".join(run.calls[0])
        assert "importlib.metadata" in probe
        assert "__version__" not in probe


class TestEnsureInstalled:
    """Tests for LiteLLMEngine.ensure_installed."""

    def test_present_when_pin_already_installed(self, tmp_path):
        """When the pin is already present, no uv commands run (idempotent)."""
        eng = nt_engine(tmp_path)
        _touch_python(eng)
        run = recorder([FakeProc(returncode=0, stdout=PIN)])
        result = eng.ensure_installed(run)
        assert result == InstallResult(action="present", version=PIN)
        # Only the version probe ran; no venv/install commands.
        assert all("pip" not in " ".join(c) for c in run.calls)

    def test_installs_pinned_engine_when_absent(self, tmp_path):
        """When absent, it creates the venv FIRST, then installs the pinned
        litellm[proxy] INTO that venv (--python <venv-python>), in order."""
        eng = nt_engine(tmp_path)
        run = recorder([FakeProc(returncode=0)])
        result = eng.ensure_installed(run)
        assert result == InstallResult(action="installed", version=PIN)
        assert "venv" in run.calls[0]  # venv created first
        assert "--python" in run.calls[1] and str(eng._python()) in run.calls[1]
        assert f"litellm[proxy]=={PIN}" in run.calls[1]  # installed into the venv, pinned

    def test_raises_engine_error_on_venv_failure(self, tmp_path):
        """A failing `uv venv` surfaces as EngineError, not a silent pass."""
        eng = nt_engine(tmp_path)
        run = recorder([FakeProc(returncode=1, stderr="venv boom")])
        with pytest.raises(EngineError):
            eng.ensure_installed(run)

    def test_raises_when_pip_install_step_fails(self, tmp_path):
        """venv succeeds but the pip install fails -> EngineError (distinct step)."""
        eng = nt_engine(tmp_path)
        run = recorder([FakeProc(returncode=0), FakeProc(returncode=1, stderr="pip boom")])
        with pytest.raises(EngineError):
            eng.ensure_installed(run)
        assert "venv" in run.calls[0]  # venv ran and succeeded before pip failed


class TestHealthPath:
    """Tests for LiteLLMEngine.health_path."""

    def test_liveliness_endpoint(self, tmp_path):
        """The engine exposes LiteLLM's liveliness endpoint for readiness checks."""
        assert nt_engine(tmp_path).health_path() == "/health/liveliness"


def _touch_python(engine: LiteLLMEngine) -> None:
    """Create a fake venv python executable so installed_version probes it."""
    py = engine._python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
