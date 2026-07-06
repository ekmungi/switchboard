# conftest.py - Shared pytest fixtures for the switchboard test suite.
#
# Only fixtures used by MORE THAN ONE split test file live here.
import json
import sqlite3
from pathlib import Path

from switchboard import cli

import pytest


@pytest.fixture(autouse=True)
def reset_markdown():
    """Reset the module-level _MARKDOWN flag between every test."""
    cli._MARKDOWN = False
    yield
    cli._MARKDOWN = False


@pytest.fixture(autouse=True)
def isolate_switchboard_profile(tmp_path_factory, monkeypatch):
    """Point the DEFAULT active-profile path at an isolated empty dir.

    Without this, `sb doctor` (which routes to the translator doctor when a
    profile exists) would read the real ~/.switchboard/profile.json on a machine
    where setup has run, making the CCR-doctor tests non-deterministic. Callers
    that pass an explicit root (the translator tests) are untouched.
    """
    from switchboard import paths

    real = paths.active_profile_path
    isolated = tmp_path_factory.mktemp("sb_home") / "profile.json"
    monkeypatch.setattr(
        paths, "active_profile_path",
        lambda root=None: real(root) if root is not None else isolated,
    )


@pytest.fixture(autouse=True)
def force_legacy_store(monkeypatch):
    """Pin cli's store detection to 'legacy' for hermeticity.

    The dev machine has a REAL v3 config.sqlite, so without this pin every
    pre-v3 cli test would route to the v3 branch (and at the live store).
    v3 dispatch tests override this by re-patching cli.detect_store.
    """
    monkeypatch.setattr(cli, "detect_store", lambda: "legacy")


def sample_v3_blob() -> dict:
    """Return a sanitized replica of the live CCR v3 config blob (fake key).

    Mirrors the structures SPEC-004 code touches (profile/Providers/Router/
    APIKEY) plus an unknown-key canary that writers must round-trip verbatim.
    """
    return {
        "APIKEY": "",
        "HOST": "127.0.0.1",
        "PORT": 3456,
        "preferredProvider": "openrouter",
        "Providers": [
            {
                "name": "openrouter",
                "api_base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-or-FAKE-test-key-000",
                "models": ["deepseek/deepseek-v4-flash", "z-ai/glm-4.6"],
            }
        ],
        "Router": {
            "builtInRules": {"claude-code": {"enabled": True}, "codex": {"enabled": True}},
            "rules": [],
            "fallback": {"mode": "off", "models": [], "retryCount": 1},
        },
        "profile": {
            "enabled": True,
            "profiles": [
                {
                    "agent": "claude-code",
                    "id": "default-claude-code",
                    "enabled": True,
                    "model": "openrouter/deepseek/deepseek-v4-flash",
                    "smallFastModel": "openrouter/deepseek/deepseek-v4-flash",
                    "name": "Claude Code",
                    "scope": "global",
                    "settingsFile": "~/.claude/settings.json",
                },
                {"agent": "codex", "id": "default-codex", "enabled": False, "model": ""},
            ],
        },
        "agent": {"mcpServers": []},
        "someUnknownKey": {"nested": [1, 2, 3]},
    }


@pytest.fixture
def v3_blob() -> dict:
    """Fresh sanitized v3 blob dict for pure-function tests."""
    return sample_v3_blob()


def make_v3_db(path: Path, blob: dict) -> None:
    """Create a CCR-v3-shaped config.sqlite at *path* holding *blob*.

    Replicates CCR's app_config table (key/value_json/updated_at) with the
    single 'default' row, exactly as app-config-store.ts creates it.
    """
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
    )
    con.execute(
        "INSERT INTO app_config VALUES (?, ?, ?)",
        ("default", json.dumps(blob), "2026-07-01T21:41:58.460Z"),
    )
    con.commit()
    con.close()


@pytest.fixture
def v3_db(tmp_path, monkeypatch) -> Path:
    """Temp v3 store holding the sample blob, wired into ccr_store.DB_PATH.

    Shared by the store-layer and cli-layer v3 test files (conftest rule:
    fixtures used by more than one split test file live here).
    """
    from switchboard import ccr_store

    path = tmp_path / "config.sqlite"
    make_v3_db(path, sample_v3_blob())
    monkeypatch.setattr(ccr_store, "DB_PATH", path)
    return path
