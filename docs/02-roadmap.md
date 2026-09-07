# Roadmap — Milestones, Tasks, Test Criteria

Companion to `docs/01-architecture.md`. Every milestone ships behind the same quality gate (§B). Nothing is "done" until positive **and** negative tests pass and the change is verified against a real non-prod system.

---

## A. The development loop (per task)

```
 develop → test(positive) → test(negative) → verify(real non-prod system)
     ↑                                                     │
     └──────────────────  fix  ←──── fail ────────────────┘
```

1. **Develop** the smallest thing that satisfies the task's acceptance criteria (ponytail: cheapest tier, shortest diff).
2. **Positive tests** — the happy path returns the expected structured result.
3. **Negative tests** — bad input / missing auth / locked object / dropped session / prod-guard / buggy-WebGUI must fail **gracefully and correctly**: right typed error, `mutated=false` on failure, no wrong-system write, no partial commit.
4. **Verify** against a real `creds` **non-prod** system (integration test, marked, opt-in).
5. **Fix → re-test → re-verify** until green. Only then close the task.

Unit tests mock backends → deterministic, run every commit. Integration tests hit real SAP → run on demand / CI with a sandbox `creds` id. **No negative test ever runs a destructive op against prod.**

---

## B. Definition of Done (quality gate — every milestone)

- [ ] Positive tests pass.
- [ ] Negative tests pass (each failure mode below has a test).
- [ ] Verified against a real non-prod system (or explicitly N/A with reason).
- [ ] Coverage ≥ 80% on changed modules.
- [ ] Router reports correct `tier` + reason for every path.
- [ ] `mutated` flag correct; write paths honor `dry_run` and the prod guard.
- [ ] No secret in code/catalog/logs; creds only via `creds exec`.
- [ ] Code review pass (self or `code-reviewer` agent); CRITICAL/HIGH resolved.

---

## C. Cross-cutting failure modes (the negative-test catalogue)

Every backend must be tested against the ones that apply to it:

| Code | Failure | Correct behavior |
|------|---------|------------------|
| `AUTH` | bad/expired creds, no authorization object | typed error, no retry storm, no leak |
| `NOT_FOUND` | task/element/field absent | typed error → router may fall to next tier |
| `LOCKED` | SAP enqueue lock held | typed error, `mutated=false` |
| `PROD_BLOCKED` | write to `env: prd` without authorization | refuse before any call |
| `UI_BUG` | WebGUI screen broken/missing control | mark catalog `buggy`, fall to Tier 3 |
| `DROPPED` | session/connection lost mid-run | typed error, no assumption of success |
| `PARTIAL` | multi-step write interrupted | roll back or report exact state; never claim success |
| `STALE_CATALOG` | cached tier no longer works | re-probe once, update catalog, continue |
| `PARAM_INVALID` | params don't match task schema | reject before execution |

---

## Milestones

### M0 — Scaffolding & contracts
Fork `Hochfrequenz/sapgui.mcp`; strip to a clean base; establish the shared contracts and test harness.

**Tasks**
- Fork + public repo + LICENSE/NOTICE with attribution (see architecture §8).
- Define `Backend` protocol, `Result`, typed `ErrorInfo`, `Task`/`System` models.
- Capability-catalog schema + loader/validator (JSON schema).
- Test harness: pytest, unit vs `@integration` marks, a `creds`-backed fixture that resolves a **non-prod** sandbox id.
- CI: lint + type + unit on every push; integration on demand.

**Pass:** contracts import; catalog validates a sample; empty backends register; `sap_execute` returns `NOT_FOUND` for an unknown task with no crash.
**Positive test:** router loads catalog, lists registered tiers.
**Negative test:** malformed catalog → validation error (not a crash); unknown task → typed `NOT_FOUND`.
**Verify:** `creds find` resolves the chosen sandbox id; fixture connects to nothing yet (contract only).

---

### M1 — Tier 0: RFC/BAPI (highest value, cheapest, most testable)
Headless RFC via pyrfc + `creds exec`.

