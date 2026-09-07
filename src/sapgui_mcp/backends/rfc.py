"""Tier 0 — headless RFC/BAPI backend (pyrfc over the SAP NW RFC SDK).

Cheapest, most deterministic tier. Connects with credentials injected by
`creds exec <id>` (CREDS_* env vars); no secrets touch the code or the catalog.

Supported ops, driven by the catalog's `tier0.rfc` entry:
  {"op": "table_read", "table": "MARA", "fields": [...], "options": [...]}
  {"fm": "RFC_SYSTEM_INFO"}                       # generic read-only FM call
  {"bapi": "BAPI_...", "commit": "BAPI_TRANSACTION_COMMIT"}  # write; dry_run skips commit
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Protocol

from ..catalog import Catalog
from ..models import Confidence, ErrorCode, ErrorInfo, ProbeHit, Result, System, Task, Tier

# A task name is only treated as a function-module name if it matches this exactly.
# This is a TRUST BOUNDARY: the name reaches a WHERE clause, so anything outside
# SAP's own identifier charset is rejected rather than escaped.
_FM_NAME = re.compile(r"^[A-Z0-9_/]{3,30}$")

log = logging.getLogger(__name__)


class Connectionish(Protocol):
    def call(self, fm: str, **kwargs: Any) -> dict[str, Any]: ...
    def close(self) -> None: ...


def connection_params_from_env() -> dict[str, str]:
    """Build pyrfc params from the env injected by `creds exec`. Raises KeyError if absent."""
    params = {
        "user": os.environ["CREDS_USER"],
        "passwd": os.environ["CREDS_PASSWORD"],
        "client": os.environ["CREDS_CLIENT"],
        "ashost": os.environ["CREDS_HOST"],
        "sysnr": os.environ["CREDS_SYSNR"],
        "lang": os.environ.get("CREDS_LANG", "EN"),
    }
    if router := os.environ.get("CREDS_ROUTER"):
        params["saprouter"] = router
    return params


def _default_connector(system: System) -> Connectionish:
    params = connection_params_from_env()  # raises KeyError before touching the native lib
    from ._sdk import ensure_sdk_dylibs

    ensure_sdk_dylibs()
    from pyrfc import Connection

    conn: Connectionish = Connection(**params)
    return conn


class RfcBackend:
    tier = Tier.API

    def __init__(self, catalog: Catalog, connector: Any = _default_connector) -> None:
        self._catalog = catalog
        self._connect = connector

    def _spec_for(self, task: Task, system: System) -> dict[str, Any] | None:
        entry = self._catalog.lookup(task.name, system.creds_id)
        return entry.tier0.rfc if entry and entry.tier0.rfc else None

    def can_handle(self, task: Task, system: System) -> Confidence:
        # Cheap catalog lookup — no SAP contact. True iff this task has an rfc spec.
        if self._spec_for(task, system) is None:
            return Confidence(False, "no tier0.rfc spec for task")
        return Confidence(True, "rfc spec present")

    def probe(self, task: Task, system: System) -> ProbeHit | None:
        """Discover capability: does a function module of this name exist here?

        Read-only — it establishes capability, it never performs the task.

        Heuristic and deliberately narrow: it only matches when the task name IS
        the function-module name (e.g. "BAPI_USER_GET_DETAIL"). Mapping arbitrary
        business tasks to BAPIs needs more than a name lookup; until then an
        unmatched task simply falls to a later tier.
        """
        candidate = task.name.strip().upper()
        if not _FM_NAME.match(candidate):
            return None
        try:
            conn = self._connect(system)
        except Exception:
            log.debug("probe could not connect for %s", task.name, exc_info=True)
            return None
        try:
            out = conn.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="TFDIR",
                DELIMITER="|",
                FIELDS=[{"FIELDNAME": "FUNCNAME"}],
                OPTIONS=[{"TEXT": f"FUNCNAME = '{candidate}'"}],
                ROWCOUNT=1,
            )
            return ProbeHit("tier0.rfc", {"fm": candidate}) if out.get("DATA") else None
        except Exception:
            log.debug("probe failed for %s", task.name, exc_info=True)
            return None
        finally:
            _safe_close(conn)

    def execute(
        self, task: Task, params: dict[str, Any], system: System, *, dry_run: bool = False
    ) -> Result:
        spec = self._spec_for(task, system)
        if spec is None:
            return Result.failure(
                ErrorCode.NOT_FOUND, f"no tier0.rfc spec for task {task.name!r}", self.tier
            )
        try:
            conn = self._connect(system)
        except KeyError as e:  # missing CREDS_* -> not launched under `creds exec`
            return Result.failure(
                ErrorCode.AUTH,
                f"missing credential env {e}; launch the server under `creds exec {system.creds_id}`",
                self.tier,
            )
        except Exception as e:  # noqa: BLE001 - map any pyrfc connect error
            return self._map_error(e)

        try:
            if "op" in spec and spec["op"] == "table_read":
                return self._table_read(conn, spec, params)
            if "bapi" in spec:
                return self._bapi(conn, spec, params, dry_run=dry_run)
            if "fm" in spec:
                return self._fm_call(conn, spec["fm"], params)
            return Result.failure(
                ErrorCode.PARAM_INVALID, f"rfc spec has no op/bapi/fm: {spec!r}", self.tier
            )
        except Exception as e:  # noqa: BLE001 - map any pyrfc call error
            return self._map_error(e)
        finally:
            _safe_close(conn)

    # -- operations -------------------------------------------------------------

    def _fm_call(self, conn: Connectionish, fm: str, params: dict[str, Any]) -> Result:
        kwargs = params.get("args", {})
        out = conn.call(fm, **kwargs)
        return Result(ok=True, tier=self.tier, reason=f"called {fm}", data=out, mutated=False)

    def _table_read(self, conn: Connectionish, spec: dict[str, Any], params: dict[str, Any]) -> Result:
        table = params.get("table") or spec["table"]
        fields = params.get("fields") or spec.get("fields") or []
        options = params.get("options") or spec.get("options") or []
        out = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE=table,
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": f} for f in fields],
            OPTIONS=[{"TEXT": o} for o in options],
            ROWCOUNT=params.get("rowcount", 0),
        )
        rows = _parse_read_table(out)
        return Result(
            ok=True, tier=self.tier, reason=f"read {table} ({len(rows)} rows)",
            data={"table": table, "rows": rows}, mutated=False,
        )

    def _bapi(
        self, conn: Connectionish, spec: dict[str, Any], params: dict[str, Any], *, dry_run: bool
    ) -> Result:
        bapi = spec["bapi"]
        args = params.get("args", {})
        out = conn.call(bapi, **args)

        bapi_err = _bapi_return_error(out)
        if bapi_err is not None:
            # Application-level failure -> never commit. Roll back to be safe.
            _rollback(conn)
            code = ErrorCode.LOCKED if _looks_like_lock(bapi_err) else ErrorCode.BACKEND
            return Result.failure(code, f"{bapi}: {bapi_err}", self.tier)

        if dry_run:
            _rollback(conn)  # validate-only: discard anything staged
            return Result(
                ok=True, tier=self.tier, reason=f"{bapi} validated (dry_run, not committed)",
                data=out, mutated=False,
            )

        commit_fm = spec.get("commit")
        if commit_fm:
            conn.call(commit_fm, WAIT="X")
        return Result(ok=True, tier=self.tier, reason=f"{bapi} committed", data=out, mutated=True)

    # -- error mapping ----------------------------------------------------------

    def _map_error(self, e: Exception) -> Result:
        name = type(e).__name__
        msg = str(e)
        code = {
            "LogonError": ErrorCode.AUTH,
            "CommunicationError": ErrorCode.DROPPED,
            "ConnectionError": ErrorCode.DROPPED,
        }.get(name, ErrorCode.BACKEND)
        if code is ErrorCode.BACKEND and _looks_like_lock(msg):
            code = ErrorCode.LOCKED
        return Result(ok=False, tier=self.tier, reason=msg, error=ErrorInfo(code, msg, self.tier))


# -- helpers ------------------------------------------------------------------


def _parse_read_table(out: dict[str, Any]) -> list[dict[str, str]]:
    fields = [f["FIELDNAME"] for f in out.get("FIELDS", [])]
    rows: list[dict[str, str]] = []
    for entry in out.get("DATA", []):
        cells = entry["WA"].split("|")
        rows.append(dict(zip(fields, (c.strip() for c in cells), strict=False)))
    return rows


def _bapi_return_error(out: dict[str, Any]) -> str | None:
    ret = out.get("RETURN")
    items = ret if isinstance(ret, list) else ([ret] if ret else [])
    for r in items:
        if r.get("TYPE") in ("E", "A"):
            return f"{r.get('TYPE')} {r.get('ID', '')}{r.get('NUMBER', '')}: {r.get('MESSAGE', '')}".strip()
    return None


def _looks_like_lock(msg: str) -> bool:
    m = msg.lower()
    return "lock" in m or "enqueue" in m or "foreign_lock" in m


def _rollback(conn: Connectionish) -> None:
    """Best-effort rollback. A failure here is logged, never raised over the real error."""
    try:
        conn.call("BAPI_TRANSACTION_ROLLBACK")
    except Exception:
        log.warning("BAPI_TRANSACTION_ROLLBACK failed; SAP state may be uncertain", exc_info=True)


def _safe_close(conn: Connectionish) -> None:
    try:
        conn.close()
    except Exception:
        log.debug("closing RFC connection failed", exc_info=True)
