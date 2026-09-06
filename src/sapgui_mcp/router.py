"""The brain: pick the cheapest tier that can do the task, fall down on failure.

M0 ships the skeleton: backend registry, catalog-driven cascade, prod guard, and
correct NO_TIER behavior. Probe + promotion (docs/02-roadmap.md M3/M5) land later
where marked TODO.
"""

from __future__ import annotations

from typing import Any

from .backend import Backend
from .catalog import Catalog, TaskEntry, tier_of_token
from .guards import blocks_tier0, check_prod_write
from .models import ErrorCode, ErrorInfo, Result, System, Task, Tier


class Router:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
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
        if (blocked := check_prod_write(system, mutating=mutating, allow_prod=_allow_prod(constraints))):
            return blocked

        entry = self._catalog.lookup(task.name, system.creds_id)
        order = self._tier_order(entry, constraints)

        if not order:
            # Unknown task, nothing registered to probe with (M0). M3 will probe here.
            return Result.failure(
                ErrorCode.NO_TIER,
                f"no tier can handle task {task.name!r} on {system.creds_id!r} "
                "(no catalog entry and no probe available)",
            )

        fallbacks: list[ErrorInfo] = []
        for tier in order:
            backend = self._backends.get(tier)
            if backend is None:
                fallbacks.append(ErrorInfo(ErrorCode.NOT_FOUND, f"tier {tier} not registered", tier))
                continue
            if not backend.can_handle(task, system).can:
                fallbacks.append(ErrorInfo(ErrorCode.NOT_FOUND, f"tier {tier} declined", tier))
                continue

            result = backend.execute(task, params, system, dry_run=dry_run)
            if result.ok:
                result.fallbacks = fallbacks
                return result

            # Runtime failure: record and fall to next tier (never retry same tier blindly).
            if result.error:
                fallbacks.append(result.error)
            # TODO(M3): mark catalog buggy/stale on UI_BUG/STALE_CATALOG before continuing.

        final = Result.failure(ErrorCode.NO_TIER, f"all tiers failed for task {task.name!r}")
        final.fallbacks = fallbacks
        return final

    # -- internal ---------------------------------------------------------------

    def _tier_order(self, entry: TaskEntry | None, constraints: dict[str, Any] | None) -> list[Tier]:
        """Deterministic cheapest-first order, de-duped, filtered by constraints."""
        if entry and entry.preferred_order:
            tiers = [tier_of_token(t) for t in entry.preferred_order]
        elif entry:
            tiers = _default_order_from_entry(entry)
        else:
            tiers = []  # unknown task -> probe territory (M3)

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
