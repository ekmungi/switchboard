# test_launch.py - `sb code [<model>]`: ensure proxy up, set session env, run claude (R4).
#
# Hermetic: start/stop/claude-launch injected; storage under tmp_path; fake key in a
# tmp env file. Plain `claude` is never touched (we only set a per-session child env).

from switchboard import launch, profiles, paths
from switchboard.launch import LaunchResult
from switchboard.translator_lifecycle import ProxyStatus

FAKE_KEY = "sk-or-v1-FAKEKEY000"


class FakeEngine:
    """Engine stub exposing just generate_config (start is injected)."""

    def generate_config(self, tier_map, catch_all):
        return "GENERATED-CONFIG\n"


def _seed(tmp_path, main="z-ai/glm-4.6", small="deepseek/deepseek-chat"):
    """Persist an active profile + a key env file; return the env path."""
    profiles.save(profiles.default_profile(main, small), paths.active_profile_path(tmp_path))
    env = tmp_path / ".env_claude"
    env.write_text(f"OPENROUTER_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    return env


def up_start(engine, **kwargs):
    return ProxyStatus(running=True, pid=4321, host=kwargs["host"], port=kwargs["port"])


def run_code(tmp_path, arg=None, **overrides):
    env = overrides.pop("env_path", None) or _seed(tmp_path)
    launched = overrides.pop("_launched", {})

    def _record_launch(e):
        launched["env"] = e
        return 0  # claude's exit code

    kwargs = dict(
        root=tmp_path,
        engine=FakeEngine(),
        env_path=env,
        environ={},
        start=up_start,
        stop=lambda *a, **k: True,
        launch=_record_launch,
    )
    kwargs.update(overrides)
    return launch.run_code(arg, **kwargs), launched


class TestSessionEnv:
    """Tests for session_env()."""

    def test_sets_base_url_token_and_models(self):
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat", port=4100)
        env = launch.session_env(p, p.port)
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4100"
        assert env["ANTHROPIC_MODEL"] == "z-ai/glm-4.6"
        assert env["ANTHROPIC_SMALL_FAST_MODEL"] == "deepseek/deepseek-chat"
        assert env["ANTHROPIC_AUTH_TOKEN"]  # a token is present

    def test_does_not_leak_the_openrouter_key(self):
        """The session env must not carry the OpenRouter key (it lives in the proxy env)."""
        p = profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat")
        env = launch.session_env(p, p.port)
        assert FAKE_KEY not in env.values()
        assert env["ANTHROPIC_AUTH_TOKEN"] != FAKE_KEY


class TestRunCode:
    """Tests for run_code()."""

    def test_requires_setup_when_no_profile(self, tmp_path):
        """No active profile -> a clear 'run sb setup' failure, nothing launched."""
        env = tmp_path / ".env_claude"
        env.write_text(f"OPENROUTER_API_KEY={FAKE_KEY}\n", encoding="utf-8")
        result, launched = run_code(tmp_path, env_path=env)
        assert isinstance(result, LaunchResult)
        assert result.ok is False and "setup" in result.message.lower()
        assert "env" not in launched  # claude never launched

    def test_happy_path_launches_claude_with_proxy_env(self, tmp_path):
        """Proxy up + claude launched with ANTHROPIC_BASE_URL pointing at the proxy."""
        result, launched = run_code(tmp_path)
        assert result.ok is True and result.exit_code == 0
        assert launched["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000"
        assert any("/logout" in n for n in result.notes)  # cached-login gotcha surfaced

    def test_model_arg_overrides_and_persists_main(self, tmp_path):
        """`sb code <model>` switches the main tier and persists it."""
        result, _ = run_code(tmp_path, arg="deepseek/deepseek-chat")
        assert result.ok is True
        saved = profiles.load(paths.active_profile_path(tmp_path))
        assert saved.main == "deepseek/deepseek-chat"

    def test_model_change_restarts_proxy_to_apply_new_config(self, tmp_path):
        """Switching the model drops the old-config daemon (stop) before starting."""
        stopped = []
        result, _ = run_code(
            tmp_path, arg="deepseek/deepseek-chat",
            stop=lambda *a, **k: stopped.append(a) or True,
        )
        assert result.ok is True and len(stopped) == 1  # old daemon stopped once

    def test_same_model_reuses_without_restart(self, tmp_path):
        """`sb code <same-model>` does not stop/restart (daemon reuse)."""
        stopped = []
        result, _ = run_code(
            tmp_path, arg="z-ai/glm-4.6",  # equals the seeded main
            stop=lambda *a, **k: stopped.append(a) or True,
        )
        assert result.ok is True and stopped == []

    def test_refuses_cost_unsafe_model(self, tmp_path):
        """`sb code anthropic/...` is refused (would leak metered Claude pricing)."""
        result, launched = run_code(tmp_path, arg="anthropic/claude-3-5-sonnet")
        assert result.ok is False and "refus" in result.message.lower()
        assert "env" not in launched
        # profile main is unchanged
        assert profiles.load(paths.active_profile_path(tmp_path)).main == "z-ai/glm-4.6"

    def test_fails_when_proxy_not_ready(self, tmp_path):
        def down_start(engine, **kwargs):
            return ProxyStatus(running=False, pid=1, host=kwargs["host"], port=kwargs["port"])
        result, launched = run_code(tmp_path, start=down_start)
        assert result.ok is False and "proxy" in result.message.lower()
        assert "env" not in launched

    def test_fails_when_key_missing(self, tmp_path):
        """No key anywhere -> clear failure, claude not launched."""
        profiles.save(profiles.default_profile("z-ai/glm-4.6", "deepseek/deepseek-chat"), paths.active_profile_path(tmp_path))
        env = tmp_path / ".env_claude"
        env.write_text("", encoding="utf-8")
        result, launched = run_code(tmp_path, env_path=env)
        assert result.ok is False
        assert "env" not in launched


class TestClaudeArgv:
    """Tests for _claude_argv()."""

    def test_windows_uses_cmd_shim(self):
        assert launch._claude_argv("nt")[:2] == ["cmd", "/c"]

    def test_posix_calls_claude_directly(self):
        assert launch._claude_argv("posix") == ["claude"]
