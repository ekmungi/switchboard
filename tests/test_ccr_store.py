# test_ccr_store.py - Tests for the CCR v3 SQLite store layer (SPEC-004 R1-R3).
#
# All tests are hermetic: tmp_path SQLite databases built by conftest.make_v3_db
# with a FAKE api key; the live store is never touched.
# ---------------------------------------------------------------------------

import json
import re
import sqlite3

import pytest

from switchboard import ccr_store
from conftest import make_v3_db, sample_v3_blob


@pytest.fixture
def db(v3_db):
    """Local alias for the shared conftest v3 store fixture."""
    return v3_db


# ---------------------------------------------------------------------------
# config_dir / detect_store
# ---------------------------------------------------------------------------


class TestConfigDir:
    """Tests for config_dir()."""

    def test_windows_uses_appdata(self, tmp_path, monkeypatch):
        """On Windows, resolves under %APPDATA%\\claude-code-router."""
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert ccr_store.config_dir("nt") == tmp_path / "claude-code-router"

    def test_posix_uses_home_config(self):
        """On POSIX, resolves under ~/.config/claude-code-router."""
        expected = ccr_store.Path.home() / ".config" / "claude-code-router"
        assert ccr_store.config_dir("posix") == expected


class TestDetectStore:
    """Tests for detect_store()."""

    def test_v3_when_sqlite_exists(self, db):
        """Returns 'v3' when config.sqlite exists at DB_PATH."""
        assert ccr_store.detect_store() == "v3"

    def test_legacy_when_sqlite_missing(self, tmp_path, monkeypatch):
        """Returns 'legacy' when config.sqlite is absent."""
        monkeypatch.setattr(ccr_store, "DB_PATH", tmp_path / "config.sqlite")
        assert ccr_store.detect_store() == "legacy"


# ---------------------------------------------------------------------------
# load_blob
# ---------------------------------------------------------------------------


class TestLoadBlob:
    """Tests for load_blob()."""

    def test_returns_parsed_blob(self, db):
        """Loads and parses the 'default' row into a dict."""
        blob = ccr_store.load_blob()
        assert blob["preferredProvider"] == "openrouter"
        assert blob["profile"]["profiles"][0]["agent"] == "claude-code"

    def test_raises_when_db_missing(self, tmp_path, monkeypatch):
        """Raises StoreError (and does NOT create a file) when db is absent."""
        path = tmp_path / "config.sqlite"
        monkeypatch.setattr(ccr_store, "DB_PATH", path)
        with pytest.raises(ccr_store.StoreError):
            ccr_store.load_blob()
        assert not path.exists()

    def test_raises_when_row_missing(self, tmp_path, monkeypatch):
        """Raises StoreError when the 'default' row is absent."""
        path = tmp_path / "config.sqlite"
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
        )
        con.commit()
        con.close()
        monkeypatch.setattr(ccr_store, "DB_PATH", path)
        with pytest.raises(ccr_store.StoreError):
            ccr_store.load_blob()

    def test_handles_uri_special_chars_in_path(self, tmp_path, monkeypatch):
        """Paths containing '#'/'%'/spaces must not break the sqlite URI."""
        weird = tmp_path / "we#ird %dir"
        weird.mkdir()
        path = weird / "config.sqlite"
        make_v3_db(path, sample_v3_blob())
        monkeypatch.setattr(ccr_store, "DB_PATH", path)
        assert ccr_store.load_blob()["preferredProvider"] == "openrouter"

    def test_raises_on_corrupt_json(self, tmp_path, monkeypatch):
        """Raises StoreError when the row holds unparseable JSON."""
        path = tmp_path / "config.sqlite"
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
        )
        con.execute("INSERT INTO app_config VALUES ('default', '{not json', 'x')")
        con.commit()
        con.close()
        monkeypatch.setattr(ccr_store, "DB_PATH", path)
        with pytest.raises(ccr_store.StoreError):
            ccr_store.load_blob()


# ---------------------------------------------------------------------------
# update_blob
# ---------------------------------------------------------------------------


def _read_row(path, key):
    """Return (value_json, updated_at) for *key*, or None."""
    con = sqlite3.connect(path)
    row = con.execute(
        "SELECT value_json, updated_at FROM app_config WHERE key=?", (key,)
    ).fetchone()
    con.close()
    return row


class TestUpdateBlob:
    """Tests for update_blob(mutator)."""

    def test_applies_mutator_and_persists(self, db):
        """The mutated blob is written back and re-loadable."""
        def bump(blob):
            return {**blob, "APIKEY": "", "PORT": 9999}
        new_blob = ccr_store.update_blob(bump)
        assert new_blob["PORT"] == 9999
        assert ccr_store.load_blob()["PORT"] == 9999

    def test_preserves_untargeted_keys_verbatim(self, db):
        """Unknown keys and the (fake) api_key survive a write untouched."""
        ccr_store.update_blob(lambda blob: {**blob, "PORT": 1234})
        after = ccr_store.load_blob()
        assert after["someUnknownKey"] == {"nested": [1, 2, 3]}
        assert after["Providers"][0]["api_key"] == "sk-or-FAKE-test-key-000"

    def test_writes_backup_row_with_prior_blob(self, db):
        """The pre-write blob lands verbatim in the backup row."""
        before_raw = _read_row(db, "default")[0]
        ccr_store.update_blob(lambda blob: {**blob, "PORT": 1234})
        backup = _read_row(db, ccr_store.BACKUP_KEY)
        assert backup is not None
        assert backup[0] == before_raw

    def test_backup_row_is_overwritten_not_accumulated(self, db):
        """A second update replaces the single backup row."""
        ccr_store.update_blob(lambda blob: {**blob, "PORT": 1111})
        mid_raw = _read_row(db, "default")[0]
        ccr_store.update_blob(lambda blob: {**blob, "PORT": 2222})
        con = sqlite3.connect(db)
        n = con.execute(
            "SELECT count(*) FROM app_config WHERE key=?", (ccr_store.BACKUP_KEY,)
        ).fetchone()[0]
        con.close()
        assert n == 1
        assert _read_row(db, ccr_store.BACKUP_KEY)[0] == mid_raw

    def test_updated_at_is_ccr_iso_format(self, db):
        """updated_at is refreshed in CCR's millisecond ISO-8601-Z format."""
        ccr_store.update_blob(lambda blob: blob)
        _, updated_at = _read_row(db, "default")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", updated_at)

    def test_raises_when_db_missing_and_creates_nothing(self, tmp_path, monkeypatch):
        """Missing store: StoreError, and no database file is created."""
        path = tmp_path / "config.sqlite"
        monkeypatch.setattr(ccr_store, "DB_PATH", path)
        with pytest.raises(ccr_store.StoreError):
            ccr_store.update_blob(lambda blob: blob)
        assert not path.exists()

    def test_mutator_exception_leaves_store_untouched(self, db):
        """A raising mutator aborts the transaction: no write, no backup."""
        before = _read_row(db, "default")
        def boom(blob):
            raise ValueError("nope")
        with pytest.raises(ValueError):
            ccr_store.update_blob(boom)
        assert _read_row(db, "default") == before
        assert _read_row(db, ccr_store.BACKUP_KEY) is None

    def test_non_dict_mutator_result_rejected(self, db):
        """A mutator returning a non-dict raises StoreError; store untouched."""
        before = _read_row(db, "default")
        with pytest.raises(ccr_store.StoreError):
            ccr_store.update_blob(lambda blob: "oops")
        assert _read_row(db, "default") == before
