# claude_scopes.py - Readers + audit helpers for Claude Code's config surfaces.
#
# Pure I/O-light layer for `sb sync` (SPEC-003): tolerant JSON loading of the
# two user-scope state files (plain vs CCR CLAUDE_CONFIG_DIR), plus small pure
# helpers that turn already-loaded dicts into audit strings. No printing here.
# ---------------------------------------------------------------------------

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (module-level so tests can monkeypatch, same pattern as ccr_config)
# ---------------------------------------------------------------------------

SOURCE_STATE: Path = Path.home() / ".claude.json"
"""User-scope state file of plain `claude` sessions (holds the real mcpServers)."""

TARGET_CONFIG_DIR: Path = Path.home() / ".claude"
"""The CLAUDE_CONFIG_DIR CCR uses when launching claude sessions."""

TARGET_STATE: Path = TARGET_CONFIG_DIR / ".claude.json"
"""User-scope state file CCR-launched sessions actually read (the sync target)."""

SETTINGS_PATH: Path = TARGET_CONFIG_DIR / "settings.json"
"""Global settings.json shared by both launch modes."""

LEGACY_CCR_CONFIG: Path = Path.home() / ".claude-code-router" / "config.json"
"""CCR v1/v2 config file - inert on v3 installs (SQLite is the real store)."""

MANIFEST_PATH: Path = TARGET_CONFIG_DIR / ".switchboard-sync-manifest.json"
"""Switchboard's record of servers it added to the target scope (prune guard)."""

# Env vars CCR injects into settings.json when it applies a profile (ISS-003).
_CCR_ENV_MARKERS: tuple[str, ...] = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_BASE_URL",
    "CLAUDE_AGENT_API_BASE_URL",
)


# ---------------------------------------------------------------------------
# Tolerant JSON loading
# ---------------------------------------------------------------------------


def load_json(path: Path) -> tuple[dict, str | None]:
    """Load a JSON file, never raising.

    Args:
        path: File to read.

    Returns:
        (data, error): data is the parsed dict ({} when missing or broken);
        error is None normally, or a one-line description naming the file when
        the content is malformed. A missing file is NOT an error (fresh setups).
    """
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {}, f"{path.name}: unreadable ({exc})"
    if not isinstance(data, dict):
        return {}, f"{path.name}: expected a JSON object"
    return data, None


def mcp_servers(state: dict) -> dict:
    """Return the mcpServers map from a state dict, {} when absent/malformed.

    Args:
        state: A parsed .claude.json state dict.

    Returns:
        The name -> server-definition mapping (possibly empty).
    """
    servers = state.get("mcpServers")
    return servers if isinstance(servers, dict) else {}


# ---------------------------------------------------------------------------
# Audit helpers (pure: dicts in, message strings out)
# ---------------------------------------------------------------------------


def settings_warns(settings: dict) -> list[str]:
    """WARN lines for a CCR-managed settings.json (ISS-003). Empty when clean.

    Args:
        settings: Parsed ~/.claude/settings.json.

    Returns:
        Zero, one, or two warning strings (env block / apiKeyHelper).
    """
    warns: list[str] = []
    env = settings.get("env", {}) if isinstance(settings.get("env"), dict) else {}
    hit = [k for k in _CCR_ENV_MARKERS if k in env]
    if hit:
        warns.append(
            f"settings.json env is CCR-managed ({', '.join(hit)}) - "
            "shared with plain sessions (ISS-003); not touched by sync"
        )
    if settings.get("apiKeyHelper"):
        warns.append(
            "settings.json apiKeyHelper points at a CCR-generated script (ISS-003); "
            "not touched by sync"
        )
    return warns


def legacy_ccr_warn(legacy: dict) -> str | None:
    """WARN line for the inert legacy CCR config.json (ISS-002). None when absent.

    Args:
        legacy: Parsed ~/.claude-code-router/config.json ({} when the file is gone).

    Returns:
        A warning naming the file as inert - plus a rotate/delete advisory when a
        provider api_key is present. The key VALUE is never included.
    """
    if not legacy:
        return None
    providers = legacy.get("Providers", [])
    has_key = isinstance(providers, list) and any(
        isinstance(p, dict) and p.get("api_key") for p in providers
    )
    msg = "legacy ~/.claude-code-router/config.json is inert on CCR v3 (SQLite is the real store)"
    if has_key:
        msg += " and holds a plaintext provider api key - rotate the key and delete the file"
    return msg


def connectors_info(target_state: dict) -> str | None:
    """INFO line when the CCR scope has no claude.ai account link. None when linked.

    Args:
        target_state: Parsed target-scope .claude.json.

    Returns:
        An advisory that connectors are not portable, or None when oauthAccount exists.
    """
    if target_state.get("oauthAccount"):
        return None
    return (
        "claude.ai account/connectors: not portable to the CCR scope "
        "(no account link there; auth state is never copied)"
    )


def plugins_info(settings: dict) -> str:
    """INFO line: plugins pass through CCR natively; report the enabled count.

    Args:
        settings: Parsed ~/.claude/settings.json.

    Returns:
        A one-line summary with the number of enabled plugins.
    """
    plugins = settings.get("enabledPlugins")
    count = len(plugins) if isinstance(plugins, dict) else 0
    return f"plugins: {count} enabled - shared via ~/.claude, pass through natively"
