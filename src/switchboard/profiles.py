# profiles.py - Model profile: the tier map that drives the translator (SPEC-005 R3).
#
# A profile is what the catalog picker produces: which OpenRouter model each Claude
# Code tier routes to. `sb code` sets ANTHROPIC_MODEL / ANTHROPIC_SMALL_FAST_MODEL to
# the profile's ids, so Claude Code emits those exact strings for the main + small
# tiers (they map explicitly); every other string Claude Code hard-codes internally
# (background/subagent helpers) lands on the concrete cheap catch-all. Switching
# models edits the profile and regenerates the engine config -- no reinstall. Storage
# is JSON under the switchboard home; unsafe profiles (R3a) are refused on save and
# audited (R5a) by the same cost_safety predicate the engine uses.

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .cost_safety import unsafe_reason


class ProfileError(Exception):
    """Raised when a profile is unsafe to persist or cannot be loaded."""


@dataclass(frozen=True)
class Profile:
    """A model profile: the per-tier OpenRouter routing plus a cheap catch-all.

    Fields:
        name:       Profile label (v1 uses a single 'default').
        main:       OpenRouter id for the main tier (ANTHROPIC_MODEL).
        small_fast: OpenRouter id for the small/fast tier (ANTHROPIC_SMALL_FAST_MODEL).
        catch_all:  Concrete cheap OpenRouter id for every unanticipated string.
        port:       Loopback port the proxy binds.
    """

    name: str
    main: str
    small_fast: str
    catch_all: str
    port: int = 4000


def default_profile(
    main: str,
    small_fast: str,
    *,
    catch_all: str | None = None,
    port: int = 4000,
    name: str = "default",
) -> Profile:
    """Build a profile, defaulting the catch-all to the (cheapest) small/fast tier.

    Args:
        main:       OpenRouter id for the main tier.
        small_fast: OpenRouter id for the small/fast tier.
        catch_all:  Override for the catch-all; defaults to small_fast.
        port/name:  Proxy port and profile label.
    """
    return Profile(
        name=name,
        main=main,
        small_fast=small_fast,
        catch_all=catch_all if catch_all is not None else small_fast,
        port=port,
    )


def tier_map(profile: Profile) -> dict[str, str]:
    """Return the explicit Claude-tier -> OpenRouter-id map for the engine config.

    Keys are the exact strings `sb code` makes Claude Code emit (the two tier ids);
    the engine appends the concrete catch-all. Never a passthrough wildcard (R3a).
    """
    return {profile.main: profile.main, profile.small_fast: profile.small_fast}


def model_env(profile: Profile) -> dict[str, str]:
    """Return the ANTHROPIC_* model env vars that steer Claude Code's per-tier strings."""
    return {
        "ANTHROPIC_MODEL": profile.main,
        "ANTHROPIC_SMALL_FAST_MODEL": profile.small_fast,
    }


def unsafe_tiers(profile: Profile) -> list[tuple[str, str]]:
    """Return (tier-label, reason) for every cost-unsafe routing target (R5a).

    Shares the cost_safety predicate with the config generator, so doctor's audit
    and the write-time guard can never disagree.
    """
    targets = {"main": profile.main, "small_fast": profile.small_fast, "catch_all": profile.catch_all}
    return [(label, reason) for label, value in targets.items() if (reason := unsafe_reason(value))]


def save(profile: Profile, path: Path) -> None:
    """Persist *profile* as JSON, refusing to write an unsafe one (R3a defense in depth).

    Raises:
        ProfileError: when any tier resolves to a cost-unsafe target.
    """
    unsafe = unsafe_tiers(profile)
    if unsafe:
        detail = "; ".join(f"{label}: {reason}" for label, reason in unsafe)
        raise ProfileError(f"refusing to save cost-unsafe profile ({detail})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")


def load(path: Path) -> Profile | None:
    """Load a profile from JSON, or None when the file does not exist.

    Raises:
        ProfileError: when the file exists but is corrupt or missing fields.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Profile(
            name=data["name"],
            main=data["main"],
            small_fast=data["small_fast"],
            catch_all=data["catch_all"],
            port=data.get("port", 4000),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProfileError(f"invalid profile at {path}: {exc}") from exc
