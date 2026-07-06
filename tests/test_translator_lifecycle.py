# test_translator_lifecycle.py - Proxy daemon lifecycle (SPEC-005 R2/R11).
#
# Hermetic: socket monkeypatched, HTTP opener injected, subprocess spawn injected,
# readiness probe + sleep injected, all paths under tmp_path. No port is ever bound.

import socket
import subprocess
import urllib.error
from unittest.mock import MagicMock

import pytest

from switchboard import translator_lifecycle as tl


class FakeEngine:
    """Minimal engine exposing just the launch vector the lifecycle drives."""

    def spawn_argv(self, config_path, host, port):
        return ["ENGINE", "--config", str(config_path), "--host", host, "--port", str(port)]

    def spawn_env(self, base_env, api_key):
        return {**dict(base_env), "PYTHONUTF8": "1", "OPENROUTER_API_KEY": api_key}


class FakeProc:
    """Stand-in for a spawned Popen with a pid and a poll() liveness result."""

    def __init__(self, pid=4321, poll_result=None):
        self.pid = pid
        self._poll = poll_result  # None = still running; int = exit code

    def poll(self):
        return self._poll


def probe_seq(values):
    """Return a zero-arg probe yielding *values* in order (last value repeats)."""
    state = {"i": 0}

    def _probe():
        v = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return v

    return _probe


def host_probe_seq(values):
    """Like probe_seq but with a (host, port) signature (for monkeypatching probes)."""
    state = {"i": 0}

    def _probe(host, port):
        v = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return v

    return _probe


# ---------------------------------------------------------------------------
# proxy_running - TCP liveness
# ---------------------------------------------------------------------------


class TestProxyRunning:
    """Tests for proxy_running(host, port)."""

    def test_true_when_connection_succeeds(self, monkeypatch):
        monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: MagicMock())
        assert tl.proxy_running("127.0.0.1", 4000) is True

    def test_false_on_oserror(self, monkeypatch):
        def _fail(addr, timeout):
            raise OSError("refused")
        monkeypatch.setattr(socket, "create_connection", _fail)
        assert tl.proxy_running("127.0.0.1", 4000) is False

    def test_probes_given_host_port(self, monkeypatch):
        captured = {}
        def _capture(addr, timeout):
            captured["addr"] = addr
            return MagicMock()
        monkeypatch.setattr(socket, "create_connection", _capture)
        tl.proxy_running("127.0.0.1", 4321)
        assert captured["addr"] == ("127.0.0.1", 4321)


# ---------------------------------------------------------------------------
# proxy_health - HTTP readiness
# ---------------------------------------------------------------------------


class TestProxyHealth:
    """Tests for proxy_health(host, port, opener)."""

    def test_true_on_2xx(self):
        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        assert tl.proxy_health("127.0.0.1", 4000, opener=lambda url, timeout: Resp()) is True

    def test_false_on_urlerror(self):
        def _boom(url, timeout):
            raise urllib.error.URLError("down")
        assert tl.proxy_health("127.0.0.1", 4000, opener=_boom) is False

    def test_false_on_non_2xx(self):
        """A bound-but-erroring proxy (5xx) is not healthy."""
        class Resp:
            status = 503
            def __enter__(self): return self
            def __exit__(self, *a): return False
        assert tl.proxy_health("127.0.0.1", 4000, opener=lambda url, timeout: Resp()) is False


# ---------------------------------------------------------------------------
# pidfile helpers
# ---------------------------------------------------------------------------


