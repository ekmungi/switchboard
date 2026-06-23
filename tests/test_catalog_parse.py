# test_catalog_parse.py - Tests for Model dataclass, parse_models, and _safe_price.
#
# Network calls are NOT made in this file. Fixtures are loaded from disk.
# ---------------------------------------------------------------------------

import json
import pathlib

import pytest

from switchboard.catalog import (
    Model,
    parse_models,
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file from tests/fixtures/ and return parsed dict."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture()
def sample_payload() -> dict:
    """Return the models_sample.json fixture as a parsed dict."""
    return load_fixture("models_sample.json")


@pytest.fixture()
def sample_models(sample_payload: dict) -> list[Model]:
    """Return parsed Model list from the sample fixture."""
    return parse_models(sample_payload)


# ---------------------------------------------------------------------------
# parse_models: field mapping
# ---------------------------------------------------------------------------


def test_parse_models_returns_list(sample_payload: dict) -> None:
    """parse_models returns a non-empty list for a valid payload."""
    result = parse_models(sample_payload)
    assert isinstance(result, list)
    assert len(result) > 0


def test_parse_models_maps_id(sample_models: list[Model]) -> None:
    """parse_models maps the 'id' field from each model dict."""
    ids = [m.id for m in sample_models]
    assert "deepseek/deepseek-v4-flash" in ids
    assert "deepseek/deepseek-chat" in ids


def test_parse_models_maps_name(sample_models: list[Model]) -> None:
    """parse_models maps the 'name' field from each model dict."""
    by_id = {m.id: m for m in sample_models}
    assert by_id["deepseek/deepseek-v4-flash"].name == "DeepSeek V4 Flash"
    assert by_id["deepseek/deepseek-chat"].name == "DeepSeek V3"


def test_parse_models_maps_context_length(sample_models: list[Model]) -> None:
    """parse_models maps context_length correctly."""
    by_id = {m.id: m for m in sample_models}
    assert by_id["deepseek/deepseek-v4-flash"].context_length == 1048576
    assert by_id["deepseek/deepseek-chat"].context_length == 32768


def test_parse_models_maps_prompt_price(sample_models: list[Model]) -> None:
    """parse_models maps prompt_price as a raw per-token float."""
    by_id = {m.id: m for m in sample_models}
    assert by_id["deepseek/deepseek-v4-flash"].prompt_price == pytest.approx(9e-8)
    assert by_id["deepseek/deepseek-chat"].prompt_price == pytest.approx(2e-7)


def test_parse_models_maps_completion_price(sample_models: list[Model]) -> None:
    """parse_models maps completion_price as a raw per-token float."""
    by_id = {m.id: m for m in sample_models}
    assert by_id["deepseek/deepseek-v4-flash"].completion_price == pytest.approx(0.0)
    assert by_id["openai/gpt-4o"].completion_price == pytest.approx(1e-5)


# ---------------------------------------------------------------------------
# parse_models: defaults for missing fields
# ---------------------------------------------------------------------------


def test_parse_models_missing_pricing_defaults_to_zero(sample_models: list[Model]) -> None:
    """Model with no 'pricing' key gets prompt_price=0 and completion_price=0."""
    by_id = {m.id: m for m in sample_models}
    m = by_id["meta-llama/llama-3-8b-instruct"]
    assert m.prompt_price == 0.0
    assert m.completion_price == 0.0


def test_parse_models_missing_context_length_defaults_to_zero() -> None:
    """Model with no 'context_length' key gets context_length=0."""
    payload = {"data": [{"id": "x/y", "pricing": {"prompt": "0", "completion": "0"}}]}
    result = parse_models(payload)
    assert len(result) == 1
    assert result[0].context_length == 0


def test_parse_models_missing_name_defaults_to_empty_string() -> None:
    """Model with no 'name' key gets name=''."""
    payload = {"data": [{"id": "x/y"}]}
    result = parse_models(payload)
    assert result[0].name == ""


def test_parse_models_none_price_defaults_to_zero() -> None:
    """A null/None price value defaults to 0.0."""
    payload = {"data": [{"id": "x/y", "pricing": {"prompt": None, "completion": None}}]}
    result = parse_models(payload)
    assert result[0].prompt_price == 0.0
    assert result[0].completion_price == 0.0


def test_parse_models_empty_string_price_defaults_to_zero() -> None:
    """An empty-string price value defaults to 0.0."""
    payload = {"data": [{"id": "x/y", "pricing": {"prompt": "", "completion": ""}}]}
    result = parse_models(payload)
    assert result[0].prompt_price == 0.0
    assert result[0].completion_price == 0.0


def test_parse_models_missing_data_key_returns_empty_list() -> None:
    """Payload with no 'data' key returns an empty list."""
    result = parse_models({})
    assert result == []


# ---------------------------------------------------------------------------
# parse_models: Model is frozen (immutable)
# ---------------------------------------------------------------------------


def test_model_is_frozen(sample_models: list[Model]) -> None:
    """Model instances must be immutable (frozen dataclass)."""
    m = sample_models[0]
    with pytest.raises((AttributeError, TypeError)):
        m.id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_models: defensive id handling
# ---------------------------------------------------------------------------


def test_parse_models_skips_entry_with_missing_id() -> None:
    """Entries with no 'id' key are silently skipped; valid entries are returned.

    Verifies that a malformed API response does not raise KeyError and does not
    stop processing of the remaining valid entries.
    """
    payload = {
        "data": [
            {"name": "No ID model", "context_length": 100},
            {"id": "", "name": "Empty ID model"},
            {"id": None, "name": "None ID model"},
            {"id": "valid/model", "name": "Valid", "context_length": 512},
        ]
    }
    result = parse_models(payload)
    assert len(result) == 1
    assert result[0].id == "valid/model"
    assert result[0].context_length == 512


def test_parse_models_int_id_coerced_to_str() -> None:
    """An integer 'id' value is coerced to str (no type error, no skip).

    The guard ``if not entry_id`` passes for a non-zero int; str(entry_id)
    must produce a valid string id rather than raising TypeError.
    """
    payload = {"data": [{"id": 42, "name": "Int ID model", "context_length": 65536}]}
    result = parse_models(payload)
    assert len(result) == 1
    assert result[0].id == "42"
    assert isinstance(result[0].id, str)
