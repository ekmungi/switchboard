# setup.py - One-command `sb setup` (SPEC-005 R1): idempotent, ends "ready" or clear failure.
#
# The whole flow, no manual file editing at any point: ensure prerequisites (uv +
# pinned engine) -> resolve the OpenRouter key (prompt ONCE only if absent) -> a
# default model profile -> generate the engine config -> start the proxy -> run the
# tool-use self-test. Re-runnable: the engine reports "present", the key is reused, an
# existing profile is kept, and the proxy daemon is reused. Every external collaborator
# is injected so the orchestration is unit-tested without touching the machine.

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths, profiles
from .keystore import env_file_path, read_key
from .profiles import ProfileError
from .translator_engine import Engine, EngineConfigError, EngineError, LiteLLMEngine
from .translator_lifecycle import ProxyStatus, start as lifecycle_start
from .verify import GateResult, tool_use_gate

# Default tiers: both passed the Phase-0 tool-use gate (R-008); GLM leads (larger
# context), DeepSeek is the cheap small/fast + catch-all.
DEFAULT_MAIN: str = "z-ai/glm-4.6"
DEFAULT_SMALL: str = "deepseek/deepseek-chat"
LOOPBACK: str = "127.0.0.1"


class SetupError(Exception):
    """Internal control-flow: a setup step failed with a user-facing reason."""


@dataclass(frozen=True)
class SetupResult:
    """Outcome of run_setup.

    Fields:
        ok:      True when setup ended ready (gate passed).
        steps:   Ordered human-readable step outcomes (for `sb setup` output).
        message: 'ready ...' on success, or the failure reason.
    """

    ok: bool
    steps: list[str]
    message: str


def _default_have_uv() -> bool:
    """Return True iff the uv executable is on PATH."""
    return shutil.which("uv") is not None


def _append_key(env_path: Path, value: str) -> None:
    """Append OPENROUTER_API_KEY=<value> to the env file (never logged)."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    prefix = "\n" if (existing and not existing.endswith("\n")) else ""  # avoid gluing onto a prior line
    with open(env_path, "a", encoding="utf-8") as fh:
        fh.write(f"{prefix}OPENROUTER_API_KEY={value}\n")


def _resolve_key(env_path: Path, prompt: Callable[[str], str]) -> str:
    """Return the OpenRouter key, prompting once and persisting it when absent (R1/R6)."""
    key = read_key("OPENROUTER_API_KEY", path=env_path, environ={})
    if key:
        return key
    entered = prompt("Enter your OpenRouter API key: ").strip()
    if not entered:
        raise SetupError("no OpenRouter key provided (setup needs a key to continue)")
    _append_key(env_path, entered)
    return entered


def _resolve_profile(root: Path | None, main: str, small: str) -> profiles.Profile:
    """Load an existing profile (idempotent reuse) or build + save the default."""
    profile_path = paths.active_profile_path(root)
    existing = profiles.load(profile_path)
    if existing is not None:
        return existing
    profile = profiles.default_profile(main, small)
    profiles.save(profile, profile_path)
    return profile


def run_setup(
    *,
    root: Path | None = None,
    engine: Engine | None = None,
    env_path: Path | None = None,
    prompt: Callable[[str], str] = input,
    have_uv: Callable[[], bool] = _default_have_uv,
    start: Callable[..., ProxyStatus] = lifecycle_start,
    gate: Callable[..., GateResult] = tool_use_gate,
    run: Callable[..., object] = subprocess.run,
    default_main: str = DEFAULT_MAIN,
    default_small: str = DEFAULT_SMALL,
) -> SetupResult:
    """Run the one-command setup flow and return its result (never raises).

    Args:
        root:       Switchboard home root (tests pass tmp_path).
        engine:     Engine adapter (defaults to LiteLLMEngine at the home engine dir).
        env_path:   Env file for the key (defaults to ~/.env_claude).
        prompt:     Callable to ask for the key (defaults to input()).
        have_uv/start/gate/run: Injected collaborators for hermetic testing.

    Returns:
        SetupResult: ok=True with a 'ready' message, or ok=False with the reason.
    """
    engine = engine if engine is not None else LiteLLMEngine(engine_dir=paths.engine_dir(root))
    env_file = env_path if env_path is not None else env_file_path()
    steps: list[str] = []
    try:
        # 1. Prerequisites: uv + the pinned engine.
        if not have_uv():
            raise SetupError("uv not found on PATH (install uv first: https://astral.sh/uv)")
        install = engine.ensure_installed(run)
        steps.append(f"engine {install.version} ({install.action})")

        # 2. Key (prompt once only if absent).
        key = _resolve_key(env_file, prompt)
        steps.append("OpenRouter key resolved")

        # 3. Default (or reused) profile.
        profile = _resolve_profile(root, default_main, default_small)
        steps.append(f"profile '{profile.name}' (main={profile.main}, small={profile.small_fast})")

        # 4. Generate + write the engine config.
        config_path = paths.proxy_config_path(root)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            engine.generate_config(profiles.tier_map(profile), profile.catch_all), encoding="utf-8"
        )
        steps.append("engine config generated")

        # 5. Start (or reuse) the proxy.
        status = start(
            engine,
            config_path=config_path,
            host=LOOPBACK,
            port=profile.port,
            pidfile=paths.proxy_pidfile(root),
            logfile=paths.proxy_logfile(root),
            api_key=key,
        )
        if not status.running:
            raise SetupError(f"proxy did not become ready on {LOOPBACK}:{profile.port}")
        steps.append(f"proxy {'reused' if status.reused else 'started'} on {LOOPBACK}:{profile.port}")

        # 6. Tool-use self-test.
        result = gate(f"http://{LOOPBACK}:{profile.port}", profile.main)
        if not result.ok:
            raise SetupError(f"tool-use gate failed ({result.detail})")
        steps.append("tool-use gate passed")
    except (SetupError, EngineError, EngineConfigError, ProfileError, OSError) as exc:
        # R1: any step failure (bad uv/install, unsafe/corrupt profile, I/O) ends in a
        # clear failure result, never an uncaught traceback.
        return SetupResult(ok=False, steps=steps, message=str(exc))

    return SetupResult(ok=True, steps=steps, message=f"ready -- `sb code` will use {profile.main}")
