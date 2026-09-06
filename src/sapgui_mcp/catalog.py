"""Capability catalog: the router's free memory of how each task can be done.

Schema mirrors docs/01-architecture.md §5. Validation is pydantic — a malformed
catalog raises on load rather than misrouting at runtime. No secrets live here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .models import Tier


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tier0(_Strict):
    rfc: dict[str, Any] | None = None  # {bapi, commit, params, verified}
    odata: dict[str, Any] | None = None
    sapcli: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return any((self.rfc, self.odata, self.sapcli))


class Tier1(_Strict):
    script: str | None = None
    platform: str | None = None  # "java" | "windows"
    params: list[str] = []
    verified: str | None = None


class Tier2(_Strict):
    webgui_ok: bool = False
    entry: str | None = None
    buggy: list[str] = []


class Tier3(_Strict):
    supported: bool = False
    notes: str = ""


# Only these strings may appear in preferred_order.
_ORDER_TOKENS = {"tier0.rfc", "tier0.odata", "tier0.sapcli", "tier1", "tier2", "tier3"}


class TaskEntry(_Strict):
    aliases: list[str] = []
    tier0: Tier0 = Tier0()
    tier1: Tier1 = Tier1()
    tier2: Tier2 = Tier2()
    tier3: Tier3 = Tier3()
    preferred_order: list[str] = []
    system_overrides: dict[str, dict[str, Any]] = {}

    def merged_for(self, creds_id: str) -> TaskEntry:
        """Apply system_overrides for one system, returning a new entry (immutable style)."""
        override = self.system_overrides.get(creds_id)
        if not override:
            return self
        base = self.model_dump()
        base.pop("system_overrides", None)
        for tier_key, patch in override.items():
            if tier_key in base and isinstance(patch, dict):
                base[tier_key] = {**base[tier_key], **patch}
        return TaskEntry(**base, system_overrides={})


class Catalog(_Strict):
    version: int
    tasks: dict[str, TaskEntry] = {}

    def lookup(self, task_name: str, creds_id: str) -> TaskEntry | None:
        entry = self.tasks.get(task_name)
        if entry is None:
            # alias fallback
            for e in self.tasks.values():
                if task_name in e.aliases:
                    entry = e
                    break
        return entry.merged_for(creds_id) if entry else None


def load_catalog(path: str | Path) -> Catalog:
    """Parse + validate. Raises pydantic.ValidationError / json errors on malformed input."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cat = Catalog(**raw)
    _validate_order_tokens(cat)
    return cat


def _validate_order_tokens(cat: Catalog) -> None:
    for name, entry in cat.tasks.items():
        bad = set(entry.preferred_order) - _ORDER_TOKENS
        if bad:
            raise ValueError(f"task {name!r}: unknown preferred_order tokens {sorted(bad)}")


# Map a preferred_order token to the Tier it selects.
def tier_of_token(token: str) -> Tier:
    return {
        "tier0.rfc": Tier.API,
        "tier0.odata": Tier.API,
        "tier0.sapcli": Tier.API,
        "tier1": Tier.SCRIPT,
        "tier2": Tier.WEBGUI,
        "tier3": Tier.COMPUTER_USE,
    }[token]
