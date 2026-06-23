# ccr_config.py - CCR config read, merge, write, and service-status helpers.
#
# Provides pure (non-mutating) functions for reading and updating the
# claude-code-router config file, plus thin wrappers to probe/restart the
# CCR daemon. The CLI (switchboard.py) remains untouched until Task 3.
# ---------------------------------------------------------------------------

import json
import os
import socket
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_PATH: Path = Path.home() / ".claude-code-router" / "config.json"
"""Absolute path to the CCR config file."""

PROVIDER: str = "openrouter"
"""The CCR provider prefix used in role values (e.g. 'openrouter,<model>')."""

ROLES: list[str] = ["default", "background", "think", "longContext", "webSearch"]
"""All five CCR routing roles, in canonical order."""


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def read_config() -> dict:
    """Read the CCR config file and return it as a dict.

    Returns an empty dict when the file does not exist, so callers never
    need to guard against a missing config.
    """
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(cfg: dict) -> None:
    """Write *cfg* back to CONFIG_PATH as pretty (2-space-indented) JSON.

    Args:
        cfg: The full config dict to persist (including Providers, Router, etc.).
    """
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure update helpers (all return NEW dicts; inputs are never mutated)
# ---------------------------------------------------------------------------


def set_all_roles(cfg: dict, model_id: str, online: bool = False) -> dict:
    """Return a new cfg with every role in ROLES set to the given model.

    For each role the value is ``f"{PROVIDER},{model_id}"``.  When *online*
    is True, the ``webSearch`` role gets a ``:online`` suffix appended.
    All non-role keys already present in ``Router`` (e.g. ``longContextThreshold``,
    ``image``) are preserved.  Top-level keys (including ``Providers``) are
    not touched.

    Args:
        cfg:      The current config dict (not modified).
        model_id: The OpenRouter model id (e.g. ``"deepseek/deepseek-chat"``).
        online:   When True, ``webSearch`` value ends with ``:online``.

    Returns:
        A new config dict with all roles updated.
    """
    base_value = f"{PROVIDER},{model_id}"
    # Copy the existing Router to preserve non-role keys; then overwrite roles.
    new_router = dict(cfg.get("Router", {}))
    for role in ROLES:
        if role == "webSearch" and online:
            new_router[role] = f"{base_value}:online"
        else:
            new_router[role] = base_value
    return {**cfg, "Router": new_router}


def set_websearch_online(cfg: dict, on: bool) -> dict:
    """Return a new cfg with the ``:online`` suffix toggled on the webSearch role.

    Strips any existing ``:online`` suffix to obtain the base value, then
    appends ``:online`` iff *on* is True.  The model id and all other Router
    keys are preserved.  The function is idempotent and round-trips correctly.

    Args:
        cfg: The current config dict (not modified).
        on:  True to enable ``:online``, False to disable.

    Returns:
        A new config dict with the webSearch role updated.
    """
    new_router = dict(cfg.get("Router", {}))
    current = new_router.get("webSearch", "")
    # Strip existing :online suffix to get the canonical base.
    base = current[: -len(":online")] if current.endswith(":online") else current
    new_router["webSearch"] = f"{base}:online" if on else base
    return {**cfg, "Router": new_router}


def ensure_apikey_blank(cfg: dict) -> dict:
    """Return a new cfg with the top-level APIKEY forced to ``""``.

    Does not read, modify, or copy ``Providers`` -- the secret ``api_key``
    inside ``Providers[0]`` is never touched.

    Args:
        cfg: The current config dict (not modified).

    Returns:
        A new config dict with ``APIKEY`` set to ``""``.
    """
    return {**cfg, "APIKEY": ""}


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


def ccr_running() -> bool:
    """Return True iff the CCR local HTTP server is reachable via TCP.

    Reads HOST and PORT from the config (defaulting to ``"127.0.0.1"`` and
    ``3456``) and attempts a short-timeout connection.  Returns False on any
    ``OSError`` (connection refused, timeout, etc.).

    Side effects: one TCP connect attempt; no mutations to config or state.
    """
    cfg = read_config()
    host: str = cfg.get("HOST", "127.0.0.1")
    port: int = cfg.get("PORT", 3456)
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def restart_ccr() -> None:
    """Restart the CCR service using the platform-appropriate command.

    On Windows (``os.name == 'nt'``), routes through ``cmd.exe`` because
    ``ccr`` is a ``.cmd`` shim.  On POSIX, calls ``ccr`` directly.
    Uses ``check=False`` so a non-zero exit code does not raise.
    Never uses ``shell=True`` to avoid command-injection risks.
    """
    if os.name == "nt":
        cmd = ["cmd", "/c", "ccr", "restart"]
    else:
        cmd = ["ccr", "restart"]
    subprocess.run(cmd, check=False)
