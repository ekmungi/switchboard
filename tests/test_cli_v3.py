# test_cli_v3.py - Tests for the v3 command layer (SPEC-004 R4/R5/R7/R8).
#
# Hermetic: tmp_path SQLite store (fake key), monkeypatched daemon probes,
# catalog and settings injected. The live store is never touched.
# ---------------------------------------------------------------------------

import pytest

from switchboard import ccr_store, ccr_v3, cli_v3
from switchboard.catalog import Model

CAT = [
    Model("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", 1048576, 9e-08, 0.0),
    Model("z-ai/glm-4.6", "GLM 4.6", 202752, 4e-07, 0.0),
    Model("openai/gpt-4o-mini", "GPT-4o mini", 128000, 1.5e-07, 6e-07),
]


@pytest.fixture
def db(v3_db, monkeypatch):
    """The shared conftest v3 store fixture plus quiet lifecycle defaults."""
    monkeypatch.setattr(cli_v3, "ccr_running", lambda host, port: False)
    monkeypatch.setattr(cli_v3, "reload_gateway", lambda: ["(reload requested)"])
    return v3_db


# ---------------------------------------------------------------------------
# use_v3
# ---------------------------------------------------------------------------


class TestUseV3:
    """Tests for use_v3()."""

    def test_pins_model_and_small_fast_in_store(self, db, capsys):
        cli_v3.use_v3("z-ai/glm-4.6", CAT[1])
        blob = ccr_store.load_blob()
        prof = ccr_v3.claude_profile(blob)
        assert prof["model"] == "openrouter/z-ai/glm-4.6"
        assert prof["smallFastModel"] == "openrouter/z-ai/glm-4.6"
        out = capsys.readouterr().out
        assert "CCR-launched session" in out

    def test_whitelisted_model_needs_no_reload(self, db, capsys):
        cli_v3.use_v3("z-ai/glm-4.6", CAT[1])
        out = capsys.readouterr().out
        assert "(reload requested)" not in out

    def test_new_model_appended_and_reload_requested(self, db, capsys):
        cli_v3.use_v3("openai/gpt-4o-mini", CAT[2])
        blob = ccr_store.load_blob()
        assert "openai/gpt-4o-mini" in blob["Providers"][0]["models"]
        out = capsys.readouterr().out
        assert "(reload requested)" in out

    def test_apikey_forced_blank(self, db):
        con_blob = ccr_store.update_blob(lambda b: {**b, "APIKEY": "dirty"})
        assert con_blob["APIKEY"] == "dirty"
        cli_v3.use_v3("z-ai/glm-4.6", CAT[1])
        assert ccr_store.load_blob()["APIKEY"] == ""

    def test_advisory_printed_when_daemon_up(self, db, monkeypatch, capsys):
        monkeypatch.setattr(cli_v3, "ccr_running", lambda host, port: True)
        cli_v3.use_v3("z-ai/glm-4.6", CAT[1])
        assert "UI" in capsys.readouterr().out

    def test_missing_store_exits_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ccr_store, "DB_PATH", tmp_path / "config.sqlite")
        monkeypatch.setattr(cli_v3, "ccr_running", lambda host, port: False)
        with pytest.raises(SystemExit) as exc:
            cli_v3.use_v3("z-ai/glm-4.6", CAT[1])
        assert exc.value.code == 1
        assert "store" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# current_v3
# ---------------------------------------------------------------------------


class TestCurrentV3:
    """Tests for current_v3()."""

    def test_shows_store_and_applied_with_drift(self, db, monkeypatch, capsys):
        monkeypatch.setattr(
            cli_v3, "load_settings", lambda: {"env": {"ANTHROPIC_MODEL": "openrouter/z-ai/glm-4.6"}}
        )
        monkeypatch.setattr(cli_v3, "fetch_models", lambda: CAT)
        cli_v3.current_v3(False)
        out = capsys.readouterr().out
        assert "deepseek/deepseek-v4-flash" in out
        assert "DRIFT" in out

    def test_unreadable_store_reports_not_crashes(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ccr_store, "DB_PATH", tmp_path / "config.sqlite")
        cli_v3.current_v3(False)
        assert "store" in capsys.readouterr().out.lower()

    def test_offline_catalog_notes_skip(self, db, monkeypatch, capsys):
        monkeypatch.setattr(cli_v3, "load_settings", lambda: {})
        def _boom():
            raise OSError("offline")
        monkeypatch.setattr(cli_v3, "fetch_models", _boom)
        cli_v3.current_v3(False)
        assert "catalog unavailable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# doctor_v3
# ---------------------------------------------------------------------------


class TestDoctorV3:
    """Tests for doctor_v3()."""

    def _wire(self, monkeypatch, applied="openrouter/deepseek/deepseek-v4-flash",
              legacy=None):
        monkeypatch.setattr(cli_v3, "ccr_running", lambda host, port: True)
        monkeypatch.setattr(cli_v3, "fetch_models", lambda: CAT)
        monkeypatch.setattr(
            cli_v3, "load_settings",
            lambda: {"env": {"ANTHROPIC_MODEL": applied}} if applied else {},
        )
        monkeypatch.setattr(cli_v3, "legacy_leftovers", lambda: legacy or [])
        monkeypatch.setattr(cli_v3, "current_plan", lambda: None)

    def test_healthy_store_passes(self, db, monkeypatch, capsys):
        self._wire(monkeypatch)
        cli_v3.doctor_v3()  # must not raise SystemExit
        out = capsys.readouterr().out
        assert "[PASS] v3 store" in out

    def test_legacy_leftover_fails_doctor(self, db, monkeypatch, capsys):
        self._wire(monkeypatch, legacy=["C:/x/.claude-code-router/config.json"])
        with pytest.raises(SystemExit) as exc:
            cli_v3.doctor_v3()
        assert exc.value.code == 1
        assert "[FAIL] legacy config" in capsys.readouterr().out

    def test_drift_fails_doctor(self, db, monkeypatch, capsys):
        self._wire(monkeypatch, applied="openrouter/z-ai/glm-4.6")
        with pytest.raises(SystemExit):
            cli_v3.doctor_v3()
        assert "[FAIL] applied model" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# websearch_v3
# ---------------------------------------------------------------------------


class TestWebsearchV3:
    """Tests for websearch_v3()."""

    def test_on_is_refused_with_explanation(self, db, capsys):
        with pytest.raises(SystemExit) as exc:
            cli_v3.websearch_v3("on")
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "ALL" in out  # names the all-traffic billing consequence
        # nothing was written
        assert not ccr_v3.websearch_online_v3(ccr_store.load_blob())

    def test_off_strips_suffix(self, db, capsys):
        ccr_store.update_blob(
            lambda b: ccr_v3._replace_claude_profile(
                b, {**ccr_v3.claude_profile(b), "model":
                    ccr_v3.claude_profile(b)["model"] + ":online"}
            )
        )
        cli_v3.websearch_v3("off")
        assert not ccr_v3.websearch_online_v3(ccr_store.load_blob())
        assert "off" in capsys.readouterr().out.lower()

    def test_off_when_already_off_reports_noop(self, db, capsys):
        cli_v3.websearch_v3("off")
        assert "already" in capsys.readouterr().out.lower()
