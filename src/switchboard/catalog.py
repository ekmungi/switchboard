# catalog.py - OpenRouter model catalog: fetch, parse, filter, and price utilities.
#
# Provides the Model dataclass and pure functions for working with the catalog.
# The CLI (switchboard.py) still uses its own dict-based copies until a later
# task wires this module in. No third-party runtime dependencies: urllib only.

import json
import urllib.request
from dataclasses import dataclass

OPENROUTER_MODELS_URL: str = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class Model:
    """Immutable representation of a single OpenRouter model entry.

    Fields:
        id: Unique model identifier (e.g. 'deepseek/deepseek-chat').
        name: Human-readable display name.
        context_length: Maximum context window in tokens (0 if unknown).
        prompt_price: Raw per-token input price as float (NOT per-million).
        completion_price: Raw per-token output price as float (NOT per-million).
    """

    id: str
    name: str
    context_length: int
    prompt_price: float
    completion_price: float


def _safe_price(value: object) -> float:
    """Convert a price value (string, float, None, or empty) to a float.

    Returns 0.0 for None, empty string, or any non-numeric value.

    Args:
        value: The raw price value from the API response.

    Returns:
        The price as a float, or 0.0 on any conversion failure.
    """
    try:
        # `or 0` collapses None / "" / other falsy values to 0 before float()
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_models(payload: dict) -> list[Model]:
    """Parse the top-level OpenRouter /models JSON object into a list of Model instances.

    Each model dict is mapped to a frozen Model dataclass. Missing or invalid
    fields fall back to safe defaults: empty string for name, 0 for context_length,
    and 0.0 for any price value.

    Args:
        payload: The parsed top-level OpenRouter JSON object (dict with a 'data' list).

    Returns:
        A list of Model instances. Returns [] if 'data' key is absent.
    """
    entries: list[dict] = payload.get("data", [])
    if not entries:
        return []

    models: list[Model] = []
    for entry in entries:
        # Skip any entry that is missing an "id" or has a None/empty id value;
        # a Model with no id would be unusable and likely signals a malformed
        # API response -- skip rather than raising KeyError or emitting bad data.
        entry_id: object = entry.get("id")
        if not entry_id:
            continue
        pricing: dict = entry.get("pricing") or {}
        models.append(
            Model(
                id=entry_id,  # type: ignore[arg-type]  # narrowed to non-empty str above
                name=entry.get("name", ""),
                context_length=entry.get("context_length", 0),
                prompt_price=_safe_price(pricing.get("prompt")),
                completion_price=_safe_price(pricing.get("completion")),
            )
        )
    return models


def fetch_models() -> list[Model]:
    """Fetch the live OpenRouter model catalog and return it as Model instances.

    Makes a single GET request to the OpenRouter /models endpoint using stdlib
    urllib (no third-party deps). Times out after 30 seconds.

    Returns:
        A list of Model instances parsed from the live catalog response.
    """
    with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=30) as resp:
        payload: dict = json.loads(resp.read().decode("utf-8"))
    return parse_models(payload)


def filter_models(models: list[Model], query: str) -> list[Model]:
    """Return models whose id or name contains query (case-insensitive).

    An empty query returns all models unchanged.

    Args:
        models: The list of Model instances to filter.
        query: The search string. Case-insensitive substring match against id and name.

    Returns:
        A filtered list of Model instances. Returns all models if query is empty.
    """
    if not query:
        return list(models)
    q = query.lower()
    return [
        m for m in models
        if q in m.id.lower() or q in m.name.lower()
    ]


def per_million(price: object) -> float:
    """Convert a raw per-token price to a per-million-token float.

    Accepts a price as a string, float, int, None, or empty string. Returns
    0.0 for None, empty string, or any non-numeric value.

    Args:
        price: The raw per-token price value (from Model.prompt_price,
               Model.completion_price, or a direct API pricing field).

    Returns:
        The price per million tokens as a float, or 0.0 on invalid input.
    """
    try:
        return float(price or 0) * 1_000_000
    except (TypeError, ValueError):
        return 0.0
