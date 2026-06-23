# test_catalog_helpers.py - Tests for filter_models, per_million, and fetch_models (mocked HTTP).
#
# Network calls are patched out via unittest.mock -- no live HTTP in any test.
# ---------------------------------------------------------------------------

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
# fetch_models: patched HTTP (no live network)
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
