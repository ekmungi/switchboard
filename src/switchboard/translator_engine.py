# translator_engine.py - Engine interface + LiteLLM adapter for the local translator.
#
# The translator turns Claude Code's Anthropic /v1/messages traffic into OpenRouter
# (OpenAI-door) calls. The engine is swappable (SPEC-005 R2); LiteLLM is the locked
# default (R-008, pinned below). This module owns three engine concerns: (1) generate
# the proxy config from a tier map -- cost-safe by construction (R3a: never a
# passthrough wildcard, never an anthropic/* Claude-priced target); (2) build the
# launch argv + env (R11: PYTHONUTF8=1 on Windows); (3) install/pin the engine.
# It performs no I/O beyond the injected subprocess runner and no printing.

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .cost_safety import unsafe_reason

PIN: str = "1.81.14"
"""Locked LiteLLM version (R-008): tool_use args survive streaming here; later pins regress."""

PACKAGE: str = "litellm[proxy]"
"""PyPI spec installed into the engine venv (proxy extras include the CLI + server)."""

LIVELINESS_PATH: str = "/health/liveliness"
"""LiteLLM proxy readiness endpoint (returns 200 once the server is serving)."""

_OPENROUTER_PREFIX: str = "openrouter/"
"""LiteLLM provider prefix that routes a model id to OpenRouter's OpenAI door."""


class EngineError(Exception):
    """Raised when an engine install/probe subprocess fails."""


class EngineConfigError(ValueError):
    """Raised when a requested config would be unsafe or is malformed (R3a)."""


@dataclass(frozen=True)
class InstallResult:
    """Outcome of ensure_installed.

    Fields:
        action:  'present' when the pinned engine was already installed,
                 'installed' when this call installed it.
        version: The engine version now in place (always the pin on success).
    """

    action: str
    version: str


class Engine(Protocol):
    """The swappable translator-engine interface the lifecycle layer drives (R2)."""

    def generate_config(self, tier_map: Mapping[str, str], catch_all: str) -> str: ...
    def spawn_argv(self, config_path: Path, host: str, port: int) -> list[str]: ...
    def spawn_env(self, base_env: Mapping[str, str], api_key: str) -> dict[str, str]: ...
    def ensure_installed(self, run: Callable[..., object]) -> InstallResult: ...
    def installed_version(self, run: Callable[..., object]) -> str | None: ...
    def health_path(self) -> str: ...


def _reject_target(tier: str, target: str) -> None:
    """Raise EngineConfigError if *target* is cost-unsafe (delegates to cost_safety).

    Uses the same predicate `sb doctor` asserts with (R3a/R5a), so a target the
    generator accepts is exactly one doctor will not flag later.
    """
    reason = unsafe_reason(target)
    if reason:
        raise EngineConfigError(f"tier {tier!r}: {reason} (R3a)")


def _reject_unsafe(tier_map: Mapping[str, str], catch_all: str) -> None:
    """Validate the whole mapping (every tier + the catch-all) before emitting config."""
    if not tier_map:
        raise EngineConfigError(
            "tier_map is empty; every Claude tier must map to an explicit OpenRouter model"
        )
    for tier, target in tier_map.items():
        _reject_target(tier, target)
    _reject_target("*", catch_all)


