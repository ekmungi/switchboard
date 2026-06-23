# test_checks_run.py - Tests for run_checks scenarios (all pass, individual failures, order).
#
# Pure logic tests -- all I/O is passed in as plain values.
# ---------------------------------------------------------------------------

from switchboard.catalog import Model
from switchboard.checks import Check, run_checks
from switchboard.ccr_config import ROLES

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

_ROUTER_ALL_GOOD = {
    "default": "openrouter,deepseek/deepseek-v4-flash",
    "background": "openrouter,deepseek/deepseek-v4-flash",
    "think": "openrouter,deepseek/deepseek-v4-flash",
    "longContext": "openrouter,deepseek/deepseek-v4-flash",
    "webSearch": "openrouter,deepseek/deepseek-v4-flash",
}

_CFG_GOOD = {"APIKEY": "", "Router": _ROUTER_ALL_GOOD}
_CATALOG_GOOD = [_MODEL_LARGE]


# ---------------------------------------------------------------------------
# run_checks: known-good config -- all checks PASS
# ---------------------------------------------------------------------------


def test_run_checks_all_pass_on_good_config():
    """All checks pass for a known-good config: APIKEY blank, large catalog model, ccr_up."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    failing = [c for c in checks if not c.ok]
    assert failing == [], f"Expected zero failures, got: {failing}"


def test_run_checks_ccr_check_passes_when_up():
    """CCR running check is PASS when ccr_up=True."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    ccr = next(c for c in checks if c.name == "CCR running")
    assert ccr.ok is True
    assert ccr.detail == "reachable"


def test_run_checks_catalog_check_passes_when_non_empty():
    """OpenRouter catalog check is PASS when catalog has models."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    cat = next(c for c in checks if c.name == "OpenRouter catalog")
    assert cat.ok is True
    assert str(len(_CATALOG_GOOD)) in cat.detail


def test_run_checks_apikey_check_passes_when_blank():
    """APIKEY blank check is PASS when APIKEY is ''."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    ak = next(c for c in checks if c.name == "APIKEY blank")
    assert ak.ok is True


def test_run_checks_role_checks_pass_on_good_model():
    """All role checks pass when every role points to a large healthy catalog model."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    role_checks = [c for c in checks if c.name.startswith("role ")]
    assert len(role_checks) == len(ROLES)
    failing = [c for c in role_checks if not c.ok]
    assert failing == [], f"Expected no failing role checks, got: {failing}"


def test_run_checks_web_search_always_ok():
    """web search check is always ok=True (informational only)."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    ws = next(c for c in checks if c.name == "web search")
    assert ws.ok is True


def test_run_checks_web_search_off_detail():
    """web search detail reports 'off' when not :online."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    ws = next(c for c in checks if c.name == "web search")
    assert ws.detail == "off"


def test_run_checks_web_search_on_detail():
    """web search detail reports 'on' when webSearch ends with :online."""
    router = {**_ROUTER_ALL_GOOD, "webSearch": "openrouter,deepseek/deepseek-v4-flash:online"}
    cfg = {"APIKEY": "", "Router": router}
    checks = run_checks(cfg, _CATALOG_GOOD, ccr_up=True)
    ws = next(c for c in checks if c.name == "web search")
    assert ws.ok is True
    assert ws.detail == "on"


# ---------------------------------------------------------------------------
# run_checks: individual failure cases
# ---------------------------------------------------------------------------


def test_run_checks_fails_when_apikey_non_blank():
    """APIKEY blank check FAILS when APIKEY is set to a non-empty value."""
    cfg = {"APIKEY": "sk-real-key", "Router": _ROUTER_ALL_GOOD}
    checks = run_checks(cfg, _CATALOG_GOOD, ccr_up=True)
    ak = next(c for c in checks if c.name == "APIKEY blank")
    assert ak.ok is False


def test_run_checks_fails_when_role_has_small_context_model():
    """Role check FAILS when a role's model is in catalog but context < MIN_CONTEXT."""
    catalog = [_MODEL_LARGE, _MODEL_SMALL]
    router = {**_ROUTER_ALL_GOOD, "background": f"openrouter,{_MODEL_SMALL.id}"}
    cfg = {"APIKEY": "", "Router": router}
    checks = run_checks(cfg, catalog, ccr_up=True)
    bg = next(c for c in checks if c.name == "role background")
    assert bg.ok is False
    assert "context" in bg.detail.lower()
    assert f"{_MODEL_SMALL.context_length:,}" in bg.detail


def test_run_checks_fails_when_role_has_anthropic_model():
    """Role check FAILS when a role's model starts with anthropic/."""
    router = {**_ROUTER_ALL_GOOD, "default": "openrouter,anthropic/claude-3-5-haiku"}
    cfg = {"APIKEY": "", "Router": router}
    checks = run_checks(cfg, _CATALOG_GOOD, ccr_up=True)
    dfl = next(c for c in checks if c.name == "role default")
    assert dfl.ok is False
    assert "Anthropic" in dfl.detail or "haiku" in dfl.detail.lower()


def test_run_checks_fails_when_role_contains_haiku():
    """Role check FAILS when a role's model id contains 'haiku'."""
    router = {**_ROUTER_ALL_GOOD, "think": "openrouter,somevendor/haiku-mini"}
    cfg = {"APIKEY": "", "Router": router}
    checks = run_checks(cfg, _CATALOG_GOOD, ccr_up=True)
    th = next(c for c in checks if c.name == "role think")
    assert th.ok is False


def test_run_checks_ccr_fails_when_ccr_down():
    """CCR running check FAILS when ccr_up=False."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=False)
    ccr = next(c for c in checks if c.name == "CCR running")
    assert ccr.ok is False
    assert ccr.detail == "not reachable"


def test_run_checks_catalog_fails_when_catalog_empty():
    """OpenRouter catalog check FAILS when catalog is empty."""
    checks = run_checks(_CFG_GOOD, [], ccr_up=True)
    cat = next(c for c in checks if c.name == "OpenRouter catalog")
    assert cat.ok is False
    assert "unavailable" in cat.detail


# ---------------------------------------------------------------------------
# run_checks: order guarantee
# ---------------------------------------------------------------------------


def test_run_checks_order():
    """run_checks returns checks in the required order: CCR, catalog, APIKEY, roles, web."""
    checks = run_checks(_CFG_GOOD, _CATALOG_GOOD, ccr_up=True)
    names = [c.name for c in checks]
    assert names[0] == "CCR running"
    assert names[1] == "OpenRouter catalog"
    assert names[2] == "APIKEY blank"
    assert all(names[3 + i].startswith("role ") for i in range(len(ROLES)))
    assert names[-1] == "web search"
