# health_v3.py - Pure status/warning logic for `sb current` on a CCR v3 store.
#
# No printing, no I/O, no side effects (mirrors health.py for the v3 world).
# Inputs are the parsed blob plus already-gathered environment facts.

from .catalog import Model
from .health import apikey_blank, model_problem
from . import ccr_v3

__all__ = ["status_lines_v3", "warnings_v3"]


def _applied_status(blob: dict, applied: str | None) -> str:
    """One-line applied-model status with an explicit drift verdict."""
    prof = ccr_v3.claude_profile(blob) or {}
    store_value = prof.get("model", "")
    if applied is None:
        return "(none applied -- launch a CCR session to apply the profile)"
    if applied == store_value:
        return f"{applied} [in sync]"
    return f"{applied} [DRIFT -- launch a new CCR session to re-apply]"


def warnings_v3(blob: dict, catalog: list[Model], applied: str | None) -> list[str]:
    """Build human-readable warning strings for the v3 health view.

    Covers: model/smallFastModel problems (leak, not-in-catalog, context),
    whitelist miss, store-vs-applied drift, non-blank APIKEY, web-search
    billing. Empty list means healthy.

    Args:
        blob:    Parsed v3 config blob.
        catalog: Live catalog (empty disables catalog-dependent checks).
        applied: env.ANTHROPIC_MODEL from settings.json, or None.

    Returns:
        A list of warning strings.
    """
    warnings: list[str] = []
    fields = [
        ("model", ccr_v3.store_model_id(blob)),
        ("smallFastModel", ccr_v3.small_fast_id(blob)),
    ]
    for label, model_id in fields:
        if not model_id:
            warnings.append(f"{label}: not set on the claude-code profile")
            continue
        problem = model_problem(model_id, catalog)
        if problem:
            warnings.append(f"{label}: '{model_id}' {problem}")

    models = ccr_v3.provider_models(blob)
    store_id = ccr_v3.store_model_id(blob)
    if models is None:
        warnings.append("no preferred provider entry in the CCR config")
    elif store_id and store_id not in models:
        warnings.append(
            f"'{store_id}' missing from the provider whitelist -- the gateway will not serve it"
        )

    prof = ccr_v3.claude_profile(blob) or {}
    if applied is not None and applied != prof.get("model", ""):
        warnings.append("store/applied drift -- settings.json still carries the previous model")

    if not apikey_blank(blob):
        warnings.append("CCR APIKEY is not blank")
    if ccr_v3.websearch_online_v3(blob):
        warnings.append("web search is ON (:online) -- ALL traffic is billed by OpenRouter")
    return warnings


def status_lines_v3(
    blob: dict, catalog: list[Model], ccr_up: bool, applied: str | None
) -> list[str]:
    """Return the status-block lines for `sb current` on v3, without printing.

    Args:
        blob:    Parsed v3 config blob.
        catalog: Live catalog (empty when offline).
        ccr_up:  True iff the daemon answers on the blob's HOST/PORT.
        applied: env.ANTHROPIC_MODEL from settings.json, or None.

    Returns:
        Printable lines: store/applied/daemon/APIKEY/web-search/Router status,
        then an optional WARNINGS block.
    """
    summary = ccr_v3.router_summary(blob)
    lines: list[str] = [
        f"Store model    : {ccr_v3.store_model_id(blob) or '(not set)'}",
        f"Small/fast     : {ccr_v3.small_fast_id(blob) or '(not set)'}",
        f"Applied (env)  : {_applied_status(blob, applied)}",
        f"CCR running    : {'yes' if ccr_up else 'no'}",
        f"APIKEY blank   : {'yes' if apikey_blank(blob) else 'NO'}",
        f"Web search     : {'on' if ccr_v3.websearch_online_v3(blob) else 'off'}",
        (
            f"Router         : builtin={','.join(summary['builtin']) or '-'} "
            f"rules={summary['rules']} fallback={summary['fallback']}"
        ),
    ]
    warnings = warnings_v3(blob, catalog, applied)
    if warnings:
        lines.append("")
        lines.append("WARNINGS:")
        lines.extend(f"  {w}" for w in warnings)
    return lines
