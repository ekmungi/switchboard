# mcp_sync.py - Pure MCP-server diff engine for `sb sync` (SPEC-003).
#
# No I/O, no printing, no side effects: dicts in, SyncPlan out. The apply
# layer (sync_apply.py) turns a plan into `claude mcp add-json/remove` calls.
# ---------------------------------------------------------------------------

import hashlib
import json
from dataclasses import dataclass

MASK: str = "***"
"""Replacement for secret values in redacted output (ASCII: survives cp1252 stdout)."""

# Top-level field names that smell like credentials (case-insensitive substrings).
_SECRET_HINTS: tuple[str, ...] = ("key", "token", "secret", "password")


def normalize(server: dict) -> dict:
    """Return a canonical copy of a server definition for comparison.

    Drops None values and empty collections ({} / []) so cosmetic differences
    (e.g. an explicit empty ``env`` vs an absent one) do not register as drift.

    Args:
        server: Raw server definition from a state file.

    Returns:
        A new dict with only meaningful fields.
    """
    return {
        k: v
        for k, v in server.items()
        if v is not None and not (isinstance(v, (dict, list)) and len(v) == 0)
    }


def fingerprint(server: dict) -> str:
    """Stable content hash of a (normalized) server definition.

    Args:
        server: Raw server definition.

    Returns:
        A hex digest that is identical for definitions that normalize equally,
        regardless of key order.
    """
    canon = json.dumps(normalize(server), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def redact(server: dict) -> dict:
    """Return a copy of a server definition safe for printing (R4).

    Masks every value inside ``env`` and ``headers`` (names survive) and any
    top-level field whose name contains a credential-ish hint (key/token/…).
    The input dict is never mutated.

    Args:
        server: Raw server definition.

    Returns:
        A new dict with secret values replaced by MASK.
    """
    out: dict = {}
    for k, v in server.items():
        if k in ("env", "headers") and isinstance(v, dict):
            out[k] = {name: MASK for name in v}
        elif any(hint in k.lower() for hint in _SECRET_HINTS):
            out[k] = MASK
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class SyncPlan:
    """Classification of every server across source scope, target scope, manifest.

    Fields (all tuples of server names, alphabetical):
        adds:            in source, absent from target -> `claude mcp add-json`.
        updates:         in both, definitions differ -> remove + re-add.
        in_sync:         in both, definitions match.
        orphans_managed: target-only AND switchboard-added (manifest fingerprint
                         matches) -> prunable with --prune.
        orphans_foreign: target-only, user-added or user-modified -> report only.
    """

    adds: tuple[str, ...]
    updates: tuple[str, ...]
    in_sync: tuple[str, ...]
    orphans_managed: tuple[str, ...]
    orphans_foreign: tuple[str, ...]

    @property
    def has_drift(self) -> bool:
        """True when actionable drift exists (adds/updates/managed orphans).

        Foreign orphans are deliberately excluded: servers the user added in
        the CCR scope themselves are their business, not drift.
        """
        return bool(self.adds or self.updates or self.orphans_managed)


def build_plan(source: dict, target: dict, manifest: dict) -> SyncPlan:
    """Diff the source scope against the target scope into a SyncPlan.

    Args:
        source:   name -> definition from ~/.claude.json (plain sessions).
        target:   name -> definition from the CCR-scope .claude.json.
        manifest: name -> fingerprint of servers switchboard previously added.

    Returns:
        A SyncPlan with every server classified (inputs never mutated).
    """
    adds, updates, in_sync = [], [], []
    for name in sorted(source):
        if name not in target:
            adds.append(name)
        elif fingerprint(source[name]) == fingerprint(target[name]):
            in_sync.append(name)
        else:
            updates.append(name)

    orphans_managed, orphans_foreign = [], []
    for name in sorted(set(target) - set(source)):
        # Prunable only when the CURRENT target definition is exactly what
        # switchboard recorded adding — a user-modified entry becomes foreign.
        if manifest.get(name) == fingerprint(target[name]):
            orphans_managed.append(name)
        else:
            orphans_foreign.append(name)

    return SyncPlan(
        adds=tuple(adds),
        updates=tuple(updates),
        in_sync=tuple(in_sync),
        orphans_managed=tuple(orphans_managed),
        orphans_foreign=tuple(orphans_foreign),
    )