> **Status: code complete; live positive verify PENDING.**
> Unit tests green (44 total, 94% cov, ruff + mypy strict clean). Live *negative*
> path CONFIRMED against `ibyte-sbx-abap-s4h`: a real `RFC_COMMUNICATION_FAILURE`
> mapped correctly to `ErrorCode.DROPPED` at Tier 0. Live *positive* path is
> blocked — the ibyte SAProuter `s4.ibytecloud.net:3299` refuses connections
> (ERRNO 61). Re-run when reachable:
> `creds exec ibyte-sbx-abap-s4h -- uv run pytest -m integration`
>
> Setup notes: pyrfc is not on PyPI (yanked) — install via `uv sync --extra rfc`
> with `SAPNWRFC_HOME` set to a NW RFC SDK. `backends/_sdk.py` colocates the SDK
> dylibs next to the pyrfc extension because macOS strips `DYLD_*` across
> `creds exec`.

**Tasks**
- RFC backend: connect via `CREDS_JCO_DEST`/`kind: rfc` entry; call function modules; map results to `Result`.
- Read path: `RFC_READ_TABLE` (or ADT) for table reads.
- Write path: a BAPI create with `BAPI_TRANSACTION_COMMIT`, `dry_run` = validate-only (no commit).
- Catalog: record `bapi`, `commit`, `params`, `verified` on success.

**Pass:** a table read returns rows as structured data; a BAPI create in `dry_run` validates without mutating; a real create commits and is re-readable.
**Positive tests:** read known table returns expected columns; BAPI dry-run returns `ok, mutated=false`; BAPI real-run returns key + `mutated=true`.
**Negative tests:** `AUTH` (bad creds), `NOT_FOUND` (bogus FM name), `LOCKED` (locked object), `PARAM_INVALID` (missing required field), `PROD_BLOCKED` (attempt write to a `prd` id → refused before call).
**Verify:** run read + dry-run + one real create against the non-prod sandbox; confirm the created object exists, then confirm prod-guard refuses the same create against a `prd` id.

---

### M2 — Tier 0: sapcli / ADT
Table reads, run reports/programs, dev-object ops — the developer/Basis branch.

**Tasks**
- Wrap `sapcli` (or ADT REST directly) behind the backend: table read, run program, fetch output.
- Catalog qualifier: task-shape → sapcli vs RFC.

**Pass:** SE16-style read and a report run both return structured output headlessly.
**Positive tests:** read `MARA` subset; run a harmless report (e.g. `RSPARAM`) and capture output.
**Negative tests:** `AUTH`, `NOT_FOUND` (bad program), `PARAM_INVALID`, timeout handling.
**Verify:** both against sandbox; compare read output to the same data via RFC (consistency).

---

### M3 — Router + capability catalog (the brain)
Wire the deterministic cascade (architecture §4) + probe + promotion hooks.

**Tasks**
- Implement `route()`, `probe_and_route()`, staleness re-probe, `system_overrides`.
- Fallback logic: runtime failure → mark catalog → next tier → report both.
- `constraints` handling (`must_stay_in_live_session`, `allow_prod`).

**Pass:** given a catalog, the router picks the cheapest valid tier; a simulated tier failure falls through correctly; probe writes back to catalog.
**Positive tests:** task with Tier-0 entry → Tier 0 chosen; task with only Tier-2 → Tier 2 chosen; `must_stay_in_live_session` → Tier 0 skipped.
**Negative tests:** all tiers fail → aggregated typed error (no infinite loop); `STALE_CATALOG` → single re-probe then proceed; fallback never re-runs the same failing tier; `allow_prod` absent → write tiers refuse on `prd`.
**Verify:** end-to-end on sandbox: same logical task routed to Tier 0, then (Tier 0 disabled) forced to a live tier, producing equivalent result.

---

### M4 — Tier 2: WebGUI (Playwright)
Adapt the baseline's Playwright backend; add SAP-aware locators (borrow `playwright-sap` patterns).

**Tasks**
- WebGUI login + transaction entry + field I/O + table read via DOM.
- `buggy` detection → emit `UI_BUG` → router falls to Tier 3.
- `dry_run`: stop before the final commit control.

