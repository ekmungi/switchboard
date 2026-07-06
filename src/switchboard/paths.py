# paths.py - Switchboard's own home directory and the local translator's runtime paths.
#
# The embedded translator (engine venv, generated proxy config, pidfile, log) lives
# entirely under one switchboard home dir (default ~/.switchboard), kept separate from
# ~/.claude and CCR's store so nothing global is touched (SPEC-005 R4). Every path is
# derived from home_dir(); tests redirect the whole tree by passing root=tmp_path.

from pathlib import Path

APP_DIRNAME: str = ".switchboard"
"""Switchboard's home folder name under the user's home directory."""


def home_dir(root: Path | None = None) -> Path:
    """Return switchboard's home directory (default ~/.switchboard).

    Args:
        root: Base directory to place the home dir under; defaults to the
            user's home. Tests pass tmp_path to redirect the whole tree.

    Returns:
        The <root>/.switchboard path (not created on disk).
    """
    base = root if root is not None else Path.home()
    return base / APP_DIRNAME


def engine_dir(root: Path | None = None) -> Path:
    """Return the uv-managed venv directory that holds the pinned engine."""
    return home_dir(root) / "engine"


def proxy_config_path(root: Path | None = None) -> Path:
    """Return the path of the generated engine (proxy) config file."""
    return home_dir(root) / "proxy.yaml"


def proxy_pidfile(root: Path | None = None) -> Path:
    """Return the path of the running proxy's pidfile."""
    return home_dir(root) / "proxy.pid"


def proxy_logfile(root: Path | None = None) -> Path:
    """Return the path of the proxy's redirected stdout/stderr log."""
    return home_dir(root) / "proxy.log"