class TestPidfile:
    """Tests for read_pid / write_pid / clear_pid."""

    def test_write_then_read_roundtrips(self, tmp_path):
        pidfile = tmp_path / "sub" / "proxy.pid"
        tl.write_pid(pidfile, 1234)
        assert tl.read_pid(pidfile) == 1234

    def test_read_none_when_absent(self, tmp_path):
        assert tl.read_pid(tmp_path / "nope.pid") is None

    def test_read_none_on_garbage(self, tmp_path):
        pidfile = tmp_path / "proxy.pid"
        pidfile.write_text("not-a-pid", encoding="utf-8")
        assert tl.read_pid(pidfile) is None

    def test_clear_removes_and_is_safe_when_absent(self, tmp_path):
        pidfile = tmp_path / "proxy.pid"
        pidfile.write_text("1234", encoding="utf-8")
        tl.clear_pid(pidfile)
        assert not pidfile.exists()
        tl.clear_pid(pidfile)  # no raise when already gone


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    """Tests for status(host, port, pidfile, is_up)."""

    def test_reports_running_and_pid(self, tmp_path):
        pidfile = tmp_path / "proxy.pid"
        tl.write_pid(pidfile, 999)
        st = tl.status("127.0.0.1", 4000, pidfile, is_up=lambda: True)
        assert st.running is True and st.pid == 999
        assert st.host == "127.0.0.1" and st.port == 4000

    def test_reports_down(self, tmp_path):
        st = tl.status("127.0.0.1", 4000, tmp_path / "proxy.pid", is_up=lambda: False)
        assert st.running is False and st.pid is None


# ---------------------------------------------------------------------------
# start - daemon reuse + fresh spawn + readiness
# ---------------------------------------------------------------------------


