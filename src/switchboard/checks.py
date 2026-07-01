# checks.py - Pure doctor logic for `sb doctor`: builds and formats pass/fail checks.
#
# No printing, no I/O, no side effects.  All inputs are plain values so every
# function can be unit-tested without network or filesystem access.

from dataclasses import dataclass

from .catalog import Model
from .ccr_config import ROLES
from .health import apikey_blank, websearch_online, model_problem, role_model
from .mcp_sync import SyncPlan

__all__ = ["Check", "run_checks", "format_checks", "mcp_parity_check"]


@dataclass(frozen=True)
class Check:
    """A single pass/fail health-check result.

    Fields:
        name:   Short human-readable check label (e.g. 'CCR running').
        ok:     True when the check passes, False when it fails.
        detail: One-line detail string (reason on failure, status on pass).
    """

    name: str
    ok: bool
    detail: str


def run_checks(cfg: dict, catalog: list[Model], ccr_up: bool) -> list[Check]:
    """Run all doctor health checks and return results in canonical order.

    Checks produced (in order):
    1. CCR running     -- pass when ccr_up is True.
    2. OpenRouter catalog -- pass when catalog is non-empty.
    3. APIKEY blank    -- pass when cfg APIKEY is ''.
    4. role <name>     -- one check per ROLE present in cfg['Router']:
                          passes when model_problem returns None.
    5. web search      -- always ok=True (informational); detail is 'on'/'off'.

    Args:
        cfg:     The full CCR config dict.
        catalog: Live catalog list (empty when offline).
        ccr_up:  True iff the CCR process is currently running.

    Returns:
        Ordered list of Check instances covering every health dimension.
    """
    checks: list[Check] = []

    # 1. CCR running
    checks.append(Check(
        name="CCR running",
        ok=ccr_up,
        detail="reachable" if ccr_up else "not reachable",
    ))

    # 2. OpenRouter catalog
    cat_ok = bool(catalog)
    checks.append(Check(
        name="OpenRouter catalog",
        ok=cat_ok,
        detail=f"{len(catalog)} models" if cat_ok else "unavailable",
    ))

    # 3. APIKEY blank
    ak_ok = apikey_blank(cfg)
    checks.append(Check(
        name="APIKEY blank",
        ok=ak_ok,
        detail="blank" if ak_ok else "NOT blank (auth-wall risk)",
    ))

    # 4. Per-role checks
    router: dict = cfg.get("Router", {})
    for role in ROLES:
        if role not in router:
            continue
        model = role_model(router[role])
        p = model_problem(model, catalog)
        role_ok = p is None
        checks.append(Check(
            name=f"role {role}",
            ok=role_ok,
            detail=model if role_ok else p,  # type: ignore[arg-type]
        ))

    # 5. Web search -- informational, always ok=True
    checks.append(Check(
        name="web search",
        ok=True,
        detail="on" if websearch_online(cfg) else "off",
    ))

    return checks


def mcp_parity_check(plan: SyncPlan) -> Check:
    """Doctor check: is the CCR scope's MCP set mirrored from the user scope?

    Args:
        plan: A SyncPlan from mcp_sync.build_plan over the live state files.

    Returns:
        Passing Check with the mirrored count, or failing Check naming the
        drifted count and pointing at `sb sync`.
    """
    drift = len(plan.adds) + len(plan.updates) + len(plan.orphans_managed)
    if drift == 0:
        return Check(
            name="MCP parity (CCR scope)",
            ok=True,
            detail=f"{len(plan.in_sync)} server(s) mirrored",
        )
    return Check(
        name="MCP parity (CCR scope)",
        ok=False,
        detail=f"{drift} server(s) drifted - run `sb sync` to inspect",
    )


def format_checks(checks: list[Check]) -> list[str]:
    """Return one printable line per check in [PASS]/[FAIL] format.

    Args:
        checks: List of Check instances from run_checks.

    Returns:
        A list of strings such as '[PASS] CCR running: reachable'.
    """
    return [
        f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}"
        for c in checks
    ]
