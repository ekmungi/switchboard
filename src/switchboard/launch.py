# launch.py - `sb code [<model>]`: ensure the proxy is up, set a per-session env, run claude (R4).
#
# Nothing is written to ~/.claude/settings.json: `sb code` only sets ANTHROPIC_* in the
# environment of the child `claude` process, so plain `claude` (Max) is untouched and
# teardown is just closing that process (the proxy daemon stays up for reuse). An
# optional model arg switches the active profile's main tier (cost-safe; regenerates the
# config and restarts the proxy so the new mapping takes effect). Collaborators injected.

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping

from . import paths, profiles
from .cost_safety import unsafe_reason
from .keystore import KeystoreError, env_file_path, require_key
from .translator_engine import Engine, LiteLLMEngine
from .translator_lifecycle import ProxyStatus, start as lifecycle_start, stop as lifecycle_stop

LOOPBACK: str = "127.0.0.1"
AUTH_TOKEN: str = "sb-local-proxy"  # proxy has no master key; Claude Code just needs a token present
LOGOUT_NOTE: str = (
    "If Claude Code still uses your Max subscription instead of the proxy, run `/logout` "
    "inside it once -- a cached login can override ANTHROPIC_BASE_URL (R-007)."
)


@dataclass(frozen=True)
class LaunchResult:
    """Outcome of run_code.

    Fields:
        ok:        True when claude was launched.
        exit_code: claude's exit code (None when it never launched).
        message:   Human-readable status or failure reason.
        env:       The per-session ANTHROPIC_* env handed to claude (empty on failure).
        notes:     Advisories to surface (e.g. the /logout gotcha).
        profile:   The profile used (None when there was none).
    """

    ok: bool
    exit_code: int | None
    message: str
    env: dict[str, str]
    notes: list[str]
    profile: profiles.Profile | None


def session_env(profile: profiles.Profile, port: int, token: str = AUTH_TOKEN) -> dict[str, str]:
    """Return the per-session ANTHROPIC_* env that points Claude Code at the proxy.

    Includes the base URL (loopback + port), a placeholder auth token (never the
    OpenRouter key -- that lives only in the proxy's own env), and the per-tier
    model strings so Claude Code emits mappings the proxy config resolves.
    """
    return {
        "ANTHROPIC_BASE_URL": f"http://{LOOPBACK}:{port}",
        "ANTHROPIC_AUTH_TOKEN": token,
        **profiles.model_env(profile),
    }


def _claude_argv(platform_name: str | None = None) -> list[str]:
    """Return the argv to launch claude (cmd shim on Windows, bare elsewhere)."""
    if (platform_name or os.name) == "nt":
        return ["cmd", "/c", "claude"]
    return ["claude"]


def _run_claude(env: Mapping[str, str], platform_name: str | None = None) -> int:
    """Launch claude with the session env layered over the current environment."""
    merged = {**os.environ, **env}
    return subprocess.call(_claude_argv(platform_name), env=merged)


def _fail(message: str, profile: profiles.Profile | None) -> LaunchResult:
    """Build a failed LaunchResult (claude not launched)."""
    return LaunchResult(ok=False, exit_code=None, message=message, env={}, notes=[], profile=profile)


def run_code(
    arg: str | None = None,
    *,
    root: Path | None = None,
    engine: Engine | None = None,
    env_path: Path | None = None,
    environ: Mapping[str, str] = os.environ,
    start: Callable[..., ProxyStatus] = lifecycle_start,
    stop: Callable[..., object] = lifecycle_stop,
    launch: Callable[[Mapping[str, str]], int] | None = None,
    platform_name: str | None = None,
) -> LaunchResult:
    """Run `sb code [<model>]`: ensure the proxy is up, then launch claude against it.

    Args:
        arg:      Optional OpenRouter model id to make the main tier for this session.
        root:     Switchboard home root (tests pass tmp_path).
        engine:   Engine adapter (defaults to LiteLLMEngine at the home engine dir).
        env_path: Env file holding the key (defaults to ~/.env_claude).
        environ:  Process environment for the key fallback (injected for tests).
        start/stop/launch: Injected collaborators for hermetic testing.

    Returns:
        LaunchResult: ok=True with claude's exit code, or ok=False with the reason.
    """
    engine = engine if engine is not None else LiteLLMEngine(engine_dir=paths.engine_dir(root))
    launch = launch if launch is not None else (lambda env: _run_claude(env, platform_name))
    profile_path = paths.active_profile_path(root)

    try:
        profile = profiles.load(profile_path)
    except profiles.ProfileError as exc:
        return _fail(f"{exc} -- run `sb setup`", None)
    if profile is None:
        return _fail("no active profile -- run `sb setup` first", None)

    # Optional model override: cost-safe, and only when it actually changes the tier.
    changed = False
    if arg:
        reason = unsafe_reason(arg)
        if reason:
            return _fail(f"refusing model {arg!r}: {reason} (R3a)", profile)
        if arg != profile.main:
            profile = replace(profile, main=arg)
            try:
                profiles.save(profile, profile_path)
            except profiles.ProfileError as exc:
                return _fail(str(exc), profile)
            changed = True

    # Key (required to run).
    try:
        key = require_key(
            "OPENROUTER_API_KEY", path=env_path if env_path is not None else env_file_path(), environ=environ
        )
    except KeystoreError as exc:
        return _fail(f"{exc} -- run `sb setup`", profile)

    # Regenerate the engine config when the mapping changed or none exists yet; a
    # model change means the running daemon has stale config, so drop it first.
    config_path = paths.proxy_config_path(root)
    if changed or not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            engine.generate_config(profiles.tier_map(profile), profile.catch_all), encoding="utf-8"
        )
        if changed:
            stop(paths.proxy_pidfile(root), LOOPBACK, profile.port)

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
        return _fail(f"proxy did not become ready on {LOOPBACK}:{profile.port}", profile)

    env = session_env(profile, profile.port)
    exit_code = launch(env)
    return LaunchResult(
        ok=True,
        exit_code=exit_code,
        message=f"launched claude via {profile.main}",
        env=env,
        notes=[LOGOUT_NOTE],
        profile=profile,
    )
