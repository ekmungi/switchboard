# keystore.py - Read the OpenRouter key from ~/.env_claude (SPEC-005 R6).
#
# v1 secret storage is the file the key already lives in: ~/.env_claude holds
# OPENROUTER_API_KEY under the exact name LiteLLM expects (R-008), so no separate
# OS credential store is needed. The key is NEVER written to ~/.claude/settings.json
# and NEVER printed or logged -- callers pass the returned value straight into the
# proxy's env. Uses only stdlib (no python-dotenv dependency).

import os
from pathlib import Path
from typing import Mapping


class KeystoreError(Exception):
    """Raised when a required key cannot be found."""


def env_file_path() -> Path:
    """Return the default env file path (~/.env_claude)."""
    return Path.home() / ".env_claude"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file into a dict (no external dependency).

    Tolerates `export KEY=value`, surrounding single/double quotes, spaces around
    '=', blank lines, and '#' comment lines. On any read error returns {} (the
    caller then falls back to the environ).

    Args:
        path: The env file to parse.

    Returns:
        Mapping of key -> value for every assignment line.
    """
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]  # strip a single layer of matching quotes
        if key:
            result[key] = value
    return result


def read_key(
    name: str = "OPENROUTER_API_KEY",
    path: Path | None = None,
    environ: Mapping[str, str] = os.environ,
) -> str | None:
    """Return *name*'s value from the env file, falling back to the process environ.

    The file (~/.env_claude) is the source of truth (R6); an exported value is
    only used when the file lacks the key. Returns None when absent everywhere.
    Never prints or logs the value.

    Args:
        name:    Environment variable name to read (default OPENROUTER_API_KEY).
        path:    Env file to read (defaults to env_file_path()).
        environ: Process environment (injected for tests).

    Returns:
        The key value, or None if not found.
    """
    env_path = path if path is not None else env_file_path()
    value = _parse_env_file(env_path).get(name)
    if value:
        return value
    return environ.get(name) or None


def require_key(
    name: str = "OPENROUTER_API_KEY",
    path: Path | None = None,
    environ: Mapping[str, str] = os.environ,
) -> str:
    """Return *name*'s value or raise KeystoreError (for flows that cannot proceed).

    Raises:
        KeystoreError: when the key is absent from both the file and the environ.
    """
    value = read_key(name, path=path, environ=environ)
    if not value:
        where = path if path is not None else env_file_path()
        raise KeystoreError(f"{name} not found in {where} or the environment")
    return value