**Pass:** a transaction is completed via WebGUI with structured confirmation; a flagged-buggy screen triggers fallback.
**Positive tests:** enter tx, set fields, read result table, (dry-run) stop pre-commit.
**Negative tests:** `UI_BUG` (missing control) → `UI_BUG` + fallback signal; `DROPPED` (session timeout); `NOT_FOUND` (locator miss); `PROD_BLOCKED` on write.
**Verify:** run a real read-only tx on sandbox WebGUI; force a buggy screen and confirm the router falls to Tier 3.

---

### M5 — Tier 1: recorded script + promotion (Java `GuiStartS.jar`)
Record-once-replay for routine flows.

**Tasks**
- `sap_record` capture → parameterized `script.js`; store + catalog `tier1`.
- Replay via `java -cp GuiStartS.jar com.sap.platin.Gui -n -b -f script.js` (+ `-t NOPHANTOM` on mac); parse output.
- Promotion hook: after a successful Tier 2/3 routine run, offer to record.

**Pass:** a recorded routine replays deterministically with new params and no vision cost.
**Positive tests:** record a 3-screen flow, replay with different params, assert output.
**Negative tests:** `PARAM_INVALID` (params don't match recorded schema → reject, don't run); replay against changed screen → detect mismatch, fail cleanly (don't blunder forward); missing `GuiStartS.jar` → clear setup error.
**Verify:** record + replay on sandbox Java GUI; confirm second run consumes ~no tokens.

---

### M6 — Tier 3: computer-use (SAP GUI for Java, macOS) — marquee lane
The fallback that makes the Java desktop controllable at all.

**Tasks**
- Drive SAP GUI for Java via the `computer-use` MCP: screenshot → locate (AX tree first, vision fallback) → click/type → verify.
- Verification discipline: after each action, confirm expected state before the next (bounded loop, not open-ended).
- Escape-hatch tools (`sap_cu_*`) surfaced for manual recovery.

**Pass:** a transaction with **no** API and **no** working WebGUI is completed on the Java desktop, with screenshot evidence and a correct structured summary.
**Positive tests:** launch tx, fill fields, submit, read confirmation (assert on extracted text, not just a screenshot).
**Negative tests:** element not found after N attempts → stop with `NOT_FOUND` (no infinite loop / no wild clicking); wrong screen detected → abort, don't mutate; `PROD_BLOCKED` before any write; ambiguous state → ask, don't guess.
**Verify:** run a real routine on your Mac against sandbox; measure cost vs the same task in Tier 0/2 (proves the cost ladder).

---

### M7 — End-to-end routing + cost report
Prove the whole cascade + promotion on real tasks; make cost visible.

**Tasks**
- 3 representative tasks exercised end-to-end: one Tier-0-native, one WebGUI-only, one Java-desktop-only.
- Promotion demo: a Java-desktop routine recorded → promoted → next run is Tier 1.
- Cost telemetry per run (tier, approx tokens, wall time) in `Result`/logs.

**Pass:** each task lands in its expected tier; the promoted task drops a tier on second run; cost report shows Tier 3 used least.
**Positive tests:** the three tasks route as predicted; promotion lowers tier + cost.
**Negative tests:** Tier-0 outage → graceful fallback for the native task; corrupted recorded script → falls back, re-promotes.
**Verify:** full run on sandbox; capture the cost report as the acceptance artifact.

---

## D. Test data & safety rules

- **Systems:** all real testing uses a **non-prod** `creds` id (resolve with `creds find ... qas|dev|sbx`). Confirm `env` before any write test.
- **Prod:** never in the automated suite. Any prod interaction is manual, explicitly authorized, `CREDS_ALLOW_PROD=1` set only per-command after asking.
- **Idempotency:** create-tests clean up (or use throwaway ranges) so the suite is re-runnable.
- **Evidence:** Tier 2/3 tests keep screenshots on failure only (cost/noise control).

---

## E. Suggested sequence & rough sizing

M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. M1 and M6 are the two biggest. If you want the **Java lane first** (it's what you use daily), we can pull M6 forward to right after M0 — accepting that we build the hardest-to-test, most expensive lane before the cheap ones and before the router has anything to fall *from*. Recommended default keeps M6 late.
