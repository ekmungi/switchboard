# cli.py - CLI dispatch layer for switchboard: subcommands, table rendering, markdown output.
#
# This module owns all user-facing output. It imports catalog and ccr_config as
# pure-function modules and adds no additional runtime dependencies beyond stdlib.
# The /catalog slash command runs `python switchboard.py list <query> --md`; that
# path must work with bare Python (no venv), so the rich import is optional.
# Table rendering is delegated to render.py; status logic to health.py.
"""switchboard.py - browse OpenRouter models and point claude-code-router at one.

Usage:
  switchboard list [query]      # no query: list companies; with query: that company's models
  switchboard use <model-id>    # pin the CCR model (v3: launch profile; legacy: all roles)
  switchboard current           # show the active CCR routing
  switchboard doctor            # run pass/fail health checks
  switchboard websearch on|off  # web-search :online toggle (v3: 'on' refused - all-traffic billing)
  switchboard sync [--apply] [--prune]
                                # audit CC->CCR context; mirror user-scope MCP servers
                                # into the CCR scope (--prune also removes
                                # switchboard-added orphans)
  switchboard setup             # one-command clean-translator setup (SPEC-005): pinned
                                # engine + key + default profile + proxy + tool-use gate
  switchboard code [<model>]    # launch claude via the local translator (full OpenRouter
                                # catalog); optional model switches the main tier
  switchboard stop              # stop the local translator proxy daemon

Run via `uv run` (or the `sb` alias) so the `rich` dependency is available.
The CCR store is auto-detected: v3 (SQLite at %APPDATA%/claude-code-router)
drives the claude-code launch profile; pre-v3 machines keep the legacy
role-based ~/.claude-code-router/config.json behavior unchanged.
"""
import sys

from . import launch, paths, profiles, setup, translator_checks, translator_lifecycle
from .browse import cmd_list
from .catalog import fetch_models
from .ccr_config import (
    read_config,
    write_config,
    set_all_roles,
    set_websearch_online,
    ensure_apikey_blank,
    restart_ccr,
    ccr_running,
    CONFIG_PATH,
    ROLES,
)
from .ccr_store import detect_store
from .checks import run_checks, format_checks, mcp_parity_check
from .cli_v3 import current_v3, doctor_v3, use_v3, websearch_v3
from .guard import validate_model
from .health import status_lines
from .render import print_table
from .sync_cmd import cmd_sync, current_plan

_MARKDOWN: bool = False  # set by --md: emit markdown tables (used by the /catalog slash command)


def _print_table(columns: list, rows: list) -> None:
    """Render via the shared table renderer using the current --md flag.

    Args:
        columns: list of (header, justify, width) tuples.
        rows: list of cell value tuples (one per column).
    """
    print_table(columns, rows, _MARKDOWN)


def cmd_use(model_id: str) -> None:
    """Pin every CCR role to model_id and restart CCR.

    Validates the model against the live catalog before writing anything.
    Refuses (exit 1, no writes, no restart) when the model is unknown or
    has a context window below the 64K minimum.  On success, webSearch is
    set WITHOUT the :online suffix (no surprise web billing) and the top-level
    APIKEY is kept blank so CCR auth uses the Providers entry only.

    Args:
        model_id: A valid OpenRouter model id (e.g. 'deepseek/deepseek-v4-flash').

    Exits with code 1 if validation fails.
    """
    catalog = fetch_models()
    verdict = validate_model(model_id, catalog)
    if not verdict.ok:
        print(verdict.reason)
        if verdict.suggestions:
            print("Nearest valid alternatives:")
            for s in verdict.suggestions:
                print(f"  {s}")
        sys.exit(1)

    model = next(m for m in catalog if m.id == model_id)
    if detect_store() == "v3":
        use_v3(model_id, model)
        return
    cfg = read_config()
    cfg = set_all_roles(cfg, model_id, online=False)
    cfg = ensure_apikey_blank(cfg)
    write_config(cfg)
    print(f"Model: {model_id}")
    print(f"Context: {model.context_length:,} tokens")
    print("All roles (incl. background) pinned -- no Haiku leak.")
    print("webSearch set without :online (no surprise web billing).")
    print("CCR APIKEY kept blank.")
    restart_ccr()


def cmd_current() -> None:
    """Show the active CCR routing roles plus a health summary.

    Reads CONFIG_PATH, prints the routing table, then delegates the status
    block (effective model, CCR running, APIKEY, web-search, WARNINGS) to
    health.status_lines.  Never crashes on a catalog fetch failure (offline
    mode: catalog checks are skipped).
    """
    if detect_store() == "v3":
        current_v3(_MARKDOWN)
        return
    cfg = read_config()
    router = cfg.get("Router", {})
    if not router:
        print("No Router config found at", CONFIG_PATH)
        return

    rows = [(role, router[role]) for role in ROLES if role in router]
    print("\nCurrent CCR routing:\n")
    _print_table([("ROLE", "left", 14), ("MODEL", "left", 44)], rows)

    try:
        catalog = fetch_models()
    except Exception:
        catalog = []

    print()
    for line in status_lines(cfg, catalog, ccr_running()):
        print(line)

    if not catalog:
        print("(catalog unavailable -- offline checks skipped)")


