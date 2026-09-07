"""Live RFC verification. Opt-in: `uv run pytest -m integration`.

Run under creds exec so CREDS_* are present, e.g.:
  creds exec ibyte-sbx-abap-s4h -- uv run pytest -m integration

Skips cleanly if not launched under creds exec. Refuses to run against prod."""

from __future__ import annotations

import os

import pytest

from sapgui_mcp.backends.rfc import RfcBackend
from sapgui_mcp.catalog import Catalog, TaskEntry, Tier0
from sapgui_mcp.models import System, Task

pytestmark = pytest.mark.integration


@pytest.fixture
def live_system() -> System:
    if "CREDS_HOST" not in os.environ:
        pytest.skip("not launched under `creds exec` (no CREDS_HOST)")
    env = os.environ.get("CREDS_ENV", "unknown")
    if env.lower() == "prd":
        pytest.skip("refusing to run integration tests against prod")
    return System(creds_id=os.environ.get("CREDS_SID", "LIVE"), env=env)


def test_rfc_system_info_live(live_system: System) -> None:
    cat = Catalog(version=1, tasks={
        "rfc_system_info": TaskEntry(tier0=Tier0(rfc={"fm": "RFC_SYSTEM_INFO"})),
    })
    res = RfcBackend(cat).execute(Task("rfc_system_info"), {}, live_system)
    assert res.ok, f"live RFC failed: {res.error}"
    assert res.mutated is False
    assert res.data["RFCSI_EXPORT"]["RFCSYSID"].strip()  # a real SID came back
