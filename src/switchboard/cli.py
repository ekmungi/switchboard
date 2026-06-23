# cli.py - CLI dispatch layer for switchboard: subcommands, table rendering, markdown output.
#
# This module owns all user-facing output. It imports catalog and ccr_config as
# pure-function modules and adds no additional runtime dependencies beyond stdlib.
# The /catalog slash command runs `python switchboard.py list <query> --md`; that
# path must work with bare Python (no venv), so the rich import is optional.
"""switchboard.py - browse OpenRouter models and point claude-code-router at one.

Usage:
  switchboard list [query]   # no query: list companies; with query: that company's models
  switchboard use <model-id> # pin all CCR roles to a model + restart CCR
  switchboard current        # show the active CCR routing

Run via `uv run` (or the `sb` alias) so the `rich` dependency is available.
Reads/writes ~/.claude-code-router/config.json.
"""
import sys

# rich gives colored tables; fall back to plain text if it is not installed.
try:
    from rich.console import Console
    from rich.table import Table
    _CONSOLE = Console()
except ImportError:
    _CONSOLE = None

from .catalog import fetch_models, filter_models, per_million
from .ccr_config import (
    read_config,
    write_config,
    set_all_roles,
    ensure_apikey_blank,
    restart_ccr,
    CONFIG_PATH,
    ROLES,
)
from .guard import validate_model

_MARKDOWN: bool = False  # set by --md: emit markdown tables (used by the /catalog slash command)


def _print_table(columns: list, rows: list) -> None:
    """Render a table: markdown if --md, else rich if available, else plain text.

    Args:
        columns: list of (header, justify, width) tuples.
        rows: list of cell value tuples (one per column).
    """
    if _MARKDOWN:
        print("| " + " | ".join(h for h, _, _ in columns) + " |")
        print("| " + " | ".join("---" for _ in columns) + " |")
        for row in rows:
            print("| " + " | ".join(str(c) for c in row) + " |")
        return
    if _CONSOLE is not None:
        table = Table(box=None, pad_edge=False)
        for header, justify, _ in columns:
            table.add_column(header, justify=justify, no_wrap=True)
        for row in rows:
            table.add_row(*[str(c) for c in row])
        _CONSOLE.print(table)
        return
    line = "  ".join(f"{h:<{w}}" if j == "left" else f"{h:>{w}}" for h, j, w in columns)
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(f"{str(c):<{w}}" if j == "left" else f"{str(c):>{w}}"
                        for c, (_, j, w) in zip(row, columns)))


def cmd_providers(models: list) -> None:
    """Show the distinct providers (the id prefix before '/') with model counts.

    Args:
        models: list of Model instances from fetch_models().
    """
    counts: dict = {}
    for m in models:
        prov = m.id.split("/", 1)[0]
        counts[prov] = counts.get(prov, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    print(f"\n{len(rows)} providers, {len(models)} models total.")
    print("See a company's models:  sb list <PROVIDER>   (e.g. sb list deepseek)\n")
    _print_table([("PROVIDER", "left", 28), ("MODELS", "right", 7)], rows)


def cmd_list(query: str) -> None:
    """No query: list providers (companies). With a query: list that provider's models.

    Args:
        query: Provider or model substring to filter on. Empty string shows providers.
    """
    models = fetch_models()
    if not query:
        cmd_providers(models)
        return
    matches = filter_models(models, query)
    matches.sort(key=lambda m: per_million(m.prompt_price))
    print(f"\n{len(matches)} model(s) matching '{query}':")
    print("Switch in a session:         /model openrouter,<MODEL>")
    print("Web search (append :online): /model openrouter,<MODEL>:online")
    print("Set as default (terminal):   sb use <MODEL>\n")
    rows = [(m.id, m.context_length,
             f"{per_million(m.prompt_price):.2f}",
             f"{per_million(m.completion_price):.2f}")
            for m in matches]
    cols = [("MODEL  (paste after 'openrouter,')", "left", 44),
            ("CTX", "right", 9), ("$IN/M", "right", 7), ("$OUT/M", "right", 7)]
    _print_table(cols, rows)


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
    """Show the active CCR routing roles from the config file.

    Reads CONFIG_PATH and prints each role's model assignment. Warns if no
    Router section is found. ROLES (5 entries including webSearch) are iterated
    exactly once -- no duplication.
    """
    router = read_config().get("Router", {})
    if not router:
        print("No Router config found at", CONFIG_PATH)
        return
    rows = [(role, router[role]) for role in ROLES if role in router]
    print("\nCurrent CCR routing:\n")
    _print_table([("ROLE", "left", 14), ("MODEL", "left", 44)], rows)


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
        cmd_list(args[1] if len(args) > 1 else "")
    elif cmd == "use" and len(args) > 1:
        cmd_use(args[1])
    elif cmd == "current":
        cmd_current()
    else:
        print(__doc__)
        sys.exit(1)