def cmd_doctor() -> None:
    """Run pass/fail health checks; exit non-zero if any check fails.

    When the clean translator is set up (an active profile exists), this reports
    the translator's health (SPEC-005 R5/R5a): engine pin, proxy health,
    cost-safety, nothing-global, and a real tool-use round-trip. Otherwise it
    falls back to the CCR doctor (deprecated path). Includes the MCP-parity check
    (SPEC-003 R8) when both user-scope state files are readable.
    """
    profile = profiles.load(paths.active_profile_path())
    if profile is not None:
        checks = translator_checks.gather_checks(profile)
        print("\nSwitchboard doctor (translator):\n")
        for line in format_checks(checks):
            print(line)
        if any(not c.ok for c in checks):
            sys.exit(1)
        return
    if detect_store() == "v3":
        doctor_v3()
        return
    ccr_up = ccr_running()
    try:
        catalog = fetch_models()
    except Exception:
        catalog = []
    checks = run_checks(read_config(), catalog, ccr_up)
    plan = current_plan()
    if plan is not None:
        checks = [*checks, mcp_parity_check(plan)]
    print("\nSwitchboard doctor:\n")
    for line in format_checks(checks):
        print(line)
    if any(not c.ok for c in checks):
        sys.exit(1)


def cmd_websearch(state: str) -> None:
    """Toggle web search (:online) on the webSearch role, then restart CCR.

    Reads the current config, applies set_websearch_online (pure, non-mutating),
    writes the result, prints the new webSearch role value, and restarts CCR.
    Exits 1 without touching config or CCR when *state* is not 'on' or 'off'.

    Args:
        state: Must be 'on' (append :online) or 'off' (strip :online).

    Exits with code 1 if state is not 'on' or 'off'.
    """
    if state not in ("on", "off"):
        print("Usage: sb websearch on|off")
        sys.exit(1)
    if detect_store() == "v3":
        websearch_v3(state)
        return
    cfg = read_config()
    cfg = set_websearch_online(cfg, state == "on")
    write_config(cfg)
    print(f"webSearch -> {cfg['Router']['webSearch']}")
    restart_ccr()


def cmd_setup() -> None:
    """Run the one-command clean-translator setup and report each step (SPEC-005 R1).

    Prints the step outcomes then the ready line, or exits 1 on a clear failure.
    """
    result = setup.run_setup()
    print("\nSwitchboard setup:\n")
    for step in result.steps:
        print(f"  [ok] {step}")
    print()
    if result.ok:
        print(result.message)
    else:
        print(f"FAILED: {result.message}")
        sys.exit(1)


def cmd_code(model: str | None) -> None:
    """Launch claude via the local translator (sb code [<model>]).

    Surfaces the cached-login advisory before the (blocking) launch, then exits
    with claude's own exit code, or 1 with a clear message on failure.

    Args:
        model: Optional OpenRouter model id to make this session's main tier.
    """
    print(launch.LOGOUT_NOTE)
    result = launch.run_code(model)
    if not result.ok:
        print(f"sb code: {result.message}")
        sys.exit(1)
    sys.exit(result.exit_code or 0)


def cmd_stop() -> None:
    """Stop the local translator proxy daemon (sb stop).

    Loads the active profile only to learn which loopback port the proxy binds,
    then hands off to translator_lifecycle.stop, which signals the recorded PID,
    clears the pidfile, and waits (synchronously) for the port to be released.
    Reports whether a live daemon was actually stopped or it was already down.

    With no active profile there is nothing running and no known port, so this
    prints a hint and returns without attempting a teardown.
    """
    profile = profiles.load(paths.active_profile_path())
    if profile is None:
        print("No active profile -- nothing to stop (run `sb setup` first).")
        return
    stopped = translator_lifecycle.stop(paths.proxy_pidfile(), "127.0.0.1", profile.port)
    if stopped:
        print(f"Translator stopped (port {profile.port} released).")
    else:
        print(f"Translator already stopped (port {profile.port} was free).")


def main() -> None:
    """Dispatch the chosen subcommand from sys.argv.

    Handles --md flag (enables markdown table output), then routes to the
    appropriate cmd_* function. Prints usage and exits 1 for unknown commands.
    """
    global _MARKDOWN
    args = sys.argv[1:]
    if "--md" in args:
        _MARKDOWN = True
        args = [a for a in args if a != "--md"]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "list":
        cmd_list(args[1] if len(args) > 1 else "", _MARKDOWN)
    elif cmd == "use" and len(args) > 1:
        cmd_use(args[1])
    elif cmd == "current":
        cmd_current()
    elif cmd == "doctor":
        cmd_doctor()
    elif cmd == "websearch" and len(args) > 1:
        cmd_websearch(args[1])
    elif cmd == "sync":
        cmd_sync(args[1:])
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "code":
        cmd_code(args[1] if len(args) > 1 else None)
    elif cmd == "stop":
        cmd_stop()
    else:
        print(__doc__)
        sys.exit(1)
