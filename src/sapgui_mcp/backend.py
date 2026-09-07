"""The one abstraction the router knows. Each tier implements it."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import Confidence, ProbeHit, Result, System, Task, Tier


@runtime_checkable
class Backend(Protocol):
    """A tier. Keep `can_handle` cheap (catalog-driven) — it must never cost vision."""

    tier: Tier

    def can_handle(self, task: Task, system: System) -> Confidence:
        """Cheap yes/no. Reads the catalog; does NOT touch SAP."""
        ...

    def execute(
        self, task: Task, params: dict[str, Any], system: System, *, dry_run: bool = False
    ) -> Result:
        """Do the task. Must set `mutated` honestly and honor `dry_run` on write paths."""
        ...


@runtime_checkable
class Probing(Protocol):
    """Optional: a backend that can DISCOVER whether it handles an unknown task.

    Probing is the only step allowed to cost something on a cache miss — the result
    is written to the catalog so it is never paid twice. Must be read-only: a probe
    establishes capability, it never performs the task.
    """

    def probe(self, task: Task, system: System) -> ProbeHit | None:
        """Return how this tier could do the task, or None if it can't."""
        ...
