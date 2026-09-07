"""MCP server skeleton. Thin, tier-agnostic surface over the Router.

M0 exposes `sap_execute` (router entry point) wired to a catalog with no backends
registered yet — so it returns typed NO_TIER rather than pretending to act. Real
tiers register here from M1 onward.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .backends import RfcBackend
from .catalog import load_catalog
from .models import System, Task
from .router import Router

_DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "catalog" / "catalog.json"


def build_router() -> Router:
    catalog_path = os.environ.get("SAPGUI_MCP_CATALOG", str(_DEFAULT_CATALOG))
    catalog = load_catalog(catalog_path)
    # Pass the path so probe results are written back — learn once, never re-pay.
    router = Router(catalog, catalog_path=catalog_path)
    router.register(RfcBackend(catalog))  # Tier 0 — RFC/BAPI (pyrfc loaded lazily)
    # TODO(M2+): sapcli/OData (Tier 0), WebGUI (Tier 2), recorded (Tier 1), computer-use (Tier 3)
    return router


mcp = MCPServer("sapgui-mcp")
_router = build_router()


@mcp.tool()
def sap_execute(
    task: str,
    system: str,
    params: dict[str, Any] | None = None,
    env: str = "unknown",
    constraints: dict[str, Any] | None = None,
    mutating: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run an SAP task via the cheapest capable tier.

    Args:
        task: logical task name (catalog key), e.g. "create_sales_order".
        system: `creds` index id of the target system.
        params: task parameters.
        env: environment of the system (dev|qas|prd|sbx); drives the prod guard.
        constraints: e.g. {"must_stay_in_live_session": true, "allow_prod": false}.
        mutating: whether this task changes SAP state.
        dry_run: validate/preview without committing.
    """
    result = _router.execute(
        Task(name=task),
        params or {},
        System(creds_id=system, env=env),
        constraints=constraints,
        mutating=mutating,
        dry_run=dry_run,
    )
    return {
        "ok": result.ok,
        "tier": int(result.tier) if result.tier is not None else None,
        "reason": result.reason,
        "data": result.data,
        "error": None if result.error is None else {"code": result.error.code, "message": result.error.message},
        "mutated": result.mutated,
        "evidence": result.evidence,
        "fallbacks": [{"code": f.code, "message": f.message} for f in result.fallbacks],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
