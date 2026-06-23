# test_guard.py - Tests for the guard module: validate_model safety layer.
#
# TDD: these tests were written before guard.py existed and drove the implementation.

from switchboard.catalog import Model
from switchboard.guard import validate_model, MIN_CONTEXT

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CAT = [
    Model("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", 1048576, 9e-08, 0.0),
    Model("deepseek/deepseek-chat", "DeepSeek V3", 32768, 2e-07, 0.0),  # too small
]


# ---------------------------------------------------------------------------
# Verbatim tests from the task brief
# ---------------------------------------------------------------------------


def test_accepts_big_context():
    """A valid model with context >= MIN_CONTEXT returns ok=True."""
    assert validate_model("deepseek/deepseek-v4-flash", CAT).ok


def test_rejects_too_small_context():
    """A model with context < MIN_CONTEXT returns ok=False with a 'context' reason and suggestions."""
    v = validate_model("deepseek/deepseek-chat", CAT)
    assert not v.ok and "context" in v.reason.lower() and v.suggestions


def test_rejects_unknown_model():
    """An id not in the catalog returns ok=False with a 'not in' reason."""
    v = validate_model("nope/nope", CAT)
    assert not v.ok and "not in" in v.reason.lower()


# ---------------------------------------------------------------------------
# Boundary: exactly MIN_CONTEXT is accepted (>= is inclusive)
# ---------------------------------------------------------------------------


def test_accepts_exact_min_context():
    """A model with context_length exactly equal to MIN_CONTEXT is accepted."""
    cat = [Model("x/exact", "Exact", MIN_CONTEXT, 1e-06, 1e-06)]
    v = validate_model("x/exact", cat)
    assert v.ok


# ---------------------------------------------------------------------------
# Suggestion ordering: cheapest first, all >= MIN_CONTEXT
# ---------------------------------------------------------------------------


def test_suggestions_are_valid_and_cheapest_first():
    """Suggestions must all be valid (>=64K context) and sorted cheapest-first by prompt_price."""
    cat = [
        Model("a/cheap", "Cheap", 128_000, 1e-07, 0.0),
        Model("a/mid", "Mid", 128_000, 5e-07, 0.0),
        Model("a/expensive", "Expensive", 128_000, 9e-07, 0.0),
        Model("a/tiny", "Tiny", 4_096, 1e-08, 0.0),  # invalid: too small
    ]
    # Validate "a/tiny" (too small); expect suggestions to be the three valid ones
    v = validate_model("a/tiny", cat)
    assert not v.ok
    # All suggestions must be valid models
    valid_ids = {"a/cheap", "a/mid", "a/expensive"}
    for s in v.suggestions:
        assert s in valid_ids
    # First suggestion is cheapest
    assert v.suggestions[0] == "a/cheap"


# ---------------------------------------------------------------------------
# Same-provider preference: same-provider valid models appear before cheaper others
# ---------------------------------------------------------------------------


def test_suggestions_same_provider_before_others():
    """Same-provider valid models appear first in suggestions even if a cheaper cross-provider model exists."""
    cat = [
        Model("target/bad", "Bad", 8_000, 5e-07, 0.0),           # too small, provider=target
        Model("target/good", "Good", 128_000, 9e-07, 0.0),        # valid, same provider
        Model("other/cheap", "Other Cheap", 128_000, 1e-08, 0.0), # valid, cheaper, different provider
    ]
    v = validate_model("target/bad", cat)
    assert not v.ok
    assert len(v.suggestions) >= 2
    # Same-provider "target/good" must appear before the cheaper "other/cheap"
    assert v.suggestions.index("target/good") < v.suggestions.index("other/cheap")


# ---------------------------------------------------------------------------
# Fallback to cross-provider suggestions when same provider has no valid models
# ---------------------------------------------------------------------------


def test_suggestions_fallback_to_other_providers():
    """When the target provider has no valid models, suggestions come from other providers."""
    cat = [
        Model("noprovider/tiny", "Tiny", 4_096, 9e-07, 0.0),  # too small
        Model("other/big", "Big", 200_000, 2e-07, 0.0),        # valid, other provider
    ]
    v = validate_model("noprovider/tiny", cat)
    assert not v.ok
    assert v.suggestions  # non-empty
    assert "other/big" in v.suggestions


# ---------------------------------------------------------------------------
# Unknown model with suggestions: suggestions from overall valid catalog
# ---------------------------------------------------------------------------


def test_unknown_model_suggestions_from_catalog():
    """An unknown model id returns 'not in' reason; suggestions are still populated from valid catalog."""
    cat = [
        Model("x/large", "Large", 128_000, 1e-06, 0.0),
    ]
    v = validate_model("unknown/model", cat)
    assert not v.ok
    assert "not in" in v.reason.lower()
    # Suggestions should include valid models from the catalog
    assert "x/large" in v.suggestions


# ---------------------------------------------------------------------------
# Empty catalog edge case
# ---------------------------------------------------------------------------


def test_empty_catalog():
    """An empty catalog always returns not-ok; unknown id gets 'not in' reason, no suggestions."""
    v = validate_model("any/model", [])
    assert not v.ok
    assert "not in" in v.reason.lower()
    assert v.suggestions == []
