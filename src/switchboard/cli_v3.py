# cli_v3.py - v3-store command implementations for use/current/doctor/websearch.
#
# cli.py dispatches here when detect_store() == 'v3' (SPEC-004 R1).  This layer
# orchestrates: guarded store writes via ccr_store.update_blob, pure updates via
# ccr_v3, environment gathering for checks_v3/health_v3, and lifecycle messaging.
# The blob (which holds the plaintext provider key) is never printed or dumped.

import sys

from .catalog import Model, fetch_models
from .ccr_lifecycle import app_advisory, ccr_running, reload_gateway
from .ccr_store import StoreError, load_blob, update_blob
from .checks import format_checks, mcp_parity_check
from .checks_v3 import run_checks_v3
from .claude_scopes import LEGACY_CCR_CONFIG, SETTINGS_PATH, load_json
from .health_v3 import status_lines_v3
from .render import print_table
from .sync_cmd import current_plan
from . import ccr_v3

NEXT_SESSION_LINE: str = (
    "Takes effect at the NEXT CCR-launched session (CCR re-applies the profile at launch)."
)
"""Printed after profile writes: running sessions keep their old model."""


def load_settings() -> dict:
    """Read ~/.claude/settings.json tolerantly ({} when missing/broken)."""
    settings, _ = load_json(SETTINGS_PATH)
    return settings


def legacy_leftovers() -> list[str]:
    """Paths of inert legacy CCR config files (config.json + .bak copies)."""
    directory = LEGACY_CCR_CONFIG.parent
    if not directory.exists():
        return []
    return sorted(str(p) for p in directory.glob("config.json*"))


def _daemon_up(blob: dict) -> bool:
    """Probe the daemon on the blob's HOST/PORT (defaults 127.0.0.1:3456)."""
    return ccr_running(blob.get("HOST", "127.0.0.1"), blob.get("PORT", 3456))


def use_v3(model_id: str, model: Model) -> None:
    """Pin the claude-code profile to *model_id* in the v3 store (SPEC-004 R4).

    Sets model + smallFastModel, ensures the whitelist entry, forces APIKEY
    blank -- all in one guarded transaction.  Reloads the gateway only when
    the whitelist changed.  Exits 1 (nothing written) on store/shape errors.

    Args:
        model_id: Already-validated OpenRouter model id.
        model:    Its catalog entry (for the context-size line).
    """
    def mutate(blob: dict) -> dict:
        new_blob = ccr_v3.set_profile_model(blob, model_id)
        new_blob, _ = ccr_v3.ensure_whitelisted(new_blob, model_id)
        return ccr_v3.set_apikey_blank(new_blob)

    try:
        # Pre-read only decides the reload message; the write itself is a
        # single guarded transaction (ensure_whitelisted is idempotent).
        models_before = ccr_v3.provider_models(load_blob())
        whitelist_changed = models_before is None or model_id not in models_before
        new_blob = update_blob(mutate)
    except (StoreError, ValueError) as exc:
        print(f"CCR v3 store error -- nothing written: {exc}")
        sys.exit(1)

    print(f"Model: {model_id}")
    print(f"Context: {model.context_length:,} tokens")
    print("Profile pinned: model + smallFastModel (no small/fast leak).")
    print("CCR APIKEY kept blank.")
    print(NEXT_SESSION_LINE)
    if whitelist_changed:
        print(f"Provider whitelist: added {model_id} (gateway must reload to serve it).")
        for line in reload_gateway():
            print(line)
    advisory = app_advisory(_daemon_up(new_blob))
    if advisory:
        print(advisory)


def current_v3(markdown: bool) -> None:
    """Show the v3 store state + health summary (SPEC-004 R5). Read-only.

    Args:
        markdown: True to render the table as markdown (--md flag).
    """
    try:
        blob = load_blob()
    except StoreError as exc:
        print(f"CCR v3 store unreadable: {exc}")
        return

    applied = ccr_v3.applied_model(load_settings())
    rows = [
        ("store model", ccr_v3.store_model_id(blob) or "(not set)"),
        ("small/fast", ccr_v3.small_fast_id(blob) or "(not set)"),
        ("applied (env)", applied or "(none)"),
    ]
    print("\nCurrent CCR v3 routing (SQLite store):\n")
    print_table([("FIELD", "left", 14), ("VALUE", "left", 44)], rows, markdown)

    try:
        catalog = fetch_models()
    except Exception:
        catalog = []
    print()
    for line in status_lines_v3(blob, catalog, _daemon_up(blob), applied):
        print(line)
    if not catalog:
        print("(catalog unavailable -- offline checks skipped)")


def doctor_v3() -> None:
    """Run the v3 doctor checks; exit 1 when any check fails (SPEC-004 R7)."""
    try:
        blob: dict | None = load_blob()
        store_error = None
    except StoreError as exc:
        blob, store_error = None, str(exc)

    try:
        catalog = fetch_models()
    except Exception:
        catalog = []
    ccr_up = _daemon_up(blob or {})
    applied = ccr_v3.applied_model(load_settings())

    checks = run_checks_v3(blob, store_error, catalog, ccr_up, applied, legacy_leftovers())
    plan = current_plan()
    if plan is not None:
        checks = [*checks, mcp_parity_check(plan)]
    print("\nSwitchboard doctor (CCR v3 store):\n")
    for line in format_checks(checks):
        print(line)
    if any(not c.ok for c in checks):
        sys.exit(1)


def websearch_v3(state: str) -> None:
    """Handle `sb websearch on|off` against a v3 store (SPEC-004 R8).

    'on' is refused: v3 has no scoped webSearch role, so ':online' would be
    billed on ALL traffic (DEC-008).  'off' strips a ':online' suffix left by
    other tools (write-guarded), reporting a no-op when already clean.
    """
    if state == "on":
        print("Refused: CCR v3 has no scoped webSearch role (the old Router role is gone).")
        print("Adding ':online' to the profile model would bill ALL traffic, not just")
        print("web-search requests -- use the CCR app's Router rules for scoped routing.")
        print("`sb websearch off` still strips a stray ':online' suffix.")
        sys.exit(1)

    try:
        blob = load_blob()
    except StoreError as exc:
        print(f"CCR v3 store unreadable: {exc}")
        sys.exit(1)
    if not ccr_v3.websearch_online_v3(blob):
        # No-op: report without writing (keeps the backup row meaningful).
        print("web search already off (no ':online' suffix on the profile model).")
        return

    def mutate(blob: dict) -> dict:
        new_blob, _ = ccr_v3.strip_online(blob)
        return new_blob

    try:
        update_blob(mutate)
    except StoreError as exc:
        print(f"CCR v3 store error -- nothing written: {exc}")
        sys.exit(1)
    print("web search -> off (':online' stripped from the profile model).")
    print(NEXT_SESSION_LINE)
