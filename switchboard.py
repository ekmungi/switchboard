#!/usr/bin/env python3
"""switchboard.py - browse OpenRouter models and point claude-code-router at one.

Usage:
  switchboard list [query]   # no query: list companies; with query: that company's models
  switchboard use <model-id> # pin all CCR roles to a model + restart CCR
  switchboard current        # show the active CCR routing

Run via `uv run` (or the `sb` alias) so the `rich` dependency is available.
Reads/writes ~/.claude-code-router/config.json.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# rich gives colored tables; fall back to plain text if it is not installed.
try:
    from rich.console import Console
    from rich.table import Table
    _CONSOLE = Console()
except ImportError:
    _CONSOLE = None

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CONFIG_PATH = Path.home() / ".claude-code-router" / "config.json"
PROVIDER = "openrouter"
ROLES = ["default", "background", "think", "longContext"]
_MARKDOWN = False  # set by --md: emit markdown tables (used by the /catalog slash command)


def fetch_models():
    """Fetch the live OpenRouter catalog. Returns a list of model dicts."""
    with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")).get("data", [])


def filter_models(models, query):
    """Return models whose id or name contains query (case-insensitive); empty = all."""
    if not query:
        return list(models)
    q = query.lower()
    return [m for m in models
            if q in m["id"].lower() or q in (m.get("name", "") or "").lower()]


def per_million(price_str):
    """Convert an OpenRouter per-token price string to per-million-token float."""
    try:
        return float(price_str or 0) * 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _print_table(columns, rows):
    """Render a table: markdown if --md, else rich if available, else plain text.

    columns: list of (header, justify, width). rows: list of cell tuples.
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


def cmd_providers(models):
    """Show the distinct providers (the id prefix before '/') with model counts."""
    counts = {}
    for m in models:
        prov = m["id"].split("/", 1)[0]
        counts[prov] = counts.get(prov, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    print(f"\n{len(rows)} providers, {len(models)} models total.")
    print("See a company's models:  sb list <PROVIDER>   (e.g. sb list deepseek)\n")
    _print_table([("PROVIDER", "left", 28), ("MODELS", "right", 7)], rows)


def cmd_list(query):
    """No query: list providers (companies). With a query: list that provider's models."""
    models = fetch_models()
    if not query:
        cmd_providers(models)
        return
    matches = filter_models(models, query)
    matches.sort(key=lambda m: per_million((m.get("pricing") or {}).get("prompt")))
    print(f"\n{len(matches)} model(s) matching '{query}':")
    print("Switch in a session:         /model openrouter,<MODEL>")
    print("Web search (append :online): /model openrouter,<MODEL>:online")
    print("Set as default (terminal):   sb use <MODEL>\n")
    rows = []
    for m in matches:
        p = m.get("pricing") or {}
        rows.append((m["id"], m.get("context_length", 0),
                     f"{per_million(p.get('prompt')):.2f}",
                     f"{per_million(p.get('completion')):.2f}"))
    cols = [("MODEL  (paste after 'openrouter,')", "left", 44),
            ("CTX", "right", 9), ("$IN/M", "right", 7), ("$OUT/M", "right", 7)]
    _print_table(cols, rows)


def read_config():
    """Read the CCR config, or return {} if it does not exist."""
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(cfg):
    """Write the CCR config back as pretty JSON."""
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def cmd_use(model_id):
    """Pin every CCR role to model_id (webSearch gets :online) and restart CCR."""
    ids = {m["id"] for m in fetch_models()}
    if model_id not in ids:
        prefix = model_id.split("/")[0]
        print(f"'{model_id}' is not in the OpenRouter catalog.")
        print(f"Try: sb list {prefix}")
        sys.exit(1)
    cfg = read_config()
    router = dict(cfg.get("Router", {}))
    for role in ROLES:
        router[role] = f"{PROVIDER},{model_id}"
    router["webSearch"] = f"{PROVIDER},{model_id}:online"
    cfg["Router"] = router
    write_config(cfg)
    print(f"Pinned all roles to {model_id} (webSearch -> {model_id}:online).")
    # No shell=True (avoids injection); on Windows `ccr` is a .cmd shim -> route via cmd.exe.
    restart = ["cmd", "/c", "ccr", "restart"] if os.name == "nt" else ["ccr", "restart"]
    subprocess.run(restart, check=False)


def cmd_current():
    """Show the active CCR routing roles."""
    router = read_config().get("Router", {})
    if not router:
        print("No Router config found at", CONFIG_PATH)
        return
    rows = [(role, router[role]) for role in ROLES + ["webSearch"] if role in router]
    print("\nCurrent CCR routing:\n")
    _print_table([("ROLE", "left", 14), ("MODEL", "left", 44)], rows)


def main():
    """Dispatch the chosen subcommand."""
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


if __name__ == "__main__":
    main()
