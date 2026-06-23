# tests/test_health.py - TDD tests for switchboard.health (pure logic, no I/O).
#
# All functions accept plain dicts and Model instances constructed inline;
# no network calls, no filesystem access.
# ---------------------------------------------------------------------------

import pytest
from switchboard.catalog import Model
from switchboard.health import (
    _role_model,
    model_problem,
    effective_model,
    apikey_blank,
    websearch_online,
    role_warnings,
    status_lines,
)
from switchboard.guard import MIN_CONTEXT

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# A healthy large-context model (1M context, not Anthropic/Haiku).
_MODEL_LARGE = Model(
    id="deepseek/deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    context_length=1_048_576,
    prompt_price=0.0000001,
    completion_price=0.0000003,
)

# A model whose context is below MIN_CONTEXT (32 K).
_MODEL_SMALL = Model(
    id="x/small-model",
    name="Small",
    context_length=32_768,
    prompt_price=0.0000001,
    completion_price=0.0000002,
)

# An Anthropic Haiku model (triggers the Anthropic/Haiku warning).
_MODEL_HAIKU = Model(
    id="anthropic/claude-3-5-haiku",
    name="Claude 3.5 Haiku",
    context_length=200_000,
    prompt_price=0.000001,
    completion_price=0.000005,
)

# A model that is simply absent from whatever catalog is passed in.
_MODEL_ABSENT = Model(
    id="acme/unknown-model",
    name="Unknown",
    context_length=128_000,
    prompt_price=0.000001,
    completion_price=0.000002,
)

# Small catalog used in most role_warnings tests.
_CATALOG_GOOD = [_MODEL_LARGE]
_CATALOG_WITH_SMALL = [_MODEL_LARGE, _MODEL_SMALL]

# A known-good router: all five roles, same large-context model, no :online.
_ROUTER_ALL_AGREE = {
    "default": "openrouter,deepseek/deepseek-v4-flash",
    "background": "openrouter,deepseek/deepseek-v4-flash",
    "think": "openrouter,deepseek/deepseek-v4-flash",
    "longContext": "openrouter,deepseek/deepseek-v4-flash",
    "webSearch": "openrouter,deepseek/deepseek-v4-flash",
}

# A good config (APIKEY blank, webSearch without :online).
_CFG_GOOD = {
    "APIKEY": "",
    "Router": _ROUTER_ALL_AGREE,
}


# ---------------------------------------------------------------------------
# _role_model
# ---------------------------------------------------------------------------


def test_role_model_strips_provider_prefix_and_online():
    """_role_model extracts the bare model id from a full CCR role value."""
    assert _role_model("openrouter,deepseek/deepseek-v4-flash:online") == "deepseek/deepseek-v4-flash"


def test_role_model_strips_provider_prefix_no_online():
    """_role_model handles a value without the :online suffix."""
    assert _role_model("openrouter,deepseek/deepseek-chat") == "deepseek/deepseek-chat"


def test_role_model_no_comma_strips_online_only():
    """_role_model treats the full string as the model id when no comma present."""
    assert _role_model("deepseek/deepseek-chat:online") == "deepseek/deepseek-chat"


def test_role_model_no_comma_no_online():
    """_role_model with bare model id and no comma or :online returns it unchanged."""
    assert _role_model("deepseek/deepseek-chat") == "deepseek/deepseek-chat"


def test_role_model_preserves_slashes():
    """_role_model does not disturb slashes within the model id."""
    assert _role_model("openrouter,provider/sub/model") == "provider/sub/model"


# ---------------------------------------------------------------------------
# effective_model
# ---------------------------------------------------------------------------


def test_effective_model_all_agree_returns_id():
    """effective_model returns the shared id when every role resolves to the same one."""
    assert effective_model(_CFG_GOOD) == "deepseek/deepseek-v4-flash"


def test_effective_model_websearch_online_does_not_count_as_disagreement():
    """effective_model treats webSearch :online as the same base model."""
    router = {**_ROUTER_ALL_AGREE, "webSearch": "openrouter,deepseek/deepseek-v4-flash:online"}
    cfg = {"Router": router}
    assert effective_model(cfg) == "deepseek/deepseek-v4-flash"


