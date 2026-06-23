# test_health_model.py - Tests for health.role_model, effective_model, model_problem.
#
# All functions accept plain dicts and Model instances; no network or file I/O.
# ---------------------------------------------------------------------------

from switchboard.catalog import Model
from switchboard.health import (
    role_model,
    model_problem,
    effective_model,
)

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

_MODEL_ABSENT = Model(
    id="acme/unknown-model",
    name="Unknown",
    context_length=128_000,
    prompt_price=0.000001,
    completion_price=0.000002,
)

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
# role_model
# ---------------------------------------------------------------------------


def test_role_model_strips_provider_prefix_and_online():
    """role_model extracts the bare model id from a full CCR role value."""
    assert role_model("openrouter,deepseek/deepseek-v4-flash:online") == "deepseek/deepseek-v4-flash"


def test_role_model_strips_provider_prefix_no_online():
    """role_model handles a value without the :online suffix."""
    assert role_model("openrouter,deepseek/deepseek-chat") == "deepseek/deepseek-chat"


def test_role_model_no_comma_strips_online_only():
    """role_model treats the full string as the model id when no comma present."""
    assert role_model("deepseek/deepseek-chat:online") == "deepseek/deepseek-chat"


def test_role_model_no_comma_no_online():
    """role_model with bare model id and no comma or :online returns it unchanged."""
    assert role_model("deepseek/deepseek-chat") == "deepseek/deepseek-chat"


def test_role_model_preserves_slashes():
    """role_model does not disturb slashes within the model id."""
    assert role_model("openrouter,provider/sub/model") == "provider/sub/model"


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
        "background": "openrouter,deepseek/deepseek-chat",
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
    assert result is None


def test_model_problem_empty_catalog_still_flags_haiku():
    """model_problem with empty catalog still flags the haiku/anthropic check."""
    result = model_problem("anthropic/claude-3-5-haiku", [])
    assert result is not None
    assert "Anthropic/Haiku" in result or "haiku" in result.lower()


def test_model_problem_haiku_check_wins_over_not_in_catalog():
    """model_problem returns haiku suffix (not not-in-catalog) when both would apply."""
    result = model_problem("anthropic/claude-3-5-haiku", [_MODEL_LARGE])
    assert result is not None
    assert "Anthropic/Haiku" in result
