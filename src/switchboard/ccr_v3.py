# ccr_v3.py - Pure accessors/updaters over the CCR v3 config blob (no I/O).
#
# On v3 the routed model rides on the claude-code launch profile
# (profile.profiles[].model/smallFastModel, format '<provider>/<model-id>'),
# NOT on the legacy role-based Router (R-006/DEC-008).  All updaters are
# immutable: they return new dicts and never touch the input blob; untargeted
# keys (including the secret Providers[].api_key) ride along by reference,
# never copied elsewhere or printed.

ONLINE_SUFFIX: str = ":online"
"""OpenRouter web-search suffix on a model id (billing-relevant)."""

DEFAULT_PROVIDER: str = "openrouter"
"""Provider name assumed when the blob has no preferredProvider."""


def _provider_name(blob: dict) -> str:
    """Return the preferred provider name ('openrouter' fallback)."""
    return blob.get("preferredProvider") or DEFAULT_PROVIDER


def claude_profile(blob: dict) -> dict | None:
    """Return the claude-code launch profile entry, or None.

    Args:
        blob: The parsed v3 config blob.

    Returns:
        The first profile.profiles[] dict with agent == 'claude-code', else None.
    """
    for prof in blob.get("profile", {}).get("profiles", []):
        if prof.get("agent") == "claude-code":
            return prof
    return None


def _bare_id(value: str | None, provider: str) -> str | None:
    """Strip '<provider>/' prefix and ':online' suffix from a profile model value."""
    if not value:
        return None
    if value.startswith(f"{provider}/"):
        value = value[len(provider) + 1:]
    if value.endswith(ONLINE_SUFFIX):
        value = value[: -len(ONLINE_SUFFIX)]
    return value


def store_model_id(blob: dict) -> str | None:
    """Return the bare OpenRouter model id from the profile's model, or None."""
    prof = claude_profile(blob)
    return _bare_id(prof.get("model"), _provider_name(blob)) if prof else None


def small_fast_id(blob: dict) -> str | None:
    """Return the bare OpenRouter model id from smallFastModel, or None."""
    prof = claude_profile(blob)
    return _bare_id(prof.get("smallFastModel"), _provider_name(blob)) if prof else None


def websearch_online_v3(blob: dict) -> bool:
    """True iff the profile model OR smallFastModel carries the ':online' suffix.

    Both fields are billing-relevant, so a stray suffix on either counts as ON
    (mirrors strip_online, which cleans both).
    """
    prof = claude_profile(blob)
    if prof is None:
        return False
    return any(
        str(prof.get(field, "")).endswith(ONLINE_SUFFIX)
        for field in ("model", "smallFastModel")
    )


def router_summary(blob: dict) -> dict:
    """Summarize the v3 Router for display: enabled builtins, rule count, fallback.

    Returns:
        {'builtin': [names], 'rules': int, 'fallback': str} -- degrades to
        empty/off values when the Router key is absent.
    """
    router = blob.get("Router", {})
    builtins = [
        name for name, spec in router.get("builtInRules", {}).items()
        if isinstance(spec, dict) and spec.get("enabled")
    ]
    return {
        "builtin": builtins,
        "rules": len(router.get("rules", [])),
        "fallback": router.get("fallback", {}).get("mode", "off"),
    }


def applied_model(settings: dict) -> str | None:
    """Return env.ANTHROPIC_MODEL from a parsed ~/.claude/settings.json dict."""
    return settings.get("env", {}).get("ANTHROPIC_MODEL") or None


def _replace_claude_profile(blob: dict, new_prof: dict) -> dict:
    """Return a new blob with the claude-code profile entry replaced."""
    profiles = [
        new_prof if p.get("agent") == "claude-code" else p
        for p in blob.get("profile", {}).get("profiles", [])
    ]
    return {**blob, "profile": {**blob.get("profile", {}), "profiles": profiles}}


def set_profile_model(blob: dict, model_id: str) -> dict:
    """Return a new blob with the claude-code profile pinned to *model_id*.

    Sets BOTH model and smallFastModel to '<provider>/<model_id>' so
    background/small-fast traffic cannot leak to another model (the v3
    equivalent of the old pin-all-roles invariant).

    Raises:
        ValueError: when the blob has no claude-code profile to pin.
    """
    prof = claude_profile(blob)
    if prof is None:
        raise ValueError("no claude-code launch profile in the CCR config")
    value = f"{_provider_name(blob)}/{model_id}"
    return _replace_claude_profile(
        blob, {**prof, "model": value, "smallFastModel": value}
    )


def ensure_whitelisted(blob: dict, model_id: str) -> tuple[dict, bool]:
    """Ensure *model_id* is in the preferred provider's models whitelist.

    The whitelist is baked into the generated gateway config, so a change
    here requires a gateway reload (SPEC-004 R6) -- hence the changed flag.

    Returns:
        (new blob, changed) -- changed is False when already whitelisted.

    Raises:
        ValueError: when no provider entry matches preferredProvider.
    """
    name = _provider_name(blob)
    providers = blob.get("Providers", [])
    target = next((p for p in providers if p.get("name") == name), None)
    if target is None:
        raise ValueError(f"no '{name}' provider entry in the CCR config")
    if model_id in target.get("models", []):
        return blob, False
    new_target = {**target, "models": [*target.get("models", []), model_id]}
    new_providers = [new_target if p is target else p for p in providers]
    return {**blob, "Providers": new_providers}, True


def provider_models(blob: dict) -> list[str] | None:
    """Return the preferred provider's models whitelist, or None if no provider.

    The whitelist is what the generated gateway config serves for model
    discovery/routing -- membership matters for whether a pinned model works.
    """
    name = _provider_name(blob)
    target = next((p for p in blob.get("Providers", []) if p.get("name") == name), None)
    return list(target.get("models", [])) if target is not None else None


def set_apikey_blank(blob: dict) -> dict:
    """Return a new blob with the top-level (inbound) APIKEY forced to ''."""
    return {**blob, "APIKEY": ""}


def strip_online(blob: dict) -> tuple[dict, bool]:
    """Return a new blob with any ':online' suffix stripped from the profile.

    Covers both model and smallFastModel.  No-op (changed=False) when there
    is no suffix or no claude-code profile.
    """
    prof = claude_profile(blob)
    if prof is None:
        return blob, False
    new_prof = dict(prof)
    changed = False
    for field in ("model", "smallFastModel"):
        value = str(new_prof.get(field, ""))
        if value.endswith(ONLINE_SUFFIX):
            new_prof[field] = value[: -len(ONLINE_SUFFIX)]
            changed = True
    if not changed:
        return blob, False
    return _replace_claude_profile(blob, new_prof), True
