"""Runtime contracts shared by the router and every backend.

These types are deliberately small and transport-agnostic. The router only ever
speaks in terms of what is here — never a concrete backend's internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class Tier(IntEnum):
    """Cost ladder. Lower = cheaper/more deterministic. See docs/01-architecture.md."""

    API = 0  # RFC/BAPI, OData, sapcli/ADT — headless, ~free
    SCRIPT = 1  # recorded script.js / VBScript — ~free after capture
    WEBGUI = 2  # Playwright on the HTML GUI DOM — low cost
    COMPUTER_USE = 3  # vision + mouse (SAP GUI for Java) — expensive, last resort


class ErrorCode(StrEnum):
    """Typed failures. The router branches on these; humans read `message`."""

    AUTH = "AUTH"  # bad/expired creds, missing authorization object
    NOT_FOUND = "NOT_FOUND"  # task/element/field/service absent
    LOCKED = "LOCKED"  # SAP enqueue lock held
    PROD_BLOCKED = "PROD_BLOCKED"  # write to env:prd without authorization
    UI_BUG = "UI_BUG"  # WebGUI screen broken/missing control -> fall to next tier
    DROPPED = "DROPPED"  # session/connection lost mid-run
    PARTIAL = "PARTIAL"  # multi-step write interrupted; state uncertain
    STALE_CATALOG = "STALE_CATALOG"  # cached tier no longer works; re-probe once
    PARAM_INVALID = "PARAM_INVALID"  # params don't match the task schema
    NO_TIER = "NO_TIER"  # no tier could handle the task
    BACKEND = "BACKEND"  # backend-internal/unexpected error


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: ErrorCode
    message: str
    tier: Tier | None = None  # which tier produced it, if any


@dataclass(frozen=True, slots=True)
class System:
    """A target SAP system, identified by its `creds` index id. No secrets here."""

    creds_id: str
    env: str = "unknown"  # dev | qas | prd | sbx | unknown (from the creds entry)

    @property
    def is_prod(self) -> bool:
        return self.env.lower() == "prd"


@dataclass(frozen=True, slots=True)
class Task:
    """A logical operation the user asked for (often maps to a tcode/business function)."""

    name: str  # catalog key, e.g. "create_sales_order"
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Confidence:
    """A backend's cheap self-assessment of whether it can handle a task."""

    can: bool
    reason: str = ""


@dataclass(slots=True)
class Result:
    ok: bool
    tier: Tier | None
    reason: str = ""  # why this tier ran / why it failed — always populated
    data: dict[str, Any] | None = None  # structured output; Tier 3 may be sparse
    error: ErrorInfo | None = None
    mutated: bool = False  # did this change SAP state?
    evidence: str | None = None  # log/screenshot ref (Tier 2/3 only)
    fallbacks: list[ErrorInfo] = field(default_factory=list)  # tiers tried and skipped

    @classmethod
    def failure(cls, code: ErrorCode, message: str, tier: Tier | None = None) -> Result:
        return cls(ok=False, tier=tier, reason=message, error=ErrorInfo(code, message, tier))