class TestStart:
    """Tests for start(engine, ...)."""

    def _paths(self, tmp_path):
        return tmp_path / "proxy.yaml", tmp_path / "proxy.pid", tmp_path / "logs" / "proxy.log"

    def test_reuses_running_daemon_without_spawning(self, tmp_path):
        """R2: an already-up proxy is reused; spawn is never called (cold start paid once)."""
        cfg, pidfile, log = self._paths(tmp_path)
        tl.write_pid(pidfile, 111)
        spawn = MagicMock()
        st = tl.start(
            FakeEngine(), config_path=cfg, host="127.0.0.1", port=4000,
            pidfile=pidfile, logfile=log, api_key="sk-or", spawn=spawn,
            is_up=lambda: True,
        )
        assert st.reused is True and st.running is True and st.pid == 111
        spawn.assert_not_called()

    def test_fresh_start_spawns_with_utf8_env_and_becomes_ready(self, tmp_path):
        """A down proxy is spawned with PYTHONUTF8=1 (R11) and polled until ready."""
        cfg, pidfile, log = self._paths(tmp_path)
        captured = {}
        def spawn(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakeProc(pid=4321)
        st = tl.start(
            FakeEngine(), config_path=cfg, host="127.0.0.1", port=4000,
            pidfile=pidfile, logfile=log, api_key="sk-or", spawn=spawn,
            is_up=probe_seq([False, True]), sleep=lambda s: None, attempts=5,
        )
        assert st.running is True and st.reused is False and st.pid == 4321
        assert tl.read_pid(pidfile) == 4321
        assert captured["kwargs"]["env"]["PYTHONUTF8"] == "1"
        assert captured["kwargs"]["env"]["OPENROUTER_API_KEY"] == "sk-or"
        assert captured["argv"][0] == "ENGINE"
        assert log.exists()  # stdout/stderr redirected here (why R11 matters)

    def test_fresh_start_reports_not_running_when_never_ready(self, tmp_path):
        """If the proxy never answers within attempts, status is running=False."""
        cfg, pidfile, log = self._paths(tmp_path)
        slept = []
        st = tl.start(
            FakeEngine(), config_path=cfg, host="127.0.0.1", port=4000,
            pidfile=pidfile, logfile=log, api_key="sk-or",
            spawn=lambda argv, **kw: FakeProc(pid=7),
            is_up=probe_seq([False]), sleep=lambda s: slept.append(s), attempts=3,
        )
        assert st.running is False and st.pid == 7
        assert len(slept) == 3  # polled the full budget
        assert tl.read_pid(pidfile) == 7  # PID persisted so a later stop can kill the orphan

    def test_readiness_waits_on_health_not_tcp_bind(self, tmp_path, monkeypatch):
        """Cold-start correctness: readiness must use HTTP health, not a bare TCP bind.

        The port binds early in LiteLLM's ~10s startup, so a TCP probe reports 'up'
        before the proxy can serve. We make TCP lie (always up) and health tell the
        truth (ready only on the 2nd poll); a correct start() spawns and waits on health.
        """
        cfg, pidfile, log = self._paths(tmp_path)
        monkeypatch.setattr(tl, "proxy_running", lambda host, port: True)  # decoy
        monkeypatch.setattr(tl, "proxy_health", host_probe_seq([False, True]))
        spawned = []
        st = tl.start(
            FakeEngine(), config_path=cfg, host="127.0.0.1", port=4000,
            pidfile=pidfile, logfile=log, api_key="sk-or",
            spawn=lambda argv, **kw: spawned.append(1) or FakeProc(pid=9),
            sleep=lambda s: None, attempts=5,
        )
        # If start() had used the TCP decoy, it would have "reused" and never spawned.
        assert spawned == [1]
        assert st.running is True and st.pid == 9

    def test_dead_child_fails_fast(self, tmp_path):
        """A child that exits immediately (bad config/missing binary) fails fast,
        not after the full readiness budget."""
        cfg, pidfile, log = self._paths(tmp_path)
        slept = []
        st = tl.start(
            FakeEngine(), config_path=cfg, host="127.0.0.1", port=4000,
            pidfile=pidfile, logfile=log, api_key="sk-or",
            spawn=lambda argv, **kw: FakeProc(pid=13, poll_result=1),
            is_up=lambda: False, sleep=lambda s: slept.append(s), attempts=10,
        )
        assert st.running is False and st.pid == 13
        assert slept == []  # bailed on the first poll seeing the dead child

    def test_refuses_non_loopback_host(self, tmp_path):
        """R2: start() refuses to bind a non-loopback host (never spawns)."""
        cfg, pidfile, log = self._paths(tmp_path)
        spawn = MagicMock()
        with pytest.raises(ValueError):
            tl.start(
                FakeEngine(), config_path=cfg, host="0.0.0.0", port=4000,
                pidfile=pidfile, logfile=log, api_key="sk-or", spawn=spawn,
                is_up=lambda: False,
            )
        spawn.assert_not_called()


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


class TestStop:
    """Tests for stop(pidfile, host, port, killer)."""

    def test_terminates_pid_and_clears_pidfile(self, tmp_path):
        pidfile = tmp_path / "proxy.pid"
        tl.write_pid(pidfile, 555)
        killed = []
        ok = tl.stop(pidfile, "127.0.0.1", 4000, killer=lambda pid, sig: killed.append((pid, sig)))
        assert ok is True
        assert killed and killed[0][0] == 555
        assert not pidfile.exists()

    def test_returns_false_when_no_pid(self, tmp_path):
        killer = MagicMock()
        ok = tl.stop(tmp_path / "absent.pid", "127.0.0.1", 4000, killer=killer)
        assert ok is False
        killer.assert_not_called()

    def test_returns_false_when_process_already_gone(self, tmp_path):
        pidfile = tmp_path / "proxy.pid"
        tl.write_pid(pidfile, 555)
        def _gone(pid, sig):
            raise ProcessLookupError
        ok = tl.stop(pidfile, "127.0.0.1", 4000, killer=_gone)
        assert ok is False
        assert not pidfile.exists()  # stale pidfile still cleared

    def test_returns_false_on_oserror_kill(self, tmp_path):
        """On Windows os.kill on a dead/invalid PID raises a bare OSError (not
        ProcessLookupError); stop() must swallow it and still clear the pidfile."""
        pidfile = tmp_path / "proxy.pid"
        tl.write_pid(pidfile, 555)
        def _oserr(pid, sig):
            raise OSError("access denied")
        ok = tl.stop(pidfile, "127.0.0.1", 4000, killer=_oserr)
        assert ok is False
        assert not pidfile.exists()


# ---------------------------------------------------------------------------
# _creationflags - Windows detach vector
# ---------------------------------------------------------------------------


class TestCreationFlags:
    """Tests for _creationflags(platform_name)."""

    def test_posix_is_zero(self):
        assert tl._creationflags("posix") == 0

    def test_nt_uses_detach_flags(self):
        expected = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        assert tl._creationflags("nt") == expected


class TestNewSession:
    """Tests for _new_session(platform_name) - the POSIX half of the detach vector."""

    def test_posix_true_nt_false(self):
        """POSIX children setsid (survive the parent); Windows uses creationflags instead."""
        assert tl._new_session("posix") is True
        assert tl._new_session("nt") is False
