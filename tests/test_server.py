"""Smoke test the MCP tool wiring: it builds a router from the shipped catalog and
returns a typed result dict without any backend registered (M0)."""

from __future__ import annotations

from sapgui_mcp.models import Tier
from sapgui_mcp.server import build_router, sap_execute


def test_build_router_loads_shipped_catalog() -> None:
    r = build_router()
    assert r.registered_tiers() == []  # no backends yet at M0


def test_sap_execute_returns_no_tier_dict() -> None:
    # Known task, but no backends registered -> honest NO_TIER, not a fake success.
    out = sap_execute(task="create_sales_order", system="SBX", env="sbx")
    assert out["ok"] is False
    assert out["error"]["code"] == "NO_TIER"
    assert out["mutated"] is False


def test_sap_execute_prod_guard_dict() -> None:
    out = sap_execute(task="create_sales_order", system="PRD", env="prd", mutating=True)
    assert out["ok"] is False and out["error"]["code"] == "PROD_BLOCKED"


def test_tier_enum_serializes_to_int() -> None:
    assert int(Tier.COMPUTER_USE) == 3
