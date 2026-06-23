# render.py - Shared table-rendering logic for switchboard CLI output.
#
# Provides print_table(), the single source of truth for markdown / rich /
# plain-text table output.  Imported by cli.py so the rendering logic lives
# in exactly one place.

# rich gives colored tables; fall back to plain text if it is not installed.
try:
    from rich.console import Console
    from rich.table import Table
    _CONSOLE = Console()
except ImportError:
    _CONSOLE = None


def print_table(columns: list, rows: list, markdown: bool = False) -> None:
    """Render a table to stdout: markdown, rich-colored, or plain text.

    Args:
        columns:  list of (header, justify, width) tuples.
        rows:     list of cell-value tuples (one tuple per row, one value per column).
        markdown: when True emit pipe-delimited GitHub-flavored markdown;
                  when False use rich if available, otherwise plain text.
    """
    if markdown:
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
