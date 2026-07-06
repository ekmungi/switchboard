# translator_checks.py - Pure `sb doctor` logic for the clean translator (SPEC-005 R5/R5a).
#
# Mirrors checks.py (CCR doctor): pure check builders plus one small settings.json
# reader. run_translator_checks takes already-resolved values so it unit-tests without
# I/O; gather_checks resolves the live inputs through injected probes. The cost-safety
# check (R5a) reuses profiles.unsafe_tiers -> cost_safety, the same predicate the config
# generator enforces at write time, so the audit can never disagree with the guard.

import json
import subprocess
from pathlib import Path
from typing import Callable

from . import profiles
from .checks import Check
from .translator_engine import PIN, Engine, LiteLLMEngine
from .verify import GateResult, tool_use_gate
from .translator_lifecycle import proxy_health
from .paths import engine_dir

LOOPBACK: str = "127.0.0.1"
SPEND_CAP_NOTE: str = "keep an eye on your OpenRouter balance (low-credit runs fail mid-session)"


def settings_path_default() -> Path:
    """Return the default Claude Code settings path (~/.claude/settings.json)."""
    return Path.home() / ".claude" / "settings.json"


def settings_has_proxy_env(path: Path) -> bool:
    """Return True iff settings.json carries an env block redirecting ANTHROPIC_BASE_URL.

    The clean-translator invariant (R4/R5) is that nothing is written to
    settings.json -- `sb code` sets the redirect only in the child process env.
    A present env.ANTHROPIC_BASE_URL means something global was touched. Any read
    error yields False (absence is not pollution).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    env = data.get("env", {}) if isinstance(data, dict) else {}
    return isinstance(env, dict) and "ANTHROPIC_BASE_URL" in env


def run_translator_checks(
    *,
    installed_version: str | None,
    proxy_up: bool,
    profile: profiles.Profile | None,
    settings_polluted: bool,
    gate: GateResult | None,
) -> list[Check]:
    """Build the ordered translator doctor checks from resolved values (pure).

    Args:
        installed_version: litellm version in the engine venv (None if absent).
        proxy_up:          Proxy answered its health endpoint.
        profile:           Active profile (None if setup has not run).
        settings_polluted: settings.json carries an ANTHROPIC_BASE_URL env block.
        gate:              Tool-use gate result, or None when it was not run.

    Returns:
        Ordered Check list covering engine pin, proxy health, cost-safety (R5a),
        nothing-global (R5), the tool-use gate (R5), and a spend-cap advisory.
    """
    checks: list[Check] = []

    version_ok = installed_version == PIN
    checks.append(Check(
        name="engine pinned",
        ok=version_ok,
        detail=f"litellm {installed_version}" if version_ok else f"want {PIN}, found {installed_version}",
    ))

    checks.append(Check(
        name="proxy health",
        ok=proxy_up,
        detail="serving" if proxy_up else "not reachable",
    ))

    if profile is None:
        checks.append(Check(name="cost-safety", ok=False, detail="no active profile"))
    else:
        unsafe = profiles.unsafe_tiers(profile)
        checks.append(Check(
            name="cost-safety",
            ok=not unsafe,
            detail="all tiers route to cheap OpenRouter models"
            if not unsafe
            else "; ".join(f"{label}: {reason}" for label, reason in unsafe),
        ))

    checks.append(Check(
        name="nothing global",
        ok=not settings_polluted,
        detail="settings.json clean (no ANTHROPIC env block)"
        if not settings_polluted
        else "settings.json has an ANTHROPIC_BASE_URL env block (should be process-env only)",
    ))

    gate_ok = gate is not None and gate.ok
    checks.append(Check(
        name="tool-use gate",
        ok=gate_ok,
        detail=gate.detail if gate is not None else "not run (proxy down)",
    ))

    checks.append(Check(name="spend cap", ok=True, detail=SPEND_CAP_NOTE))
    return checks


def gather_checks(
    profile: profiles.Profile,
    *,
    root: Path | None = None,
    engine: Engine | None = None,
    health: Callable[[str, int], bool] = proxy_health,
    gate_fn: Callable[..., GateResult] = tool_use_gate,
    settings_path: Path | None = None,
    run: Callable[..., object] = subprocess.run,
) -> list[Check]:
    """Resolve the live doctor inputs via injected probes and return the checks.

    Args:
        profile:       Active profile (doctor is only run when one exists).
        engine:        Engine adapter (defaults to LiteLLMEngine at the home dir).
        health/gate_fn: Injected proxy-health and tool-use-gate callables.
        settings_path: Claude settings.json (defaults to ~/.claude/settings.json).
        run:           Injected subprocess runner for the version probe.

    Returns:
        The Check list from run_translator_checks. The gate is only run when the
        proxy is healthy (there is nothing to test on a down proxy).
    """
    eng = engine if engine is not None else LiteLLMEngine(engine_dir=engine_dir(root))
    version = eng.installed_version(run)
    up = health(LOOPBACK, profile.port)
    polluted = settings_has_proxy_env(settings_path if settings_path is not None else settings_path_default())
    gate = gate_fn(f"http://{LOOPBACK}:{profile.port}", profile.main) if up else None
    return run_translator_checks(
        installed_version=version, proxy_up=up, profile=profile, settings_polluted=polluted, gate=gate
    )
