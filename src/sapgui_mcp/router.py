"""The brain: pick the cheapest tier that can do the task, fall down on failure,
and LEARN so an unknown task is only ever discovered once.

Cost rules this file enforces:
  - Tier selection is a free catalog lookup. Never a discovery loop.
  - A cache miss probes once (cheapest tier first) and writes the answer back.
  - A tier is never retried blindly; a stale entry is re-probed exactly once.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backend import Backend, Probing
from .catalog import Catalog, TaskEntry, save_catalog, tier_of_token
from .guards import blocks_tier0, check_prod_write
from .models import ErrorCode, ErrorInfo, Result, System, Task, Tier

log = logging.getLogger(__name__)

# A tier spec older than this is re-probed before it is trusted again.
STALE_AFTER_DAYS = 90


class Router:
    def __init__(self, catalog: Catalog, catalog_path: str | Path | None = None) -> None:
        self._catalog = catalog
        self._catalog_path = Path(catalog_path) if catalog_path else None
        self._backends: dict[Tier, Backend] = {}

    def register(self, backend: Backend) -> None:
        self._backends[backend.tier] = backend

    def registered_tiers(self) -> list[Tier]:
        return sorted(self._backends)

    def execute(
        self,
        task: Task,
        params: dict[str, Any],
        system: System,
        *,
        constraints: dict[str, Any] | None = None,
        mutating: bool = False,
        dry_run: bool = False,
    ) -> Result:
        # Prod guard first — never routed around.
        if blocked := check_prod_write(system, mutating=mutating, allow_prod=_allow_prod(constraints)):
            return blocked

        entry = self._catalog.lookup(task.name, system.creds_id)
        order = self._tier_order(entry, constraints)
        fallbacks: list[ErrorInfo] = []

        if not order:
            # Cache miss: discover once, remember forever.
            return self._probe_and_route(
                task, params, system, constraints, dry_run=dry_run, fallbacks=fallbacks
            )

        reprobed: set[Tier] = set()
        for tier in order:
            backend = self._backends.get(tier)
            if backend is None:
                fallbacks.append(ErrorInfo(ErrorCode.NOT_FOUND, f"tier {tier} not registered", tier))
                continue
            if not backend.can_handle(task, system).can:
                fallbacks.append(ErrorInfo(ErrorCode.NOT_FOUND, f"tier {tier} declined", tier))
                continue

            # An aged spec is refreshed before we trust it (at most once per call).
            if tier not in reprobed and _is_aged(entry, tier):
                reprobed.add(tier)
                self._reprobe(task, system, backend)

            result = backend.execute(task, params, system, dry_run=dry_run)

            if not result.ok and _is_stale(result) and tier not in reprobed:
                # Exactly one re-probe, then one retry of this same tier.
                reprobed.add(tier)
                if self._reprobe(task, system, backend):
                    result = backend.execute(task, params, system, dry_run=dry_run)

            if result.ok:
                self._record_success(task, system, tier)
                result.fallbacks = fallbacks
                return result

            if result.error:
                fallbacks.append(result.error)
                self._record_failure(task, system, result.error)

        final = Result.failure(ErrorCode.NO_TIER, f"all tiers failed for task {task.name!r}")
        final.fallbacks = fallbacks
        return final

    # -- probing ----------------------------------------------------------------

    def _probe_and_route(
        self,
        task: Task,
        params: dict[str, Any],
        system: System,
        constraints: dict[str, Any] | None,
        *,
        dry_run: bool,
        fallbacks: list[ErrorInfo],
    ) -> Result:
        """Unknown task: ask each tier (cheapest first) whether it can do this."""
        skip_tier0 = blocks_tier0(constraints)
        for tier in sorted(self._backends):
            if skip_tier0 and tier == Tier.API:
                continue
            backend = self._backends[tier]
            if not isinstance(backend, Probing):
                continue
            hit = backend.probe(task, system)
            if hit is None:
                fallbacks.append(ErrorInfo(ErrorCode.NOT_FOUND, f"tier {tier} probe: no", tier))
                continue

            self._catalog.set_spec(task.name, hit.token, hit.spec)  # learn
            self._persist()
            result = backend.execute(task, params, system, dry_run=dry_run)
            if result.ok:
                self._record_success(task, system, tier)
            elif result.error:
                fallbacks.append(result.error)
            result.fallbacks = fallbacks
            return result

        final = Result.failure(
            ErrorCode.NO_TIER,
            f"no tier can handle task {task.name!r} on {system.creds_id!r} (probe found nothing)",
        )
        final.fallbacks = fallbacks
        return final

    def _reprobe(self, task: Task, system: System, backend: Backend) -> bool:
        """Refresh one stale spec. Returns True if the catalog was updated."""
        if not isinstance(backend, Probing):
            return False
        hit = backend.probe(task, system)
        if hit is None:
            return False
        self._catalog.set_spec(task.name, hit.token, hit.spec)
        self._persist()
        return True

    # -- learning ---------------------------------------------------------------

    def _record_success(self, task: Task, system: System, tier: Tier) -> None:
        entry = self._catalog.lookup(task.name, system.creds_id)
        token = _token_for(entry, tier)
        if token:
            self._catalog.mark_verified(task.name, token, _today())
            self._persist()

    def _record_failure(self, task: Task, system: System, error: ErrorInfo) -> None:
        # A broken WebGUI control is remembered per-system so we skip straight past it.
        if error.code is ErrorCode.UI_BUG:
            self._catalog.mark_buggy(task.name, system.creds_id, error.message[:120])
            self._persist()

    def _persist(self) -> None:
        if self._catalog_path is None:
            return  # in-memory only (tests, or a read-only catalog)
        try:
            save_catalog(self._catalog, self._catalog_path)
        except OSError:
            log.warning("could not persist catalog to %s", self._catalog_path, exc_info=True)

    # -- ordering ---------------------------------------------------------------

    def _tier_order(self, entry: TaskEntry | None, constraints: dict[str, Any] | None) -> list[Tier]:
        """Deterministic cheapest-first order, de-duped, filtered by constraints."""
        if entry and entry.preferred_order:
            tiers = [tier_of_token(t) for t in entry.preferred_order]
        elif entry:
            tiers = _default_order_from_entry(entry)
        else:
            tiers = []  # unknown task -> probe

        if blocks_tier0(constraints):
            tiers = [t for t in tiers if t != Tier.API]

        seen: set[Tier] = set()
        ordered: list[Tier] = []
        for t in tiers:
            if t not in seen:
                seen.add(t)
                ordered.append(t)
        return ordered


def _allow_prod(constraints: dict[str, Any] | None) -> bool:
    return bool(constraints and constraints.get("allow_prod"))


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _is_stale(result: Result) -> bool:
    return result.error is not None and result.error.code is ErrorCode.STALE_CATALOG


def _is_aged(entry: TaskEntry | None, tier: Tier) -> bool:
    """True if this tier's spec was last verified longer ago than STALE_AFTER_DAYS.

    A spec that has never been verified is NOT aged — it has simply never run, and
    the execute attempt itself is the cheapest way to find out whether it works.
    """
    token = _token_for(entry, tier)
    if entry is None or token is None:
        return False
    verified = _verified_date(entry, token)
    if not verified:
        return False
    try:
        seen = datetime.fromisoformat(verified).date()
    except ValueError:
        return True  # unparseable stamp -> treat as stale rather than trust it
    return (datetime.now(UTC).date() - seen).days > STALE_AFTER_DAYS


def _verified_date(entry: TaskEntry, token: str) -> str | None:
    if token.startswith("tier0."):
        spec = getattr(entry.tier0, token.split(".", 1)[1])
        return spec.get("verified") if isinstance(spec, dict) else None
    if token == "tier1":
        return entry.tier1.verified
    return None


def _token_for(entry: TaskEntry | None, tier: Tier) -> str | None:
    """Which catalog token did this tier run under? Prefer the declared order."""
    if entry is None:
        return None
    for token in entry.preferred_order:
        if tier_of_token(token) == tier:
            return token
    return {Tier.SCRIPT: "tier1", Tier.WEBGUI: "tier2", Tier.COMPUTER_USE: "tier3"}.get(tier)


def _default_order_from_entry(entry: TaskEntry) -> list[Tier]:
    """When no explicit preferred_order: cheapest available tier first."""
    order: list[Tier] = []
    if entry.tier0.available:
        order.append(Tier.API)
    if entry.tier1.script:
        order.append(Tier.SCRIPT)
    if entry.tier2.webgui_ok:
        order.append(Tier.WEBGUI)
    if entry.tier3.supported:
        order.append(Tier.COMPUTER_USE)
    return order