@dataclass(frozen=True)
class LiteLLMEngine:
    """LiteLLM adapter: config generation, launch vector, and pinned install.

    Fields:
        engine_dir:    uv-managed venv directory holding the pinned litellm.
        platform_name: os.name override ('nt'/'posix') for venv layout; defaults
                       to the host at call time.
        pin:           Locked litellm version (PIN).
        package:       PyPI spec installed into the venv (PACKAGE).
        name:          Engine identifier (for the swappable-engine slot).
    """

    engine_dir: Path
    platform_name: str | None = None
    pin: str = PIN
    package: str = PACKAGE
    name: str = "litellm"

    # -- config generation (R3a) --------------------------------------------

    def generate_config(self, tier_map: Mapping[str, str], catch_all: str) -> str:
        """Return LiteLLM proxy YAML mapping every tier + a cheap catch-all.

        Each Claude-tier string Claude Code emits becomes an explicit model_name
        entry routing to openrouter/<id>; a final model_name "*" entry routes any
        unanticipated string to the concrete *catch_all* model (never a wildcard).
        Refuses to emit an anthropic/* or passthrough target (R3a).

        Args:
            tier_map:  Claude model string -> bare OpenRouter model id.
            catch_all: Bare OpenRouter model id for the "*" catch-all entry.

        Returns:
            YAML text suitable for `litellm --config`.

        Raises:
            EngineConfigError: on an empty map or any unsafe target.
        """
        _reject_unsafe(tier_map, catch_all)
        entries = list(tier_map.items()) + [("*", catch_all)]
        lines = [
            "# Generated by switchboard -- do not edit by hand.",
            "# Explicit Claude-tier -> OpenRouter maps + a concrete cheap catch-all",
            "# (never a passthrough wildcard, never anthropic/*), so every tier and",
            "# every spawned subagent routes to a cheap model (SPEC-005 R3a).",
            "model_list:",
        ]
        for name, target in entries:
            lines += [
                f"  - model_name: {json.dumps(name)}",
                "    litellm_params:",
                f"      model: {_OPENROUTER_PREFIX}{target}",
                "      api_key: os.environ/OPENROUTER_API_KEY",
            ]
        lines += ["", "litellm_settings:", "  drop_params: true", ""]
        return "\n".join(lines)

    # -- launch vector (R11) ------------------------------------------------

    def _is_nt(self) -> bool:
        """True when targeting Windows venv layout (Scripts/, .exe)."""
        import os

        return (self.platform_name or os.name) == "nt"

    def _scripts_dir(self) -> Path:
        """Return the venv's executables directory (Scripts on Windows, bin on POSIX)."""
        return self.engine_dir / ("Scripts" if self._is_nt() else "bin")

    def _python(self) -> Path:
        """Return the venv's python interpreter path."""
        return self._scripts_dir() / ("python.exe" if self._is_nt() else "python")

    def _litellm(self) -> Path:
        """Return the venv's litellm proxy launcher path."""
        return self._scripts_dir() / ("litellm.exe" if self._is_nt() else "litellm")

    def spawn_argv(self, config_path: Path, host: str, port: int) -> list[str]:
        """Return the argv that launches the proxy bound to host:port with *config_path*."""
        return [
            str(self._litellm()),
            "--config",
            str(config_path),
            "--host",
            host,
            "--port",
            str(port),
        ]

    def spawn_env(self, base_env: Mapping[str, str], api_key: str) -> dict[str, str]:
        """Return a new env dict adding PYTHONUTF8=1 (R11) and the OpenRouter key.

        PYTHONUTF8=1 is mandatory on Windows: LiteLLM's startup banner crashes with
        UnicodeEncodeError under cp1252 when stdout is redirected (always, for a
        daemonized proxy). Inherited ANTHROPIC_* vars are scrubbed: the proxy is an
        OpenRouter translator and must never see a (self-referential) ANTHROPIC_BASE_URL
        or a stray Claude key. The base env is never mutated.
        """
        clean = {k: v for k, v in dict(base_env).items() if not k.startswith("ANTHROPIC_")}
        return {**clean, "PYTHONUTF8": "1", "OPENROUTER_API_KEY": api_key}

    def health_path(self) -> str:
        """Return the proxy's readiness endpoint path."""
        return LIVELINESS_PATH

    # -- install / pin (R7/R9) ----------------------------------------------

    def installed_version(self, run: Callable[..., object] = subprocess.run) -> str | None:
        """Return the litellm version importable in the engine venv, or None.

        Returns None when the venv python is absent or litellm cannot be imported;
        never raises. Used both to gate install and by doctor's pinned-version check.
        """
        py = self._python()
        if not py.exists():
            return None
        proc = run(
            [str(py), "-c", "import litellm, sys; sys.stdout.write(litellm.__version__)"],
            capture_output=True,
            text=True,
        )
        if getattr(proc, "returncode", 1) != 0:
            return None
        out = (getattr(proc, "stdout", "") or "").strip()
        return out or None

    def ensure_installed(
        self, run: Callable[..., object] = subprocess.run, uv: str = "uv"
    ) -> InstallResult:
        """Ensure the pinned engine is installed in a uv-managed venv (idempotent).

        Fast path: if the pin is already importable, return 'present' without
        touching anything. Otherwise create the venv and install the pinned
        package, raising EngineError on any command failure.

        Args:
            run: Injected subprocess.run-like callable (tests pass a recorder).
            uv:  The uv executable name/path.

        Returns:
            InstallResult describing whether it was already present or installed.
        """
        if self.installed_version(run) == self.pin:
            return InstallResult(action="present", version=self.pin)
        self._run_checked(run, [uv, "venv", str(self.engine_dir)])
        self._run_checked(
            run,
            [uv, "pip", "install", "--python", str(self._python()), f"{self.package}=={self.pin}"],
        )
        return InstallResult(action="installed", version=self.pin)

    @staticmethod
    def _run_checked(run: Callable[..., object], argv: list[str]) -> object:
        """Run *argv* and raise EngineError on a non-zero exit.

        A missing returncode is treated as failure (fail-safe): a malformed proc
        must raise loudly, never be mistaken for success.
        """
        proc = run(argv, capture_output=True, text=True)
        if getattr(proc, "returncode", 1) != 0:
            stderr = getattr(proc, "stderr", "") or ""
            raise EngineError(f"command failed ({' '.join(argv)}): {stderr.strip()}")
        return proc
