"""The one abstraction the router knows. Each tier implements it."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import Confidence, Result, System, Task, Tier


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
