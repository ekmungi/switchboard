# translator_lifecycle.py - Local proxy daemon: start / stop / status / health (SPEC-005 R2).
#
# Manages one LiteLLM proxy bound to 127.0.0.1:<port>. Started on demand and REUSED
# (daemonized) so the ~10s cold start is paid once across `sb code` launches. The
# engine subprocess is spawned detached with its stdout/stderr redirected to a log
# file and PYTHONUTF8=1 in its env (R11: without it LiteLLM's banner crashes under
# cp1252 when redirected). Never binds anything but loopback. All external effects
# (socket, HTTP, spawn, kill, sleep) are injected so the units stay hermetic.

import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .translator_engine import Engine, LIVELINESS_PATH

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
"""Hosts start() will bind (SPEC-005 R2: loopback only, never a public interface)."""


@dataclass(frozen=True)
class ProxyStatus:
    """Snapshot of the proxy daemon's state.

    Fields:
        running: True when the proxy answers on host:port.
        pid:     PID recorded in the pidfile, or None when unknown.
        host:    Loopback host the proxy is bound to.
        port:    Port the proxy is bound to.
        reused:  True when start() found an already-running daemon and reused it.
    """

    running: bool
    pid: int | None
    host: str
    port: int
    reused: bool = False


def proxy_running(host: str = "127.0.0.1", port: int = 4000) -> bool:
    """Return True iff a TCP connect to host:port succeeds (the port is bound).

    Side effects: one short-timeout connect attempt; nothing mutated.
    """
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def proxy_health(
    host: str = "127.0.0.1",
    port: int = 4000,
    opener: Callable[..., object] = urllib.request.urlopen,
    path: str = LIVELINESS_PATH,
) -> bool:
    """Return True iff the proxy answers its liveliness endpoint with a 2xx.

    Stronger than proxy_running: a bound-but-not-ready proxy (mid cold-start)
    fails this. Uses stdlib urllib so switchboard adds no runtime dependency.

    Args:
        opener: Injected urlopen-like callable (tests pass a stub).
        path:   Liveliness path (defaults to the engine's endpoint).
    """
    url = f"http://{host}:{port}{path}"
    try:
        with opener(url, timeout=2) as resp:
            code = getattr(resp, "status", None) or getattr(resp, "code", 0)
            return 200 <= int(code) < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# pidfile helpers - the daemon-reuse ledger
# ---------------------------------------------------------------------------


def read_pid(pidfile: Path) -> int | None:
    """Return the PID stored in *pidfile*, or None if absent/unparseable."""
    try:
        return int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(pidfile: Path, pid: int) -> None:
    """Write *pid* to *pidfile*, creating the parent directory if needed."""
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(pid), encoding="utf-8")


def clear_pid(pidfile: Path) -> None:
    """Remove *pidfile* if it exists (safe to call when already gone)."""
    pidfile.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# detach vector
# ---------------------------------------------------------------------------


def _creationflags(platform_name: str | None = None) -> int:
    """Return Windows detach creation flags (0 on POSIX).

    DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP let the proxy outlive the `sb`
    process that spawned it. getattr-guarded so importing on POSIX is safe.
    """
    if (platform_name or os.name) != "nt":
        return 0
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return detached | new_group


def _new_session(platform_name: str | None = None) -> bool:
    """Return True on POSIX so the child gets its own session (setsid)."""
    return (platform_name or os.name) != "nt"


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def status(
    host: str, port: int, pidfile: Path, is_up: Callable[[], bool] | None = None
) -> ProxyStatus:
    """Return a ProxyStatus for the proxy at host:port using *pidfile* for the PID."""
    probe = is_up or (lambda: proxy_running(host, port))
    running = probe()
    return ProxyStatus(running=running, pid=read_pid(pidfile), host=host, port=port)


def start(
    engine: Engine,
    *,
    config_path: Path,
    host: str,
    port: int,
    pidfile: Path,
    logfile: Path,
    api_key: str,
    base_env: dict[str, str] | None = None,
    spawn: Callable[..., object] = subprocess.Popen,
    is_up: Callable[[], bool] | None = None,
    sleep: Callable[[float], object] = time.sleep,
    attempts: int = 60,
    delay: float = 0.5,
    platform_name: str | None = None,
) -> ProxyStatus:
    """Ensure the proxy is up, reusing a running daemon or spawning a fresh one.

    Reuse (R2): if the proxy already answers health, return immediately with
    reused=True and never spawn. Otherwise spawn the engine detached, redirect its
    output to *logfile*, record the PID, and poll readiness up to *attempts* *
    *delay* -- bailing early if the child exits.

    Readiness uses HTTP health (`proxy_health`), not a bare TCP connect: LiteLLM
    binds the port early in its ~10s cold start, so a TCP probe would report "up"
    before the proxy can actually serve, and the first real request would fail.

    Args:
        engine:      Engine adapter providing spawn_argv/spawn_env.
        config_path: Generated proxy config to launch with.
        host/port:   Loopback bind target (host must be a loopback address).
        pidfile:     Where the spawned PID is recorded (daemon-reuse ledger).
        logfile:     Redirected stdout/stderr target (why PYTHONUTF8 matters).
        api_key:     OpenRouter key injected into the engine env.
        base_env:    Base environment (defaults to a copy of os.environ).
        spawn/is_up/sleep: Injected seams for hermetic testing.

    Returns:
        ProxyStatus: reused=True when an existing daemon was reused; running
        reflects whether the proxy answered health within the readiness budget.

    Raises:
        ValueError: when *host* is not a loopback address (R2: loopback only).
    """
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"refusing to bind non-loopback host {host!r} (SPEC-005 R2: loopback only)")

    probe = is_up or (lambda: proxy_health(host, port))
    if probe():
        return ProxyStatus(running=True, pid=read_pid(pidfile), host=host, port=port, reused=True)

    env = engine.spawn_env(os.environ if base_env is None else base_env, api_key)
    argv = engine.spawn_argv(config_path, host, port)
    logfile.parent.mkdir(parents=True, exist_ok=True)
    log = open(logfile, "ab")  # noqa: SIM115 - handed to the child; closed below
    try:
        proc = spawn(
            argv,
            env=dict(env),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=_creationflags(platform_name),
            start_new_session=_new_session(platform_name),
            close_fds=True,
        )
    finally:
        log.close()

    write_pid(pidfile, proc.pid)  # persist before polling so a slow/dead proxy stays killable
    for _ in range(attempts):
        if probe():
            return ProxyStatus(running=True, pid=proc.pid, host=host, port=port, reused=False)
        if proc.poll() is not None:  # child exited (bad config / missing binary) -> fail fast
            return ProxyStatus(running=False, pid=proc.pid, host=host, port=port, reused=False)
        sleep(delay)
    return ProxyStatus(running=False, pid=proc.pid, host=host, port=port, reused=False)


def stop(
    pidfile: Path,
    host: str,
    port: int,
    killer: Callable[[int, int], object] = os.kill,
    is_up: Callable[[], bool] | None = None,
) -> bool:
    """Terminate the recorded proxy PID and clear the pidfile.

    Returns True when a live PID was signaled, False when there was no PID or the
    process was already gone. The pidfile is always cleared (stale entries removed).

    Args:
        killer: Injected os.kill-like callable. On Windows os.kill with SIGTERM
                maps to TerminateProcess, which stops the daemon unconditionally.
    """
    pid = read_pid(pidfile)
    stopped = False
    if pid is not None:
        try:
            killer(pid, signal.SIGTERM)
            stopped = True
        except (ProcessLookupError, OSError):
            stopped = False
    clear_pid(pidfile)
    return stopped
