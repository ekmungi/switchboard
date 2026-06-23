# health.py - Pure status/warning logic for the sb current health view (FR2 / AC2).
#
# No printing, no I/O, no side effects.  All functions accept plain dicts and
# return plain values so they can be unit-tested without any filesystem or
# network access.

from .catalog import Model
from .ccr_config import ROLES
from .guard import MIN_CONTEXT

__all__ = [
    "role_model",
    "model_problem",
    "effective_model",
    "apikey_blank",
    "websearch_online",
    "role_warnings",
    "status_lines",
]


def role_model(role_value: str) -> str:
    """Return the bare OpenRouter model id from a CCR role value.

    Strips the leading '<provider>,' prefix (up to the first comma) and any
    trailing ':online' suffix.  If there is no comma the whole string is
    treated as the model id (stripped of ':online' only).

    Args:
        role_value: A CCR Router value such as
            ``'openrouter,deepseek/deepseek-v4-flash:online'``.

    Returns:
        The bare model id, e.g. ``'deepseek/deepseek-v4-flash'``.
    """
    # Strip provider prefix
    if "," in role_value:
        _, model_part = role_value.split(",", 1)
    else:
        model_part = role_value
    # Strip :online suffix
    if model_part.endswith(":online"):
        model_part = model_part[: -len(":online")]
    return model_part


def effective_model(cfg: dict) -> str | None:
    """Return the single effective model id when all ROLES agree, else None.

    webSearch is compared by its base model id (the ':online' suffix is
    stripped before comparison), so ':online' on webSearch alone does NOT
    count as disagreement.

    Args:
        cfg: The full CCR config dict (must contain a 'Router' key).

    Returns:
        The common model id string when every role resolves to the same base
        id, or ``None`` when roles disagree or no roles are present.
    """
    router: dict = cfg.get("Router", {})
    ids = {
        role_model(router[role])
        for role in ROLES
        if role in router
    }
    if len(ids) == 1:
        return next(iter(ids))
    return None


def apikey_blank(cfg: dict) -> bool:
    """Return True iff the top-level APIKEY in cfg is the empty string.

    Args:
        cfg: The full CCR config dict.

    Returns:
        True when ``cfg.get('APIKEY', '')`` is ``''``, False otherwise.
    """
    return cfg.get("APIKEY", "") == ""


def websearch_online(cfg: dict) -> bool:
    """Return True iff the webSearch role value ends with ':online'.

    Args:
        cfg: The full CCR config dict (must contain a 'Router' key).

    Returns:
        True when the webSearch role ends with ``':online'``, False otherwise.
    """
    router: dict = cfg.get("Router", {})
    return router.get("webSearch", "").endswith(":online")


def model_problem(model_id: str, catalog: list[Model]) -> str | None:
    """Return the problem suffix for a model id, or None when healthy.

    Priority (first match wins): (1) Anthropic/Haiku leak -- always checked;
    (2) not in catalog -- only when catalog non-empty; (3) context < MIN_CONTEXT.

    Args:
        model_id: Bare OpenRouter model id.
        catalog:  Live catalog; empty list disables checks 2 and 3.

    Returns:
        Suffix string to append after ``"<role>: '<model>' "``, or None.
    """
    # Check 1: Anthropic/Haiku leak (catalog-independent).
    if (
        model_id.startswith("anthropic/")
        or model_id.startswith("~anthropic/")
        or "haiku" in model_id
    ):
        return "is an Anthropic/Haiku model (small/fast leak)"
    # Checks 2 and 3 require a non-empty catalog.
    if not catalog:
        return None
    catalog_ids: set[str] = {m.id for m in catalog}
    # Check 2: not in catalog.
    if model_id not in catalog_ids:
        return "is not in the catalog"
    # Check 3: context window too small.
    catalog_ctx: dict[str, int] = {m.id: m.context_length for m in catalog}
    ctx = catalog_ctx[model_id]
    if ctx < MIN_CONTEXT:
        return f"context {ctx:,} is below {MIN_CONTEXT:,}"
    return None


def role_warnings(cfg: dict, catalog: list[Model]) -> list[str]:
    """Build a list of human-readable warning strings for the health view.

    Per-role checks are delegated to model_problem (Anthropic/Haiku leak,
    not-in-catalog, context too small).  Config-level checks appended after:
    APIKEY not blank and web search ON (':online').

    Args:
        cfg:     The full CCR config dict.
        catalog: Live catalog list; when empty, membership/context checks skipped.

    Returns:
        A list of warning strings.  Empty list means everything is healthy.
    """
    router: dict = cfg.get("Router", {})
    warnings: list[str] = []

    for role in ROLES:
        if role not in router:
            continue
        model = role_model(router[role])
        p = model_problem(model, catalog)
        if p:
            warnings.append(f"{role}: '{model}' {p}")

    # Config-level checks (preserved exactly as before)
    if not apikey_blank(cfg):
        warnings.append("CCR APIKEY is not blank")
    if websearch_online(cfg):
        warnings.append("web search is ON (:online) -- billed by OpenRouter")

    return warnings


def status_lines(cfg: dict, catalog: list[Model], ccr_up: bool) -> list[str]:
    """Return the status-block lines for 'sb current', without printing them.

    Produces four mandatory status lines followed by an optional WARNINGS block
    when role_warnings finds issues.  The caller prints each line.

    Args:
        cfg:     The full CCR config dict.
        catalog: Live catalog (empty list when offline -- catalog checks skipped).
        ccr_up:  True iff the CCR process is currently running.

    Returns:
        A list of strings ready to be printed one per line.  The leading blank
        line that separates the routing table from the status block is NOT
        included here; the caller emits it before iterating.
    """
    em = effective_model(cfg)
    lines: list[str] = [
        f"Effective model : {em if em is not None else '(roles disagree)'}",
        f"CCR running     : {'yes' if ccr_up else 'no'}",
        f"APIKEY blank    : {'yes' if apikey_blank(cfg) else 'NO'}",
        f"Web search      : {'on' if websearch_online(cfg) else 'off'}",
    ]

    warnings = role_warnings(cfg, catalog)
    if warnings:
        lines.append("")  # blank line before WARNINGS block, matching cmd_current output
        lines.append("WARNINGS:")
        for w in warnings:
            lines.append(f"  {w}")

    return lines
