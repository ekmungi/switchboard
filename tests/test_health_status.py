# test_health_status.py - Tests for health.apikey_blank, websearch_online, and status_lines.
#
# All functions accept plain dicts and Model instances; no network or file I/O.
# ---------------------------------------------------------------------------

from switchboard.catalog import Model
from switchboard.health import (
    apikey_blank,
    websearch_online,
    status_lines,
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

_CATALOG_GOOD = [_MODEL_LARGE]
_CATALOG_WITH_SMALL = [_MODEL_LARGE, _MODEL_SMALL]

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

    assert lines[1] == "CCR running     : no"
    assert lines[2] == "APIKEY blank    : NO"

    assert "WARNINGS:" in lines
    warnings_idx = lines.index("WARNINGS:")
    assert warnings_idx >= 4

    assert any(ln.startswith("  ") for ln in lines[warnings_idx + 1:])
