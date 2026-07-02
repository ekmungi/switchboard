# ccr_store.py - CCR v3 SQLite config store: detection, guarded read, guarded write.
#
# CCR v3 keeps its whole config as ONE JSON blob in %APPDATA%/claude-code-router/
# config.sqlite (table app_config, row key='default'); the legacy
# ~/.claude-code-router/config.json is inert when that DB exists (ISS-002/R-006).
# The blob contains the plaintext provider api_key, so this module never prints,
# logs, or copies it outside the store; the pre-write backup stays in the same
# table (SPEC-004 R3/R9).

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

CONFIG_KEY: str = "default"
"""app_config row key CCR loads its config from (pickConfig reads only this)."""

BACKUP_KEY: str = "default.switchboard-bak"
"""Switchboard-owned backup row: the pre-write blob, overwritten on each write."""


class StoreError(Exception):
    """Raised when the v3 store is missing, unreadable, or a write is invalid."""


def config_dir(platform_name: str | None = None) -> Path:
    """Return CCR's platform config directory (CONFIGDIR).

    Windows: %APPDATA%/claude-code-router; POSIX: ~/.config/claude-code-router
    (mirrors CCR v3's app-paths.ts resolution).

    Args:
        platform_name: os.name override for tests ('nt'/'posix'); defaults to
            the real os.name.  Injected rather than monkeypatched because
            pathlib itself dispatches on os.name at call time.
    """
    if (platform_name or os.name) == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "claude-code-router"
    return Path.home() / ".config" / "claude-code-router"


DB_PATH: Path = config_dir() / "config.sqlite"
"""Absolute path to the v3 SQLite store (module constant, monkeypatched in tests)."""


def detect_store() -> str:
    """Return 'v3' when the SQLite store exists, else 'legacy'.

    Mirrors CCR v3's own load order (SQLite first, JSON files only as
    fallback), so switchboard always targets the store CCR actually reads.
    """
    return "v3" if DB_PATH.exists() else "legacy"


def _connect(mode: str) -> sqlite3.Connection:
    """Open the store via URI so a missing file errors instead of being created.

    Args:
        mode: 'ro' for reads, 'rw' for writes (never 'rwc' -- we must not
              fabricate an empty store on machines that do not have one).

    Raises:
        StoreError: when the database file cannot be opened.
    """
    # Percent-encode the path: '#'/'?'/'%' in a profile dir would otherwise be
    # parsed as URI syntax and silently point sqlite at a different file.
    uri = f"file:{quote(DB_PATH.as_posix(), safe='/:')}?mode={mode}"
    try:
        return sqlite3.connect(uri, uri=True, isolation_level=None)
    except sqlite3.Error as exc:
        raise StoreError(f"CCR v3 store not readable at {DB_PATH}: {exc}") from exc


def _fetch_raw(con: sqlite3.Connection) -> str:
    """Return the raw value_json of the 'default' row.

    Raises:
        StoreError: when the table or row is missing.
    """
    try:
        row = con.execute(
            "SELECT value_json FROM app_config WHERE key=?", (CONFIG_KEY,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"CCR v3 store has no app_config table: {exc}") from exc
    if row is None:
        raise StoreError(f"CCR v3 store has no '{CONFIG_KEY}' config row")
    return row[0]


def _parse(raw: str) -> dict:
    """Parse the blob JSON, mapping decode errors to StoreError."""
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StoreError(f"CCR v3 config blob is not valid JSON: {exc}") from exc
    if not isinstance(blob, dict):
        raise StoreError("CCR v3 config blob is not a JSON object")
    return blob


def _now_iso() -> str:
    """Return the current UTC time in CCR's millisecond ISO-8601-Z format."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def load_blob() -> dict:
    """Read and parse the v3 config blob (read-only).

    Returns:
        The parsed config dict.

    Raises:
        StoreError: when the store, table, row, or JSON is missing/invalid.
    """
    con = _connect("ro")
    try:
        return _parse(_fetch_raw(con))
    finally:
        con.close()


def update_blob(mutator: Callable[[dict], dict]) -> dict:
    """Apply *mutator* to the live blob inside one guarded transaction.

    Read-modify-write under BEGIN IMMEDIATE (write lock): the previous raw
    blob is first copied to the BACKUP_KEY row (same table -- the secret never
    leaves the store), then the mutated blob replaces the 'default' row with a
    refreshed updated_at.  Any mutator exception or invalid result rolls the
    whole transaction back, leaving the store byte-identical.

    Args:
        mutator: Pure function old-blob -> new-blob (must return a dict).

    Returns:
        The new blob as written.

    Raises:
        StoreError: store missing/unreadable, or mutator returned a non-dict.
        Exception:  whatever the mutator itself raises (after rollback).
    """
    con = _connect("rw")
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            raw = _fetch_raw(con)
            new_blob = mutator(_parse(raw))
            if not isinstance(new_blob, dict):
                raise StoreError("config mutator must return a dict")
            ts = _now_iso()
            con.execute(
                "INSERT INTO app_config (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                "updated_at=excluded.updated_at",
                (BACKUP_KEY, raw, ts),
            )
            con.execute(
                "UPDATE app_config SET value_json=?, updated_at=? WHERE key=?",
                (json.dumps(new_blob, separators=(",", ":")), ts, CONFIG_KEY),
            )
            con.execute("COMMIT")
            return new_blob
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
