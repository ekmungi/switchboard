# sync_cmd.py - The `sb sync` subcommand: CC -> CCR context audit + MCP mirror.
#
# Orchestration + report formatting only. Reading lives in claude_scopes,
# diffing in mcp_sync, writing in sync_apply. Reports print server NAMES only -
# definitions (which may hold tokens in env/headers) are never echoed (SPEC R4).
# ---------------------------------------------------------------------------

import sys

from . import claude_scopes, sync_apply
from .mcp_sync import SyncPlan, build_plan


def current_plan() -> SyncPlan | None:
    """Build the live SyncPlan from the real config surfaces.

    Returns None when either state file is unreadable (malformed JSON) -
    callers like `sb doctor` then skip the parity check instead of guessing.
    """
    source_state, err_s = claude_scopes.load_json(claude_scopes.SOURCE_STATE)
    target_state, err_t = claude_scopes.load_json(claude_scopes.TARGET_STATE)
    if err_s or err_t:
        return None
    return build_plan(
        claude_scopes.mcp_servers(source_state),
        claude_scopes.mcp_servers(target_state),
        sync_apply.load_manifest(),
    )


def _server_lines(plan: SyncPlan) -> list[str]:
    """One report line per server, names only, grouped by classification."""
    lines: list[str] = []
    for name in plan.adds:
        lines.append(f"  [DRIFT] {name:<22} missing in CCR scope")
    for name in plan.updates:
        lines.append(f"  [DRIFT] {name:<22} definition drifted (remove + re-add)")
    for name in plan.orphans_managed:
        lines.append(f"  [DRIFT] {name:<22} orphaned (switchboard-added; removable with --prune)")
    for name in plan.in_sync:
        lines.append(f"  [SYNC]  {name:<22} in sync")
    for name in plan.orphans_foreign:
        lines.append(f"  [INFO]  {name:<22} only in CCR scope (user-added; left alone)")
    return lines


def _surface_lines(target_state: dict) -> list[str]:
    """Audit lines for the non-MCP context surfaces (read-only, WARN/INFO)."""
    lines: list[str] = []
    if (claude_scopes.TARGET_CONFIG_DIR / "CLAUDE.md").exists():
        lines.append("  [OK]    global CLAUDE.md - shared via ~/.claude, routes into CCR sessions")

    settings, settings_err = claude_scopes.load_json(claude_scopes.SETTINGS_PATH)
    if settings_err:
        lines.append(f"  [WARN]  {settings_err}")
    lines.append(f"  [OK]    {claude_scopes.plugins_info(settings)}")
    for warn in claude_scopes.settings_warns(settings):
        lines.append(f"  [WARN]  {warn}")

    legacy, _legacy_err = claude_scopes.load_json(claude_scopes.LEGACY_CCR_CONFIG)
    legacy_warn = claude_scopes.legacy_ccr_warn(legacy)
    if legacy_warn:
        lines.append(f"  [WARN]  {legacy_warn}")

    connectors = claude_scopes.connectors_info(target_state)
    if connectors:
        lines.append(f"  [INFO]  {connectors}")
    return lines


def cmd_sync(argv: list[str]) -> None:
    """Run the sync subcommand.

    Args:
        argv: Remaining CLI args. Supported flags: --apply (mirror drifted
              servers into the CCR scope), --prune (also remove
              switchboard-added orphans; implies --apply).

    Exit codes: 0 in sync / applied cleanly; 1 audit found drift;
    2 hard error (unreadable state file, missing claude CLI, failed apply).
    """
    prune = "--prune" in argv
    apply = "--apply" in argv or prune

    source_state, err_s = claude_scopes.load_json(claude_scopes.SOURCE_STATE)
    target_state, err_t = claude_scopes.load_json(claude_scopes.TARGET_STATE)
    errors = [e for e in (err_s, err_t) if e]
    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        sys.exit(2)

    source = claude_scopes.mcp_servers(source_state)
    target = claude_scopes.mcp_servers(target_state)
    manifest = sync_apply.load_manifest()
    plan = build_plan(source, target, manifest)

    # ASCII only: the plugin command runs bare python on Windows (cp1252 stdout).
    print("\nSwitchboard sync - Claude Code -> CCR context audit\n")
    print("MCP servers (user scope -> CCR scope):")
    print("\n".join(_server_lines(plan)) or "  (none configured on either side)")
    print("\nOther surfaces:")
    print("\n".join(_surface_lines(target_state)))
    print()

    if not apply:
        if plan.has_drift:
            n = len(plan.adds) + len(plan.updates) + len(plan.orphans_managed)
            print(f"Result: {n} server(s) drifted - run `sb sync --apply` to mirror them.")
            sys.exit(1)
        print(f"Result: all {len(plan.in_sync)} mirrored server(s) in sync.")
        return

    if not plan.has_drift:
        print("Already in sync - nothing to apply.")
        return

    if sync_apply.claude_exe() is None:
        print("[ERROR] claude executable not found (PATH or ~/.local/bin/claude.exe) - "
              "cannot apply; nothing was written.")
        sys.exit(2)

    results, new_manifest = sync_apply.apply_plan(plan, source, manifest, prune=prune)
    sync_apply.save_manifest(new_manifest)

    print("Applying:")
    for r in results:
        marker = "OK " if r.ok else "ERR"
        print(f"  [{marker}] {r.action:<6} {r.name:<22} {r.detail}")
    print("\nDone. Servers appear in the NEXT CCR-launched session (no CCR restart needed).")

    if any(not r.ok for r in results):
        sys.exit(2)
