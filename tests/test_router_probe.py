"""M3: probe-on-cache-miss, learning, persistence, staleness, buggy-marking."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sapgui_mcp import router as router_mod
from sapgui_mcp.catalog import Catalog, TaskEntry, Tier0, load_catalog, save_catalog
from sapgui_mcp.models import Confidence, ErrorCode, ProbeHit, Result, System, Task, Tier
from sapgui_mcp.router import Router

_SYS = System(creds_id="SBX", env="sbx")


class ProbingBackend:
    """A tier that can discover capability. Counts probes so we can assert 'exactly once'."""

    def __init__(self, tier: Tier, hit: ProbeHit | None, *, ok: bool = True,
                 error: ErrorCode | None = None) -> None:
        self.tier = tier
        self._hit = hit
        self._ok = ok
        self._error = error
        self.probes = 0
        self.executions = 0

    def probe(self, task: Task, system: System) -> ProbeHit | None:
        self.probes += 1
        return self._hit

    def can_handle(self, task: Task, system: System) -> Confidence:
        return Confidence(True)

    def execute(self, task: Task, params: dict[str, Any], system: System,
                *, dry_run: bool = False) -> Result:
        self.executions += 1
        if self._ok:
            return Result(ok=True, tier=self.tier, reason="done")
        return Result.failure(self._error or ErrorCode.BACKEND, "failed", self.tier)


class NonProbingBackend:
    """A tier with no discovery ability — the router must skip it while probing."""

    def __init__(self, tier: Tier) -> None:
        self.tier = tier
        self.executions = 0

    def can_handle(self, task: Task, system: System) -> Confidence:
        return Confidence(True)

    def execute(self, task: Task, params: dict[str, Any], system: System,
                *, dry_run: bool = False) -> Result:
        self.executions += 1
        return Result(ok=True, tier=self.tier, reason="done")


def _empty() -> Catalog:
    return Catalog(version=1, tasks={})


# -- positive: probe, learn, persist ------------------------------------------

def test_unknown_task_is_probed_and_executed() -> None:
    b = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "RFC_SYSTEM_INFO"}))
    r = Router(_empty())
    r.register(b)
    res = r.execute(Task("mystery"), {}, _SYS)
    assert res.ok and res.tier == Tier.API
    assert b.probes == 1 and b.executions == 1


def test_probe_result_is_written_to_catalog() -> None:
    cat = _empty()
    r = Router(cat)
    r.register(ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "RFC_SYSTEM_INFO"})))
    r.execute(Task("mystery"), {}, _SYS)
    entry = cat.lookup("mystery", "SBX")
    assert entry is not None
    assert entry.tier0.rfc["fm"] == "RFC_SYSTEM_INFO"
    assert "tier0.rfc" in entry.preferred_order


def test_learned_task_is_not_probed_again() -> None:
    cat = _empty()
    b = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"}))
    r = Router(cat)
    r.register(b)
    r.execute(Task("mystery"), {}, _SYS)
    r.execute(Task("mystery"), {}, _SYS)  # second call must hit the catalog, not probe
    assert b.probes == 1 and b.executions == 2


def test_probe_prefers_cheapest_tier() -> None:
    cheap = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"}))
    dear = ProbingBackend(Tier.COMPUTER_USE, ProbeHit("tier3", {"supported": True}))
    r = Router(_empty())
    r.register(dear)
    r.register(cheap)
    res = r.execute(Task("mystery"), {}, _SYS)
    assert res.tier == Tier.API
    assert dear.probes == 0  # never even asked the expensive tier


def test_success_stamps_verified_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    save_catalog(_empty(), path)
    cat = load_catalog(path)
    r = Router(cat, catalog_path=path)
    r.register(ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"})))
    r.execute(Task("mystery"), {}, _SYS)

    on_disk = json.loads(path.read_text())
    spec = on_disk["tasks"]["mystery"]["tier0"]["rfc"]
    assert spec["fm"] == "F"
    assert spec["verified"] == datetime.now(UTC).date().isoformat()


def test_persisted_catalog_reloads(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    save_catalog(_empty(), path)
    r = Router(load_catalog(path), catalog_path=path)
    r.register(ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"})))
    r.execute(Task("mystery"), {}, _SYS)
    assert load_catalog(path).lookup("mystery", "SBX") is not None  # round-trips + validates


# -- positive: staleness -------------------------------------------------------

def test_aged_spec_triggers_one_reprobe() -> None:
    old = (datetime.now(UTC).date() - timedelta(days=router_mod.STALE_AFTER_DAYS + 1)).isoformat()
    cat = Catalog(version=1, tasks={"t": TaskEntry(
        tier0=Tier0(rfc={"fm": "F", "verified": old}), preferred_order=["tier0.rfc"])})
    b = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F2"}))
    r = Router(cat)
    r.register(b)
    res = r.execute(Task("t"), {}, _SYS)
    assert res.ok and b.probes == 1
    assert cat.lookup("t", "SBX").tier0.rfc["fm"] == "F2"  # refreshed


def test_fresh_spec_is_not_reprobed() -> None:
    today = datetime.now(UTC).date().isoformat()
    cat = Catalog(version=1, tasks={"t": TaskEntry(
        tier0=Tier0(rfc={"fm": "F", "verified": today}), preferred_order=["tier0.rfc"])})
    b = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F2"}))
    r = Router(cat)
    r.register(b)
    r.execute(Task("t"), {}, _SYS)
    assert b.probes == 0


def test_never_verified_spec_is_not_treated_as_aged() -> None:
    cat = Catalog(version=1, tasks={"t": TaskEntry(
        tier0=Tier0(rfc={"fm": "F"}), preferred_order=["tier0.rfc"])})
    b = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F2"}))
    r = Router(cat)
    r.register(b)
    r.execute(Task("t"), {}, _SYS)
    assert b.probes == 0  # just run it; that's cheaper than probing


def test_stale_catalog_error_reprobes_once_then_retries() -> None:
    """Backend fails STALE once, then succeeds after the re-probe."""

    class FlakyStale(ProbingBackend):
        def execute(self, task: Task, params: dict[str, Any], system: System,
                    *, dry_run: bool = False) -> Result:
            self.executions += 1
            if self.executions == 1:
                return Result.failure(ErrorCode.STALE_CATALOG, "moved", self.tier)
            return Result(ok=True, tier=self.tier, reason="ok after reprobe")

    cat = Catalog(version=1, tasks={"t": TaskEntry(
        tier0=Tier0(rfc={"fm": "F"}), preferred_order=["tier0.rfc"])})
    b = FlakyStale(Tier.API, ProbeHit("tier0.rfc", {"fm": "F2"}))
    r = Router(cat)
    r.register(b)
    res = r.execute(Task("t"), {}, _SYS)
    assert res.ok and b.probes == 1 and b.executions == 2


# -- negative ------------------------------------------------------------------

def test_probe_finding_nothing_returns_no_tier() -> None:
    b = ProbingBackend(Tier.API, None)
    r = Router(_empty())
    r.register(b)
    res = r.execute(Task("mystery"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.NO_TIER
    assert b.probes == 1 and b.executions == 0  # probed, never executed blindly


def test_non_probing_backend_is_skipped_during_probe() -> None:
    b = NonProbingBackend(Tier.WEBGUI)
    r = Router(_empty())
    r.register(b)
    res = r.execute(Task("mystery"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.NO_TIER
    assert b.executions == 0  # never guessed that it might work


def test_probe_skips_tier0_when_live_session_required() -> None:
    t0 = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"}))
    t2 = ProbingBackend(Tier.WEBGUI, ProbeHit("tier2", {"webgui_ok": True, "entry": "va01"}))
    r = Router(_empty())
    r.register(t0)
    r.register(t2)
    res = r.execute(Task("mystery"), {}, _SYS,
                    constraints={"must_stay_in_live_session": True})
    assert res.tier == Tier.WEBGUI and t0.probes == 0


def test_prod_write_blocked_before_probe() -> None:
    b = ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"}))
    r = Router(_empty())
    r.register(b)
    res = r.execute(Task("mystery"), {}, System(creds_id="PRD", env="prd"), mutating=True)
    assert not res.ok and res.error.code == ErrorCode.PROD_BLOCKED
    assert b.probes == 0  # guard runs before any discovery cost

def test_ui_bug_is_marked_per_system_not_globally() -> None:
    cat = Catalog(version=1, tasks={"t": TaskEntry(
        tier2={"webgui_ok": True}, tier3={"supported": True},  # type: ignore[arg-type]
        preferred_order=["tier2", "tier3"])})
    web = ProbingBackend(Tier.WEBGUI, None, ok=False, error=ErrorCode.UI_BUG)
    cu = ProbingBackend(Tier.COMPUTER_USE, None, ok=True)
    r = Router(cat)
    r.register(web)
    r.register(cu)
    res = r.execute(Task("t"), {}, _SYS)
    assert res.ok and res.tier == Tier.COMPUTER_USE  # fell past the broken WebGUI

    assert "SBX" in cat.tasks["t"].system_overrides       # remembered for THIS system
    assert cat.tasks["t"].tier2.buggy == []               # global entry untouched


def test_persist_failure_does_not_crash(tmp_path: Path) -> None:
    unwritable = tmp_path / "nonexistent-dir" / "catalog.json"
    r = Router(_empty(), catalog_path=unwritable)
    r.register(ProbingBackend(Tier.API, ProbeHit("tier0.rfc", {"fm": "F"})))
    res = r.execute(Task("mystery"), {}, _SYS)
    assert res.ok  # learning is best-effort; the task still completes