def test_effective_model_disagreement_returns_none():
    """effective_model returns None when roles point to different models."""
    router = {
        **_ROUTER_ALL_AGREE,
        "background": "openrouter,deepseek/deepseek-chat",  # different model
    }
    cfg = {"Router": router}
    assert effective_model(cfg) is None


def test_effective_model_no_router_returns_none():
    """effective_model returns None when no Router key exists."""
    assert effective_model({}) is None


def test_effective_model_empty_router_returns_none():
    """effective_model returns None when Router is present but has no ROLES entries."""
    assert effective_model({"Router": {}}) is None


# ---------------------------------------------------------------------------
# apikey_blank
# ---------------------------------------------------------------------------


def test_apikey_blank_true_when_empty_string():
    """apikey_blank returns True for APIKEY = ''."""
    assert apikey_blank({"APIKEY": ""}) is True


def test_apikey_blank_true_when_key_absent():
    """apikey_blank returns True when APIKEY key is missing entirely."""
    assert apikey_blank({}) is True


def test_apikey_blank_false_when_non_empty():
    """apikey_blank returns False for a non-blank APIKEY value."""
    assert apikey_blank({"APIKEY": "sk-some-key"}) is False


# ---------------------------------------------------------------------------
# websearch_online
# ---------------------------------------------------------------------------


def test_websearch_online_true_when_ends_with_online():
    """websearch_online returns True when webSearch ends with ':online'."""
    cfg = {"Router": {"webSearch": "openrouter,deepseek/deepseek-chat:online"}}
    assert websearch_online(cfg) is True


def test_websearch_online_false_without_suffix():
    """websearch_online returns False when webSearch does not end with ':online'."""
    cfg = {"Router": {"webSearch": "openrouter,deepseek/deepseek-chat"}}
    assert websearch_online(cfg) is False


def test_websearch_online_false_when_no_websearch_key():
    """websearch_online returns False when the webSearch key is absent."""
    assert websearch_online({"Router": {}}) is False


# ---------------------------------------------------------------------------
# role_warnings
# ---------------------------------------------------------------------------


def test_role_warnings_known_good_config_returns_empty():
    """role_warnings returns an empty list for a perfectly healthy configuration.

    All roles point to a large-context catalog model, APIKEY is blank, and
    webSearch is not :online.
    """
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
    # Empty catalog: membership/context checks must be skipped; haiku check must run.
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
    # catalog does NOT contain _MODEL_ABSENT
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("not in the catalog" in w and _MODEL_ABSENT.id in w for w in warnings)


def test_role_warnings_skip_catalog_checks_when_catalog_empty():
    """role_warnings does NOT emit not-in-catalog when catalog is empty (offline mode)."""
    router = {**_ROUTER_ALL_AGREE, "default": f"openrouter,{_MODEL_ABSENT.id}"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, [])
    # Should be clean: absent model is not haiku/anthropic, catalog is empty -> no warning.
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
    # Should have: background context too small + APIKEY warning + web-search warning
    assert any("background" in w for w in warnings)
    assert any("APIKEY" in w for w in warnings)
    assert any("web search" in w.lower() for w in warnings)
    assert len(warnings) >= 3


