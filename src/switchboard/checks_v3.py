# checks_v3.py - Pure doctor logic for `sb doctor` on a CCR v3 store (SPEC-004 R7).
#
# No printing, no I/O, no side effects: the CLI gathers blob/catalog/daemon/
# settings/legacy state and this module only judges it.  Reuses the legacy
# Check dataclass and model_problem so verdict wording stays consistent.

from .catalog import Model
from .checks import Check
from .health import apikey_blank, model_problem
from . import ccr_v3

__all__ = ["run_checks_v3"]


def _env_checks(catalog: list[Model], ccr_up: bool) -> list[Check]:
    """Environment-level checks that run even when the store is unreadable."""
    return [
        Check("CCR running", ccr_up, "reachable" if ccr_up else "not reachable"),
        Check(
            "OpenRouter catalog",
            bool(catalog),
            f"{len(catalog)} models" if catalog else "unavailable",
        ),
    ]


def _profile_check(blob: dict) -> Check:
    """Check the claude-code launch profile exists, is enabled, and has a model."""
    prof = ccr_v3.claude_profile(blob)
    if prof is None:
        return Check("claude-code profile", False, "not found in profile.profiles")
    if not prof.get("enabled"):
        return Check("claude-code profile", False, "present but disabled")
    if not prof.get("model"):
        return Check("claude-code profile", False, "no model set")
    return Check("claude-code profile", True, str(prof["model"]))


def _model_check(name: str, model_id: str | None, catalog: list[Model]) -> Check:
    """Leak/catalog/context check for one model field via model_problem."""
    if not model_id:
        return Check(name, False, "not set")
    problem = model_problem(model_id, catalog)
    return Check(name, problem is None, model_id if problem is None else f"'{model_id}' {problem}")


def _whitelist_check(blob: dict, model_id: str | None) -> Check:
    """Is the pinned model in the provider whitelist the gateway serves?"""
    models = ccr_v3.provider_models(blob)
    if models is None:
        return Check("whitelist", False, "no preferred provider entry in config")
    if model_id and model_id in models:
        return Check("whitelist", True, f"{len(models)} models incl. pinned")
    return Check(
        "whitelist", False,
        f"'{model_id}' not in provider models -- gateway will not serve it "
        "(run `sb use` to add + reload)",
    )


def _parity_check(blob: dict, applied: str | None) -> Check:
    """Does settings.json's applied ANTHROPIC_MODEL match the store profile?"""
    prof = ccr_v3.claude_profile(blob) or {}
    store_value = prof.get("model", "")
    if applied is None:
        return Check(
            "applied model", False,
            "settings.json has no ANTHROPIC_MODEL -- launch a CCR session to apply the profile",
        )
    if applied == store_value:
        return Check("applied model", True, applied)
    return Check(
        "applied model", False,
        f"settings.json has '{applied}' but store has '{store_value}' -- "
        "launch a new CCR session to re-apply",
    )


def run_checks_v3(
    blob: dict | None,
    store_error: str | None,
    catalog: list[Model],
    ccr_up: bool,
    applied: str | None,
    legacy_files: list[str],
) -> list[Check]:
    """Run all v3 doctor checks and return results in canonical order.

    Args:
        blob:         Parsed v3 config blob, or None when the store is unreadable.
        store_error:  Error detail when blob is None.
        catalog:      Live OpenRouter catalog (empty when offline).
        ccr_up:       True iff the CCR daemon answers on the blob's HOST/PORT.
        applied:      env.ANTHROPIC_MODEL from ~/.claude/settings.json, or None.
        legacy_files: Paths of inert legacy config files still on disk.

    Returns:
        Ordered list of Check instances; blob-derived checks are skipped
        (not failed) when the store itself is unreadable.
    """
    checks = _env_checks(catalog, ccr_up)

    if blob is None:
        checks.append(Check("v3 store", False, store_error or "unreadable"))
    else:
        checks.append(Check("v3 store", True, "readable"))
        checks.append(_profile_check(blob))
        checks.append(_model_check("model", ccr_v3.store_model_id(blob), catalog))
        checks.append(_model_check("smallFastModel", ccr_v3.small_fast_id(blob), catalog))
        checks.append(_whitelist_check(blob, ccr_v3.store_model_id(blob)))
        checks.append(_parity_check(blob, applied))
        apikey_ok = apikey_blank(blob)
        checks.append(Check(
            "APIKEY blank", apikey_ok,
            "blank" if apikey_ok else "NOT blank (auth-wall risk)",
        ))

    if legacy_files:
        checks.append(Check(
            "legacy config", False,
            "inert legacy file(s) still hold the old plaintext key -- rotate the "
            f"OpenRouter key, then delete: {', '.join(legacy_files)}",
        ))
    else:
        checks.append(Check("legacy config", True, "no inert legacy files"))

    if blob is not None:
        checks.append(Check(
            "web search", True,
            "on" if ccr_v3.websearch_online_v3(blob) else "off",
        ))
    return checks
