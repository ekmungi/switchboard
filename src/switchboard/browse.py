# browse.py - Catalog-browse subcommands for switchboard: list providers and models.
#
# Extracted from cli.py so that cli.py stays under the 200-line target.
# These functions take `markdown` as an explicit parameter (not a global) so
# they are independently testable.  Table rendering is delegated to render.py.

from .catalog import Model, fetch_models, filter_models, per_million
from .render import print_table


def cmd_providers(models: list[Model], markdown: bool = False) -> None:
    """Show the distinct providers (the id prefix before '/') with model counts.

    Args:
        models:   List of Model instances from fetch_models().
        markdown: When True, emit pipe-delimited GitHub-flavored markdown table.
    """
    counts: dict = {}
    for m in models:
        prov = m.id.split("/", 1)[0]
        counts[prov] = counts.get(prov, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    print(f"\n{len(rows)} providers, {len(models)} models total.")
    print("See a company's models:  sb list <PROVIDER>   (e.g. sb list deepseek)\n")
    print_table([("PROVIDER", "left", 28), ("MODELS", "right", 7)], rows, markdown)


def cmd_list(query: str, markdown: bool = False) -> None:
    """No query: list providers (companies). With a query: list that provider's models.

    Args:
        query:    Provider or model substring to filter on. Empty string shows providers.
        markdown: When True, emit pipe-delimited GitHub-flavored markdown table.
    """
    models = fetch_models()
    if not query:
        cmd_providers(models, markdown)
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
    print_table(cols, rows, markdown)