def test_role_warnings_tilde_anthropic_prefix_triggers_warning():
    """role_warnings flags a model whose id starts with '~anthropic/' as a leak risk.

    Exercises the startswith('~anthropic/') branch in the Anthropic/Haiku check.
    """
    router = {**_ROUTER_ALL_AGREE, "background": "openrouter,~anthropic/claude-haiku-3"}
    cfg = {"APIKEY": "", "Router": router}
    warnings = role_warnings(cfg, _CATALOG_GOOD)
    assert any("background" in w for w in warnings), (
        f"Expected warning for background role with ~anthropic/ prefix, got: {warnings}"
    )
    assert any("Anthropic/Haiku" in w or "haiku" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# model_problem
# ---------------------------------------------------------------------------


def test_model_problem_healthy_returns_none():
    """model_problem returns None for a healthy large-context catalog model."""
    result = model_problem(_MODEL_LARGE.id, [_MODEL_LARGE])
    assert result is None


def test_model_problem_haiku_detected_by_anthropic_prefix():
    """model_problem detects 'anthropic/' prefix and returns the haiku suffix."""
    result = model_problem("anthropic/claude-3-5-haiku", [_MODEL_LARGE])
    assert result is not None
    assert "Anthropic/Haiku" in result or "haiku" in result.lower()


def test_model_problem_haiku_detected_by_tilde_prefix():
    """model_problem detects '~anthropic/' prefix and returns the haiku suffix."""
    result = model_problem("~anthropic/claude-haiku-3", [_MODEL_LARGE])
    assert result is not None
    assert "Anthropic/Haiku" in result or "haiku" in result.lower()


def test_model_problem_haiku_detected_by_substring():
    """model_problem detects 'haiku' anywhere in the id, regardless of provider."""
    result = model_problem("somevendor/haiku-mini", [_MODEL_LARGE])
    assert result is not None
    assert "Anthropic/Haiku" in result or "haiku" in result.lower()


def test_model_problem_not_in_catalog_with_non_empty_catalog():
    """model_problem detects model absent from a non-empty catalog."""
    result = model_problem(_MODEL_ABSENT.id, [_MODEL_LARGE])
    assert result is not None
    assert "not in the catalog" in result


def test_model_problem_context_too_small():
    """model_problem detects context below MIN_CONTEXT for a catalog model."""
    result = model_problem(_MODEL_SMALL.id, [_MODEL_LARGE, _MODEL_SMALL])
    assert result is not None
    assert "context" in result
    assert f"{_MODEL_SMALL.context_length:,}" in result


def test_model_problem_empty_catalog_skips_membership_check():
    """model_problem with empty catalog does NOT report not-in-catalog for a non-haiku model."""
    result = model_problem(_MODEL_ABSENT.id, [])
    # Absent model is not haiku/anthropic -> no problem in offline mode
    assert result is None


def test_model_problem_empty_catalog_still_flags_haiku():
    """model_problem with empty catalog still flags the haiku/anthropic check."""
    result = model_problem("anthropic/claude-3-5-haiku", [])
    assert result is not None
    assert "Anthropic/Haiku" in result or "haiku" in result.lower()


def test_model_problem_haiku_check_wins_over_not_in_catalog():
    """model_problem returns haiku suffix (not not-in-catalog) when both would apply."""
    # anthropic/claude-3-5-haiku is not in _CATALOG_GOOD (which only has deepseek)
    result = model_problem("anthropic/claude-3-5-haiku", [_MODEL_LARGE])
    assert result is not None
    assert "Anthropic/Haiku" in result  # haiku check fires, not not-in-catalog


# ---------------------------------------------------------------------------
# status_lines
# ---------------------------------------------------------------------------


def test_status_lines_known_good_config():
    """status_lines returns four status lines and no WARNINGS for a healthy config."""
    lines = status_lines(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    assert len(lines) == 4
    assert lines[0] == "Effective model : deepseek/deepseek-v4-flash"
    assert lines[1] == "CCR running     : yes"
    assert lines[2] == "APIKEY blank    : yes"
    assert lines[3] == "Web search      : off"
    assert not any("WARNINGS" in ln for ln in lines)


def test_status_lines_broken_config_includes_warnings():
    """status_lines appends WARNINGS: and indented items when issues exist."""
    router = {
        **_ROUTER_ALL_AGREE,
        "background": f"openrouter,{_MODEL_SMALL.id}",
    }
    cfg = {"APIKEY": "sk-real", "Router": router}
    lines = status_lines(cfg, _CATALOG_WITH_SMALL, ccr_up=False)

    # First four lines must still be the status block
    assert lines[1] == "CCR running     : no"
    assert lines[2] == "APIKEY blank    : NO"

    # WARNINGS: line must appear after the four status lines
    assert "WARNINGS:" in lines
    warnings_idx = lines.index("WARNINGS:")
    assert warnings_idx >= 4

    # At least one indented warning line must follow it
    assert any(ln.startswith("  ") for ln in lines[warnings_idx + 1:])
