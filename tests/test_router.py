"""Router: cheapest-tier selection, fallback, prod guard, constraints, NO_TIER.

Uses fake backends so the cascade logic is tested deterministically, no SAP."""

from __future__ import annotations

from pathlib import Path

from sapgui_mcp.catalog import Catalog, TaskEntry, Tier0, Tier2, load_catalog
from sapgui_mcp.models import Confidence, ErrorCode, Result, System, Task, Tier
from sapgui_mcp.router import Router

SAMPLE = Path(__file__).resolve().parents[1] / "catalog" / "catalog.json"


class FakeBackend:
    def __init__(self, tier: Tier, *, can: bool = True, ok: bool = True,
                 error: ErrorCode | None = None) -> None:
        self.tier = tier
        self._can = can
        self._ok = ok
        self._error = error
        self.executed = False

    def can_handle(self, task: Task, system: System) -> Confidence:
        return Confidence(self._can)

    def execute(self, task: Task, params: dict, system: System, *, dry_run: bool = False) -> Result:
        self.executed = True
        if self._ok:
            return Result(ok=True, tier=self.tier, reason=f"handled by {self.tier}", mutated=False)
        return Result.failure(self._error or ErrorCode.BACKEND, f"{self.tier} failed", self.tier)


def _router(*backends: FakeBackend) -> Router:
    r = Router(load_catalog(SAMPLE))
    for b in backends:
        r.register(b)
    return r


def _sys(env: str = "sbx") -> System:
    return System(creds_id="SBX", env=env)


# -- positive -----------------------------------------------------------------

def test_picks_cheapest_available_tier() -> None:
    t0, t2 = FakeBackend(Tier.API), FakeBackend(Tier.WEBGUI)
    res = _router(t0, t2).execute(Task("create_sales_order"), {}, _sys())
    assert res.ok and res.tier == Tier.API
    assert t0.executed and not t2.executed


def test_registered_tiers_listed() -> None:
    r = _router(FakeBackend(Tier.API), FakeBackend(Tier.WEBGUI))
    assert r.registered_tiers() == [Tier.API, Tier.WEBGUI]


def test_must_stay_in_live_session_skips_tier0() -> None:
    t0, t2 = FakeBackend(Tier.API), FakeBackend(Tier.WEBGUI)
    res = _router(t0, t2).execute(
        Task("create_sales_order"), {}, _sys(),
        constraints={"must_stay_in_live_session": True},
    )
    assert res.ok and res.tier == Tier.WEBGUI
    assert not t0.executed and t2.executed


# -- negative -----------------------------------------------------------------

def test_falls_through_on_runtime_failure() -> None:
    t0 = FakeBackend(Tier.API, ok=False, error=ErrorCode.UI_BUG)
    t2 = FakeBackend(Tier.WEBGUI, ok=True)
    res = _router(t0, t2).execute(Task("create_sales_order"), {}, _sys())
    assert res.ok and res.tier == Tier.WEBGUI
    assert res.fallbacks and res.fallbacks[0].code == ErrorCode.UI_BUG


def test_all_tiers_fail_returns_no_tier_no_loop() -> None:
    # create_sales_order's preferred_order has 4 tiers; only two are registered and
    # both fail. Invariant: every tier in the order is tried at most once (no loop).
    t0 = FakeBackend(Tier.API, ok=False, error=ErrorCode.DROPPED)
    t2 = FakeBackend(Tier.WEBGUI, ok=False, error=ErrorCode.UI_BUG)
    res = _router(t0, t2).execute(Task("create_sales_order"), {}, _sys())
    assert not res.ok and res.error and res.error.code == ErrorCode.NO_TIER
    tried = [f.tier for f in res.fallbacks]
    assert len(tried) == 4 and len(set(tried)) == 4  # each preferred tier tried once
    assert res.fallbacks[0].code == ErrorCode.DROPPED  # the one registered+failing tier


def test_unknown_task_returns_no_tier() -> None:
    res = _router(FakeBackend(Tier.API)).execute(Task("nonexistent"), {}, _sys())
    assert not res.ok and res.error and res.error.code == ErrorCode.NO_TIER


def test_prod_write_blocked_before_any_backend() -> None:
    t0 = FakeBackend(Tier.API)
    res = _router(t0).execute(
        Task("create_sales_order"), {}, _sys(env="prd"), mutating=True,
    )
    assert not res.ok and res.error and res.error.code == ErrorCode.PROD_BLOCKED
    assert not t0.executed  # refused before touching SAP


def test_prod_write_allowed_with_explicit_flag() -> None:
    t0 = FakeBackend(Tier.API)
    res = _router(t0).execute(
        Task("create_sales_order"), {}, _sys(env="prd"),
        mutating=True, constraints={"allow_prod": True},
    )
    assert res.ok and t0.executed


def test_prod_read_not_blocked() -> None:
    t0 = FakeBackend(Tier.API)
    res = _router(t0).execute(Task("create_sales_order"), {}, _sys(env="prd"), mutating=False)
    assert res.ok  # reads against prod are fine


def test_default_order_used_when_no_preferred_order() -> None:
    # A catalog task without preferred_order -> cheapest available tier first.
    cat = Catalog(version=1, tasks={
        "x": TaskEntry(tier0=Tier0(rfc={"bapi": "B"}), tier2=Tier2(webgui_ok=True)),
    })
    r = Router(cat)
    r.register(FakeBackend(Tier.WEBGUI))
    r.register(FakeBackend(Tier.API))
    res = r.execute(Task("x"), {}, _sys())
    assert res.ok and res.tier == Tier.API  # tier0 cheaper than tier2, no explicit order


def test_tier_declined_is_skipped() -> None:
    t0 = FakeBackend(Tier.API, can=False)
    t2 = FakeBackend(Tier.WEBGUI, can=True)
    res = _router(t0, t2).execute(Task("create_sales_order"), {}, _sys())
    assert res.ok and res.tier == Tier.WEBGUI and not t0.executed
