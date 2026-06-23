# tests/test_catalog.py - tests for the switchboard.catalog module.
#
# TDD: tests are written before the implementation. Run uv run pytest to verify.
# Network calls are patched out via unittest.mock -- no live HTTP in any test.

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from switchboard.catalog import (
    Model,
    fetch_models,
    filter_models,
    parse_models,
    per_million,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

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
    # meta-llama/llama-3-8b-instruct has no pricing field in the fixture
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
# filter_models
# ---------------------------------------------------------------------------


def test_filter_models_empty_query_returns_all(sample_models: list[Model]) -> None:
    """An empty query string returns all models unchanged."""
    result = filter_models(sample_models, "")
    assert len(result) == len(sample_models)


def test_filter_models_matches_by_id(sample_models: list[Model]) -> None:
    """filter_models matches models whose id contains the query."""
    result = filter_models(sample_models, "deepseek")
    ids = [m.id for m in result]
    assert "deepseek/deepseek-v4-flash" in ids
    assert "deepseek/deepseek-chat" in ids
    assert "openai/gpt-4o" not in ids


def test_filter_models_matches_by_name(sample_models: list[Model]) -> None:
    """filter_models matches models whose name contains the query."""
    result = filter_models(sample_models, "GPT")
    assert len(result) == 1
    assert result[0].id == "openai/gpt-4o"


def test_filter_models_case_insensitive(sample_models: list[Model]) -> None:
    """filter_models match is case-insensitive."""
    upper = filter_models(sample_models, "DEEPSEEK")
    lower = filter_models(sample_models, "deepseek")
    assert [m.id for m in upper] == [m.id for m in lower]


def test_filter_models_no_match_returns_empty(sample_models: list[Model]) -> None:
    """filter_models returns an empty list when no model matches."""
    result = filter_models(sample_models, "zzznonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# per_million
# ---------------------------------------------------------------------------


def test_per_million_converts_string_price() -> None:
    """per_million converts a per-token price string to per-million float."""
    assert per_million("0.000001") == pytest.approx(1.0)


def test_per_million_converts_float_price() -> None:
    """per_million converts a per-token price float to per-million float."""
    assert per_million(0.0000025) == pytest.approx(2.5)


def test_per_million_handles_none() -> None:
    """per_million returns 0.0 when price is None."""
    assert per_million(None) == 0.0


def test_per_million_handles_empty_string() -> None:
    """per_million returns 0.0 when price is an empty string."""
    assert per_million("") == 0.0


def test_per_million_handles_non_numeric_string() -> None:
    """per_million returns 0.0 for non-numeric string input."""
    assert per_million("free") == 0.0


def test_per_million_zero_price() -> None:
    """per_million returns 0.0 for a zero price."""
    assert per_million("0") == 0.0
    assert per_million(0.0) == 0.0


# ---------------------------------------------------------------------------
# parse_models: defensive id handling (fix #1)
# ---------------------------------------------------------------------------


def test_parse_models_skips_entry_with_missing_id() -> None:
    """Entries with no 'id' key are silently skipped; valid entries are returned.

    Verifies that a malformed API response does not raise KeyError and does not
    stop processing of the remaining valid entries.
    """
    payload = {
        "data": [
            {"name": "No ID model", "context_length": 100},  # missing "id"
            {"id": "", "name": "Empty ID model"},            # empty string id
            {"id": None, "name": "None ID model"},           # None id
            {"id": "valid/model", "name": "Valid", "context_length": 512},
        ]
    }
    result = parse_models(payload)
    assert len(result) == 1
    assert result[0].id == "valid/model"
    assert result[0].context_length == 512


# ---------------------------------------------------------------------------
# fetch_models: patched HTTP (fix #2 -- no live network)
# ---------------------------------------------------------------------------


def test_fetch_models_returns_parsed_models_from_fixture() -> None:
    """fetch_models returns a list[Model] matching parse_models on the fixture.

    urllib.request.urlopen is patched so no live HTTP request is made. The mock
    context-manager's .read() returns the raw bytes of models_sample.json.
    Asserts that the deepseek-v4-flash entry is present with the expected values.
    """
    fixture_bytes: bytes = (FIXTURES_DIR / "models_sample.json").read_bytes()
    expected: list[Model] = parse_models(json.loads(fixture_bytes.decode("utf-8")))

    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = fixture_bytes

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = fetch_models()

    assert result == expected
    by_id = {m.id: m for m in result}
    flash = by_id["deepseek/deepseek-v4-flash"]
    assert flash.context_length == 1048576
    assert flash.prompt_price == pytest.approx(9e-8)
