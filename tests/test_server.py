"""Smoke test the MCP tool wiring: it builds a router (with the Tier-0 RFC backend
registered) from the shipped catalog and returns typed result dicts."""

from __future__ import annotations

from sapgui_mcp.models import Tier
from sapgui_mcp.server import build_router, sap_execute


def test_build_router_registers_tier0() -> None:
    r = build_router()
    assert r.registered_tiers() == [Tier.API]  # RFC backend (pyrfc loaded lazily)


def test_sap_execute_unknown_task_returns_no_tier() -> None:
    out = sap_execute(task="does_not_exist", system="SBX", env="sbx")
    assert out["ok"] is False and out["error"]["code"] == "NO_TIER"


def test_sap_execute_prod_guard_dict() -> None:
    out = sap_execute(task="create_sales_order", system="PRD", env="prd", mutating=True)
    assert out["ok"] is False and out["error"]["code"] == "PROD_BLOCKED"


def test_tier_enum_serializes_to_int() -> None:
    assert int(Tier.COMPUTER_USE) == 3
