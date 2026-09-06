"""Safety boundaries that are orthogonal to tier selection.

The prod guard is checked for every mutating execution, in EVERY tier, before any
call reaches SAP. Tier choice never relaxes it.
"""

from __future__ import annotations

from typing import Any

from .models import ErrorCode, Result, System, Tier


def check_prod_write(system: System, *, mutating: bool, allow_prod: bool) -> Result | None:
    """Return a PROD_BLOCKED failure if a write to prod is not explicitly authorized.

    Returns None when the operation is permitted to proceed.
    """
    if mutating and system.is_prod and not allow_prod:
        return Result.failure(
            ErrorCode.PROD_BLOCKED,
            f"refusing to mutate production system {system.creds_id!r} "
            "without explicit authorization (constraints.allow_prod)",
            tier=None,
        )
    return None


def blocks_tier0(constraints: dict[str, Any] | None) -> bool:
    """Tier 0 opens its own headless connection, not the user's live GUI session.

    A task that must run in the live session (context/authorization reasons) sets
    `must_stay_in_live_session` and Tier 0 is skipped.
    """
    return bool(constraints and constraints.get("must_stay_in_live_session"))


__all__ = ["Tier", "blocks_tier0", "check_prod_write"]
