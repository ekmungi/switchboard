# ccr_lifecycle.py - CCR v3 daemon probing and gateway reload semantics.
#
# v3 has no `ccr restart`; the CLI is start/stop/<profile> only, and `ccr stop`
# can only kill a daemon it started itself (recorded in CONFIGDIR/service.json).
# A daemon spawned by the Electron app has no service.json -- the only safe
# "reload" there is telling the user to restart the app (R-006 s4, SPEC-004 R6).

import os
import socket
import subprocess
from typing import Callable

from .ccr_store import config_dir

SERVICE_PATH = config_dir() / "service.json"
"""State file `ccr start` writes; its presence marks a CLI-managed daemon."""

APP_RESTART_LINE: str = (
    "Gateway config changed: restart the Claude Code Router app to apply it "
    "(daemon is app-owned or not running; `ccr stop/start` cannot manage it)."
)
"""Instruction printed when we cannot reload the gateway ourselves."""


def ccr_running(host: str = "127.0.0.1", port: int = 3456) -> bool:
    """Return True iff the CCR daemon answers a TCP connect on host:port.

    Args:
        host: Daemon host (v3 callers pass the blob's HOST).
        port: Daemon port (v3 callers pass the blob's PORT).

    Side effects: one short-timeout TCP connect attempt; nothing mutated.
    """
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def service_owned() -> bool:
    """Return True iff a `ccr start`-managed daemon state file exists."""
    return SERVICE_PATH.exists()


def _ccr_cmd(action: str, platform_name: str | None) -> list[str]:
    """Build the argv for `ccr <action>` (cmd shim on Windows, never shell=True)."""
    if (platform_name or os.name) == "nt":
        return ["cmd", "/c", "ccr", action]
    return ["ccr", action]


def reload_gateway(
    run: Callable[..., object] = subprocess.run, platform_name: str | None = None
) -> list[str]:
    """Reload the CCR gateway so a regenerated gateway config takes effect.

    Only a CLI-managed daemon (service.json present) can be cycled with
    `ccr stop` + `ccr start`; otherwise return the app-restart instruction.
    Needed only after gateway-relevant config changes (provider whitelist).

    Args:
        run: Injected subprocess runner (tests pass a recorder).
        platform_name: os.name override for tests ('nt'/'posix').

    Returns:
        Printable report lines describing what happened / what the user must do.
    """
    if not service_owned():
        return [APP_RESTART_LINE]
    run(_ccr_cmd("stop", platform_name), check=False)
    run(_ccr_cmd("start", platform_name), check=False)
    return ["Gateway reloaded (ccr stop + ccr start)."]


def app_advisory(daemon_up: bool) -> str | None:
    """Return the UI-clobber advisory when writing while the daemon is up.

    An Electron UI save replaces the whole config blob from the UI's
    in-memory state, so store writes made mid-edit can be lost (R-006 s4).

    Args:
        daemon_up: Result of ccr_running() at write time.

    Returns:
        Advisory line when daemon_up, else None.
    """
    if not daemon_up:
        return None
    return (
        "Note: the CCR app/daemon is running -- avoid saving settings in its "
        "UI right now (a UI save replaces the whole config and would undo this)."
    )
