"""RFC backend: positive + negative, all with a fake connection (no live SAP)."""

from __future__ import annotations

from typing import Any

from sapgui_mcp.backends.rfc import RfcBackend
from sapgui_mcp.catalog import Catalog, TaskEntry, Tier0
from sapgui_mcp.models import ErrorCode, System, Task


# Error classes named exactly as pyrfc's, so the backend's name-based mapping applies.
class LogonError(Exception): ...
class CommunicationError(Exception): ...


class FakeConn:
    def __init__(self, responses: dict[str, Any] | None = None,
                 raise_on: dict[str, Exception] | None = None) -> None:
        self.responses = responses or {}
        self.raise_on = raise_on or {}
        self.calls: list[str] = []

    def call(self, fm: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(fm)
        if fm in self.raise_on:
            raise self.raise_on[fm]
        return self.responses.get(fm, {})

    def close(self) -> None:
        self.calls.append("__close__")


def _catalog(name: str, rfc: dict[str, Any]) -> Catalog:
    return Catalog(version=1, tasks={name: TaskEntry(tier0=Tier0(rfc=rfc))})


def _backend(cat: Catalog, conn: FakeConn) -> RfcBackend:
    return RfcBackend(cat, connector=lambda system: conn)


_SYS = System(creds_id="SBX", env="sbx")


# -- positive -----------------------------------------------------------------

def test_fm_call_returns_data() -> None:
    conn = FakeConn({"RFC_SYSTEM_INFO": {"RFCSI_EXPORT": {"RFCSYSID": "S4H"}}})
    cat = _catalog("info", {"fm": "RFC_SYSTEM_INFO"})
    res = _backend(cat, conn).execute(Task("info"), {}, _SYS)
    assert res.ok and res.mutated is False
    assert res.data["RFCSI_EXPORT"]["RFCSYSID"] == "S4H"
    assert "RFC_SYSTEM_INFO" in conn.calls and "__close__" in conn.calls


def test_table_read_parses_rows() -> None:
    conn = FakeConn({"RFC_READ_TABLE": {
        "FIELDS": [{"FIELDNAME": "MATNR"}, {"FIELDNAME": "MTART"}],
        "DATA": [{"WA": "0001 |FERT"}, {"WA": "0002 |ROH "}],
    }})
    cat = _catalog("read", {"op": "table_read", "table": "MARA", "fields": ["MATNR", "MTART"]})
    res = _backend(cat, conn).execute(Task("read"), {}, _SYS)
    assert res.ok and res.data["rows"] == [
        {"MATNR": "0001", "MTART": "FERT"}, {"MATNR": "0002", "MTART": "ROH"},
    ]


def test_bapi_dry_run_validates_without_commit() -> None:
    conn = FakeConn({"BAPI_X": {"RETURN": [{"TYPE": "S", "MESSAGE": "ok"}]}})
    cat = _catalog("create", {"bapi": "BAPI_X", "commit": "BAPI_TRANSACTION_COMMIT"})
    res = _backend(cat, conn).execute(Task("create"), {"args": {}}, _SYS, dry_run=True)
    assert res.ok and res.mutated is False
    assert "BAPI_X" in conn.calls
    assert "BAPI_TRANSACTION_COMMIT" not in conn.calls
    assert "BAPI_TRANSACTION_ROLLBACK" in conn.calls  # dry-run discards staged work


def test_bapi_real_commits_and_marks_mutated() -> None:
    conn = FakeConn({"BAPI_X": {"RETURN": []}})
    cat = _catalog("create", {"bapi": "BAPI_X", "commit": "BAPI_TRANSACTION_COMMIT"})
    res = _backend(cat, conn).execute(Task("create"), {"args": {}}, _SYS, dry_run=False)
    assert res.ok and res.mutated is True
    assert conn.calls.index("BAPI_X") < conn.calls.index("BAPI_TRANSACTION_COMMIT")


# -- negative -----------------------------------------------------------------

def test_missing_creds_env_is_auth() -> None:
    def bad_connector(system: System) -> FakeConn:
        raise KeyError("CREDS_USER")

    cat = _catalog("info", {"fm": "RFC_SYSTEM_INFO"})
    res = RfcBackend(cat, connector=bad_connector).execute(Task("info"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.AUTH


def test_logon_error_maps_to_auth() -> None:
    def connector(system: System) -> FakeConn:
        raise LogonError("Name or password is incorrect")

    cat = _catalog("info", {"fm": "RFC_SYSTEM_INFO"})
    res = RfcBackend(cat, connector=connector).execute(Task("info"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.AUTH


def test_communication_error_maps_to_dropped() -> None:
    def connector(system: System) -> FakeConn:
        raise CommunicationError("partner not reached")

    cat = _catalog("info", {"fm": "RFC_SYSTEM_INFO"})
    res = RfcBackend(cat, connector=connector).execute(Task("info"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.DROPPED


def test_bapi_error_return_blocks_commit() -> None:
    conn = FakeConn({"BAPI_X": {"RETURN": [{"TYPE": "E", "ID": "V1", "NUMBER": "123",
                                            "MESSAGE": "Customer does not exist"}]}})
    cat = _catalog("create", {"bapi": "BAPI_X", "commit": "BAPI_TRANSACTION_COMMIT"})
    res = _backend(cat, conn).execute(Task("create"), {"args": {}}, _SYS, dry_run=False)
    assert not res.ok and res.mutated is False and res.error.code == ErrorCode.BACKEND
    assert "BAPI_TRANSACTION_COMMIT" not in conn.calls
    assert "BAPI_TRANSACTION_ROLLBACK" in conn.calls


def test_bapi_lock_message_maps_to_locked() -> None:
    conn = FakeConn({"BAPI_X": {"RETURN": [{"TYPE": "E", "MESSAGE": "Object is locked by user"}]}})
    cat = _catalog("create", {"bapi": "BAPI_X", "commit": "BAPI_TRANSACTION_COMMIT"})
    res = _backend(cat, conn).execute(Task("create"), {"args": {}}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.LOCKED


def test_no_rfc_spec_declines_and_not_found() -> None:
    cat = Catalog(version=1, tasks={"x": TaskEntry(tier2={"webgui_ok": True})})  # type: ignore[arg-type]
    b = _backend(cat, FakeConn())
    assert b.can_handle(Task("x"), _SYS).can is False
    res = b.execute(Task("x"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.NOT_FOUND


# -- probe (M3 capability discovery) ------------------------------------------

def test_probe_finds_existing_function_module() -> None:
    conn = FakeConn({"RFC_READ_TABLE": {"FIELDS": [{"FIELDNAME": "FUNCNAME"}],
                                        "DATA": [{"WA": "BAPI_USER_GET_DETAIL"}]}})
    hit = _backend(Catalog(version=1), conn).probe(Task("BAPI_USER_GET_DETAIL"), _SYS)
    assert hit is not None
    assert hit.token == "tier0.rfc" and hit.spec == {"fm": "BAPI_USER_GET_DETAIL"}


def test_probe_returns_none_when_fm_absent() -> None:
    conn = FakeConn({"RFC_READ_TABLE": {"FIELDS": [{"FIELDNAME": "FUNCNAME"}], "DATA": []}})
    assert _backend(Catalog(version=1), conn).probe(Task("BAPI_NOPE"), _SYS) is None


def test_probe_is_read_only() -> None:
    conn = FakeConn({"RFC_READ_TABLE": {"FIELDS": [{"FIELDNAME": "FUNCNAME"}],
                                        "DATA": [{"WA": "BAPI_X"}]}})
    _backend(Catalog(version=1), conn).probe(Task("BAPI_X"), _SYS)
    assert conn.calls == ["RFC_READ_TABLE", "__close__"]  # never executes the task


def test_probe_rejects_names_that_are_not_fm_identifiers() -> None:
    """Trust boundary: the name reaches a WHERE clause — reject, never escape."""
    conn = FakeConn()
    b = _backend(Catalog(version=1), conn)
    for bad in ("bapi'; DROP TABLE T000--", "create sales order", "x", "A" * 31, "BAPI X"):
        assert b.probe(Task(bad), _SYS) is None
    assert conn.calls == []  # nothing injectable ever reached SAP


def test_probe_survives_connection_failure() -> None:
    def boom(system: System) -> FakeConn:
        raise CommunicationError("partner not reached")

    assert RfcBackend(Catalog(version=1), connector=boom).probe(Task("BAPI_X"), _SYS) is None


def test_unknown_spec_shape_is_param_invalid() -> None:
    cat = _catalog("weird", {"something": "unexpected"})
    res = _backend(cat, FakeConn()).execute(Task("weird"), {}, _SYS)
    assert not res.ok and res.error.code == ErrorCode.PARAM_INVALID
