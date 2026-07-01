# sync_apply.py - Side-effect layer for `sb sync`: runs `claude mcp add-json/remove`
# against the CCR CLAUDE_CONFIG_DIR scope and maintains the sync manifest.
#
# Per DEC-007 all writes to the target state file go THROUGH the claude CLI
# (never hand-edited: it is a live session-state file). The subprocess runner
# is injectable so every test stays hermetic.
# ---------------------------------------------------------------------------

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import claude_scopes
from .mcp_sync import SyncPlan, fingerprint


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of one server operation.

    Fields:
        name:   Server name.
        action: 'add' | 'update' | 'prune'.
        ok:     True when every subprocess involved returned 0.
        detail: CLI output on success, error text on failure (never secrets).
    """

    name: str
    action: str
    ok: bool
    detail: str


def claude_exe() -> str | None:
    """Locate the claude executable.

    Resolution order: PATH (shutil.which), then the standard native-install
    location ``~/.local/bin/claude.exe``. Returns None when not found so the
    caller can emit an actionable error before attempting any writes.
    """
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude.exe"
    return str(fallback) if fallback.exists() else None


def apply_plan(
    plan: SyncPlan,
    source: dict,
    manifest: dict,
    prune: bool = False,
    run=subprocess.run,
) -> tuple[list[ApplyResult], dict]:
    """Execute a SyncPlan against the CCR scope via the claude CLI.

    Adds run ``claude mcp add-json``; updates run ``remove`` then ``add-json``
    (add-json refuses to overwrite an existing name — verified empirically);
    managed orphans are removed only when *prune* is True. Failures are
    collected, never raised, and remaining servers still process.

    Args:
        plan:     The classification from mcp_sync.build_plan.
        source:   name -> definition map (source of truth for adds/updates).
        manifest: Current name -> fingerprint manifest (not mutated).
        prune:    When True, remove plan.orphans_managed from the target scope.
        run:      subprocess.run-compatible callable (injected in tests).

    Returns:
        (results, new_manifest): per-server outcomes and the updated manifest
        (fingerprints added for successful adds/updates, dropped for prunes).
    """
    exe = claude_exe()
    # Everything runs against the CCR scope: same env override CCR itself uses.
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(claude_scopes.TARGET_CONFIG_DIR)}

    def call(args: list[str]):
        return run([exe, "mcp", *args], env=env, capture_output=True, text=True, check=False)

    def failure_text(proc) -> str:
        return (proc.stderr or proc.stdout or "").strip()

    results: list[ApplyResult] = []
    new_manifest = dict(manifest)

    for name in plan.adds:
        proc = call(["add-json", name, json.dumps(source[name]), "--scope", "user"])
        ok = proc.returncode == 0
        results.append(ApplyResult(name, "add", ok,
                                   proc.stdout.strip() if ok else failure_text(proc)))
        if ok:
            new_manifest[name] = fingerprint(source[name])

    for name in plan.updates:
        removed = call(["remove", name, "--scope", "user"])
        added = call(["add-json", name, json.dumps(source[name]), "--scope", "user"])
        ok = removed.returncode == 0 and added.returncode == 0
        detail = added.stdout.strip() if ok else failure_text(removed if removed.returncode else added)
        results.append(ApplyResult(name, "update", ok, detail))
        if ok:
            new_manifest[name] = fingerprint(source[name])

    if prune:
        for name in plan.orphans_managed:
            proc = call(["remove", name, "--scope", "user"])
            ok = proc.returncode == 0
            results.append(ApplyResult(name, "prune", ok,
                                       proc.stdout.strip() if ok else failure_text(proc)))
            if ok:
                new_manifest.pop(name, None)

    return results, new_manifest


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest() -> dict:
    """Load the name -> fingerprint map of servers switchboard added. {} if none."""
    data, _err = claude_scopes.load_json(claude_scopes.MANIFEST_PATH)
    synced = data.get("synced", {})
    return synced if isinstance(synced, dict) else {}


def save_manifest(synced: dict) -> None:
    """Persist the manifest atomically (temp file + os.replace).

    Args:
        synced: name -> fingerprint map to store.
    """
    path = claude_scopes.MANIFEST_PATH
    payload = json.dumps({"version": 1, "synced": synced}, indent=2)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
