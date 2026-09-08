# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [0.1.0] — 2026-09-08

First tagged release. The cost-routing core and the cheapest tier are working and
verified against a real SAP system.

### Added

**Contracts & routing (M0, M3)**
- `Backend` protocol and typed `Result` / `ErrorInfo` contracts; `Tier` cost ladder
  (0 API → 1 recorded script → 2 WebGUI → 3 computer-use).
- Deterministic cheapest-first router with fallback: a tier is tried at most once,
  a runtime failure falls to the next tier and reports both.
- Capability catalog (pydantic-validated JSON) with aliases and per-system overrides.
- **Probe-on-cache-miss**: an unknown task is discovered once, written back to the
  catalog, and never re-paid. Tier selection itself is always a free lookup.
- Staleness: specs older than 90 days, and `STALE_CATALOG` errors, re-probe exactly
  once — loop-guarded.
- `UI_BUG` is remembered per-system via `system_overrides`, never globally.
- Atomic catalog persistence; a write failure is non-fatal.

**Tier 0 — RFC/BAPI (M1)**
- `RfcBackend` over pyrfc: generic function-module calls, `RFC_READ_TABLE` reads, and
  BAPI writes where `dry_run` validates then rolls back and only a real run commits.
- BAPIRET2 inspection blocks the commit on any `E`/`A` return and issues a rollback.
- pyrfc exceptions mapped to typed `AUTH` / `DROPPED` / `LOCKED` / `BACKEND`.
- `RfcBackend.probe`: read-only `TFDIR` existence check. Task names are regex-validated
  before reaching a WHERE clause (trust boundary — rejected, not escaped).
- `backends/_sdk.py` colocates the NW RFC SDK dylibs next to the pyrfc extension, so it
  loads without `DYLD_*` (macOS strips those across `creds exec`). Bounded, explicit
  search paths only — it never crawls the filesystem.

**Safety**
- Production writes refused unless explicitly authorized, checked before any tier runs
  and before any probe cost.
- `must_stay_in_live_session` skips Tier 0 (which opens its own headless connection).
- Credentials come only from `creds exec`; nothing secret is stored in the repo,
  the catalog, or logs.

### Verified

Live against an S/4HANA sandbox (S4H, release 757, HANA/Linux):
- `RFC_SYSTEM_INFO` call and a `T000` table read (rows parsed correctly).
- Write safety: a real SAP `E V1312` rejection produced a ROLLBACK with the COMMIT
  never called and `mutated=False`.
- A real `RFC_COMMUNICATION_FAILURE` mapped to `DROPPED`.
- Full learn loop: empty catalog → probed once → learned → persisted → executed;
  the second call was a cache hit with no re-probe.

Quality gate: 66 tests, 94% coverage, `ruff` clean, `mypy --strict` clean.

### Known limitations

- **A successful committing BAPI write is not yet verified live** — it needs valid
  master data. The failure path is proven; the commit path is unit-tested only.
- Tiers 1 (recorded script), 2 (WebGUI) and 3 (computer-use) are **not implemented**.
  Only Tier 0 exists, so there is nothing to fall back *to* yet.
- `RfcBackend.probe` matches only when the task name IS the function-module name.
  Mapping arbitrary business tasks to BAPIs is unsolved.
- Tier 0 requires the SAP NW RFC SDK (a separate SAP download) and a source build of
  pyrfc; PyPI's pyrfc release is yanked.

[0.1.0]: https://github.com/adam0thman/sapgui-computer-use-mcp/releases/tag/v0.1.0
