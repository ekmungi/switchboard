# guard.py - Shared safety layer: validates a model id against the catalog.
#
# Prevents "stale or too-small model" failures by checking id existence and
# minimum context-window size before the model is used by any command.

from dataclasses import dataclass, field

from .catalog import Model

# Minimum acceptable context length.  Claude Code's prompt is ~56K tokens,
# so 64K provides a comfortable margin.
MIN_CONTEXT: int = 64_000


@dataclass(frozen=True)
class Verdict:
    """Result of a validate_model call.

    Fields:
        ok: True when the model is present in the catalog and meets the
            minimum context requirement.
        reason: Human-readable explanation of the verdict.
        suggestions: Up to 3 valid alternative model ids when ok is False,
            same-provider first, then cheapest-overall; empty on success.
    """

    ok: bool
    reason: str
    suggestions: list[str] = field(default_factory=list)


def _valid_models(catalog: list[Model]) -> list[Model]:
    """Return every model in *catalog* that meets the minimum context requirement.

    Args:
        catalog: The full list of Model instances to screen.

    Returns:
        A list of Model instances whose context_length >= MIN_CONTEXT.
    """
    return [m for m in catalog if m.context_length >= MIN_CONTEXT]


def _suggestions(target_id: str, catalog: list[Model]) -> list[str]:
    """Build an ordered list of up to 3 valid alternative model ids.

    Strategy (FR1 spec):
    1. Collect all valid (context >= MIN_CONTEXT) models from the same provider
       (prefix before the first "/"), sorted by prompt_price ascending.
    2. Append all remaining valid models sorted by prompt_price ascending.
    3. Deduplicate while preserving order; return the first 3 ids.

    Args:
        target_id: The model id being validated (may or may not be in catalog).
        catalog: The full model catalog.

    Returns:
        An ordered list of up to 3 valid model id strings.
    """
    provider = target_id.split("/")[0] if "/" in target_id else target_id
    valid = _valid_models(catalog)

    same_provider = sorted(
        [m for m in valid if m.id.split("/")[0] == provider],
        key=lambda m: m.prompt_price,
    )
    other_provider = sorted(
        [m for m in valid if m.id.split("/")[0] != provider],
        key=lambda m: m.prompt_price,
    )

    # Deduplicate preserving order (same provider first, then others)
    seen: set[str] = set()
    ordered: list[str] = []
    for m in same_provider + other_provider:
        if m.id not in seen:
            seen.add(m.id)
            ordered.append(m.id)
        if len(ordered) == 3:
            break

    return ordered


def validate_model(model_id: str, catalog: list[Model]) -> Verdict:
    """Validate that *model_id* exists in *catalog* and meets the minimum context size.

    Two failure modes:
    - Unknown id: model_id is not present in the catalog.
    - Too-small context: model is present but context_length < MIN_CONTEXT.

    In both failure cases, *suggestions* lists up to 3 valid alternatives
    (same provider first, then cheapest overall).

    Args:
        model_id: The OpenRouter model id to validate (e.g. 'deepseek/deepseek-chat').
        catalog: The list of Model instances representing the full catalog.

    Returns:
        A Verdict with ok=True when the model is found and context >= MIN_CONTEXT,
        or ok=False with a reason string and suggestions list otherwise.
    """
    # Look up the model by id
    match = next((m for m in catalog if m.id == model_id), None)

    if match is None:
        return Verdict(
            ok=False,
            reason=f"'{model_id}' is not in the OpenRouter catalog.",
            suggestions=_suggestions(model_id, catalog),
        )

    ctx = match.context_length
    if ctx < MIN_CONTEXT:
        return Verdict(
            ok=False,
            reason=(
                f"'{model_id}' context {ctx:,} is below the {MIN_CONTEXT:,} minimum "
                f"(Claude Code's prompt is ~56K)."
            ),
            suggestions=_suggestions(model_id, catalog),
        )

    return Verdict(
        ok=True,
        reason=f"'{model_id}' OK ({ctx:,} context).",
        suggestions=[],
    )
