# test_health_warnings.py - Tests for health.role_warnings.
#
# All functions accept plain dicts and Model instances; no network or file I/O.
# ---------------------------------------------------------------------------

from switchboard.catalog import Model
from switchboard.health import role_warnings

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_MODEL_LARGE = Model(
    id="deepseek/deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    context_length=1_048_576,
    prompt_price=0.0000001,
    completion_price=0.0000003,
)

_MODEL_SMALL = Model(
    id="x/small-model",
    name="Small",
    context_length=32_768,
    prompt_price=0.0000001,
    completion_price=0.0000002,
)

_MODEL_HAIKU = Model(
    id="anthropic/claude-3-5-haiku",
    name="Claude 3.5 Haiku",
    context_length=200_000,
    prompt_price=0.000001,
    completion_price=0.000005,
)

_MODEL_ABSENT = Model(
    id="acme/unknown-model",
    name="Unknown",
    context_length=128_000,
    prompt_price=0.000001,
    completion_price=0.000002,
)

_CATALOG_GOOD = [_MODEL_LARGE]
_CATALOG_WITH_SMALL = [_MODEL_LARGE, _MODEL_SMALL]

_ROUTER_ALL_AGREE = {
    "default": "openrouter,deepseek/deepseek-v4-flash",
    "background": "openrouter,deepseek/deepseek-v4-flash",
    "think": "openrouter,deepseek/deepseek-v4-flash",
    "longContext": "openrouter,deepseek/deepseek-v4-flash",
    "webSearch": "openrouter,deepseek/deepseek-v4-flash",
}

_CFG_GOOD = {
    "APIKEY": "",
    "Router": _ROUTER_ALL_AGREE,
}

# ---------------------------------------------------------------------------
# role_warnings
# ---------------------------------------------------------------------------


def test_role_warnings_known_good_config_returns_empty():
    """role_warnings returns an empty list for a perfectly healthy configuration."""
    warnings = role_warnings(_CFG_GOOD, _CATALOG_GOOD)
    assert warnings == []


def test_role_warnings_context_too_small():
    """role_warnings flags a role whose model context is below MIN_CONTEXT."""
    router = {
        **_ROUTER_ALL_AGREE,
        "background": f"openrouter,{_MODEL_SMALL.id}",
    }
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_WITH_SMALL)
    assert any("background" in w and "context" in w and str(_MODEL_SMALL.id) in w
               for w in warnings), f"Unexpected warnings: {warnings}"
    assert any(f"{_MODEL_SMALL.context_length:,}" in w for w in warnings)


def test_role_warnings_anthropic_haiku_model_even_with_empty_catalog():
    """role_warnings flags an Anthropic/Haiku model even when catalog is empty."""
    router = {**_ROUTER_ALL_AGREE, "default": f"openrouter,{_MODEL_HAIKU.id}"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, [])
    assert any("Anthropic/Haiku" in w or "haiku" in w.lower() for w in warnings)
    assert any("default" in w for w in warnings)


def test_role_warnings_anthropic_prefix_triggers_warning():
    """role_warnings flags a model whose id starts with 'anthropic/'."""
    haiku_router = {**_ROUTER_ALL_AGREE, "think": "openrouter,anthropic/claude-3-5-haiku"}
    cfg = {"APIKEY": "", "Router": haiku_router}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("think" in w for w in warnings)


def test_role_warnings_haiku_in_name_triggers_warning():
    """role_warnings flags a model whose id contains 'haiku' regardless of provider."""
    router = {**_ROUTER_ALL_AGREE, "longContext": "openrouter,somevendor/haiku-mini"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("longContext" in w for w in warnings)


def test_role_warnings_non_blank_apikey():
    """role_warnings appends the APIKEY warning when APIKEY is not blank."""
    cfg = {"APIKEY": "sk-real-key", "Router": _ROUTER_ALL_AGREE}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("APIKEY" in w for w in warnings)


def test_role_warnings_websearch_online():
    """role_warnings appends the web-search warning when webSearch ends with :online."""
    router = {**_ROUTER_ALL_AGREE, "webSearch": "openrouter,deepseek/deepseek-v4-flash:online"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("web search" in w.lower() for w in warnings)


def test_role_warnings_not_in_catalog_with_non_empty_catalog():
    """role_warnings flags a role on a model absent from a non-empty catalog."""
    router = {**_ROUTER_ALL_AGREE, "default": f"openrouter,{_MODEL_ABSENT.id}"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("not in the catalog" in w and _MODEL_ABSENT.id in w for w in warnings)


def test_role_warnings_skip_catalog_checks_when_catalog_empty():
    """role_warnings does NOT emit not-in-catalog when catalog is empty (offline mode)."""
    router = {**_ROUTER_ALL_AGREE, "default": f"openrouter,{_MODEL_ABSENT.id}"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, [])
    assert not any("not in the catalog" in w for w in warnings)


def test_role_warnings_multiple_issues_all_reported():
    """role_warnings collects warnings from multiple roles and config checks."""
    router = {
        "default": "openrouter,deepseek/deepseek-v4-flash",
        "background": f"openrouter,{_MODEL_SMALL.id}",
        "think": "openrouter,deepseek/deepseek-v4-flash",
        "longContext": "openrouter,deepseek/deepseek-v4-flash",
        "webSearch": "openrouter,deepseek/deepseek-v4-flash:online",
    }
    cfg = {"APIKEY": "sk-not-blank", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_WITH_SMALL)
    assert any("background" in w for w in warnings)
    assert any("APIKEY" in w for w in warnings)
    assert any("web search" in w.lower() for w in warnings)
    assert len(warnings) >= 3


def test_role_warnings_tilde_anthropic_prefix_triggers_warning():
    """role_warnings flags a model whose id starts with '~anthropic/' as a leak risk."""
    router = {**_ROUTER_ALL_AGREE, "background": "openrouter,~anthropic/claude-haiku-3"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("background" in w for w in warnings), (
        f"Expected warning for background role with ~anthropic/ prefix, got: {warnings}"
    )
    assert any("Anthropic/Haiku" in w or "haiku" in w.lower() for w in warnings)
