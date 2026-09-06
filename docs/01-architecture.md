# Architecture & Routing Spec

**Project:** `sapgui-mcp` (working name; repo `sapgui-computer-use-mcp`)
**Goal:** One MCP server that performs an SAP task via the **cheapest tier that can do it**, falling down a deterministic ladder only when a tier can't, and **learning** so routine tasks get cheaper over time.

---

## 1. Design principles

1. **Cost is the primary optimization axis.** Vision loops (Tier 3) are the most expensive fuel and the last resort. Everything the router does is in service of keeping tasks *out* of Tier 3.
2. **The routing decision must itself be free.** "Can this be done via RFC?" is a **catalog lookup**, never a discovery loop. You must never pay vision cost just to decide not to use vision.
3. **Learn once, replay free.** The first time a routine task has no API, solve it once (Tier 2/3), then record it as a parameterized script and **promote** it to Tier 1. Every future run is near-free.
4. **No silent tier switches.** Every result reports which tier ran and why. A fallback is logged, never hidden.
5. **Never mutate the wrong system.** Tier selection is orthogonal to the prod-guard: any write path re-checks `env` and refuses prod unless explicitly authorized (see §7).

---

## 2. The cost ladder (tiers)

| Tier | Mechanism | Rel. cost/run | Deterministic? | Works when |
|------|-----------|---------------|----------------|------------|
| **0** | Headless API — RFC/BAPI (pyrfc), OData/RAP, ADT/sapcli | ~free | yes | A BAPI / OData service / ABAP object exists for the function |
| **1** | Recorded script — `script.js` (Java) / VBScript (Windows) | ~free after capture | yes | Routine, repetitive, stable flow already recorded |
| **2** | WebGUI — Playwright on DOM | low | mostly | Function exists in HTML GUI and is not flagged buggy |
| **3** | Computer-use — vision + mouse (SAP GUI for Java, macOS) | **high** | no | Nothing above applies (the desktop long tail) |

**Hard platform facts that shaped this** (see `docs/00-research.md` for sources):
- SAP GUI for **Java has no external live-attach** (COM/OLE is Windows-only; JACOB/COMJava are Windows-only). Live interactive control of the Java desktop is **only** possible via Tier 3, or non-interactively via `GuiStartS.jar -f script.js` (Tier 1).
- SAP GUI for **Windows** has full COM scripting (`findById`) — precise, but Windows-only.
- **WebGUI** is browser HTML → Playwright/CDP drives it with structured locators.
- **S/4HANA Cloud** blocks RFC/BAPI/IDoc → Tier 0 there means OData/REST only.

---

## 3. Tier-0 sub-routing (which headless API)

Tier 0 is not one thing. The qualifier picks the sub-mechanism:

| Task shape | Sub-mechanism | Example |
|------------|---------------|---------|
| Business function with a BAPI | **RFC/BAPI** (pyrfc) | `BAPI_SALESORDER_CREATEFROMDAT2` |
| S/4 published API | **OData/RAP** | API Business Hub service |
| Table read (SE16-like) | **sapcli/ADT** or RFC `RFC_READ_TABLE` | read `MARA` |
| Run a report/program, fetch output | **sapcli/ADT** | run `RSPARAM` |
| ABAP dev object op, transports, ABAP Unit | **sapcli/ADT** | activate class, release transport |

`sapcli` is a **developer/Basis/data-read** Tier-0 tool. It is **not** for dynpro business entry (that's BAPI, else GUI).

---

## 4. The routing cascade (deterministic)

Input: `task`, `params`, `system` (a `creds` id), optional `constraints` (e.g. `must_stay_in_live_session`, `allow_prod`).

```
route(task, params, system, constraints):
  cat  = catalog.lookup(task, system)          # free dict lookup; may be empty
  cost = ordered tiers from cat.preferred_order, filtered by constraints

  for tier in cost:
      if tier == 1 and cat.tier1.script and params_match(cat.tier1, params):
          return run_tier1(...)
      if tier == 0 and cat.tier0.available:      # bapi/odata/sapcli present & verified
          return run_tier0(...)
      if tier == 2 and cat.tier2.webgui_ok and not buggy(cat, task, system):
          return run_tier2(...)
      if tier == 3 and cat.tier3.supported:
          return run_tier3(...)                   # expensive; last

  # No cached knowledge → PROBE (costs once), then persist to catalog
  return probe_and_route(task, params, system)

after any successful Tier 2/3 run of a *routine* task:
  offer_promotion(task, system)                   # record → Tier 1 next time
```

**Fallback rule:** a tier may *fail at runtime* (element missing, WebGUI bug, session dropped). On failure the router: (a) marks the catalog entry (`buggy`/`stale`), (b) falls to the next tier, (c) reports both the failure and the fallback. It never retries the *same* failing tier blindly.

**Probe rule:** an unknown task is probed **once** in the cheapest plausible tier (check BAPI existence via RFC metadata → check WebGUI reachability → else Tier 3). The probe result is written to the catalog so it's never re-paid.

---

## 5. Capability catalog (the memory)

A JSON file (per-project, git-tracked; secrets never stored here). Keyed by logical task.

```jsonc
{
  "version": 1,
  "tasks": {
    "create_sales_order": {
      "aliases": ["VA01", "create sales order"],
      "tier0": {
        "rfc":    { "bapi": "BAPI_SALESORDER_CREATEFROMDAT2",
                    "commit": "BAPI_TRANSACTION_COMMIT",
                    "params": ["order_header_in", "order_items_in"],
                    "verified": "2026-09-06" },
        "odata":  null,
        "sapcli": null
      },
      "tier1": { "script": "scripts/va01_create.js", "platform": "java",
                 "params": ["sold_to","material","qty"], "verified": null },
      "tier2": { "webgui_ok": true, "entry": "va01", "buggy": [] },
      "tier3": { "supported": true, "notes": "fallback only" },
      "preferred_order": ["tier0.rfc","tier1","tier2","tier3"],
      "system_overrides": {
        "S4P": { "tier2": { "buggy": ["schedule_lines_tab"] } }
      }
    }
  }
}
```

- `verified` = last date the entry was confirmed to work → drives staleness re-probe.
- `system_overrides` = a function can be buggy in WebGUI on one system only.
- Missing task = probe on first use.

---

## 6. Backend contract (the abstraction that stays honest)

Every tier implements the same interface. The router only knows this interface.

```python
class Backend(Protocol):
    tier: int
    def can_handle(self, task: Task, system: System) -> Confidence: ...   # cheap, catalog-driven
    def execute(self, task: Task, params: dict, system: System,
                dry_run: bool = False) -> Result: ...

@dataclass
class Result:
    ok: bool
    tier: int
    data: dict | None            # structured output (never a screenshot when avoidable)
    error: ErrorInfo | None      # typed: AUTH, NOT_FOUND, LOCKED, PROD_BLOCKED, UI_BUG, DROPPED...
    mutated: bool                # did this change SAP state?
    evidence: str | None         # log/screenshot ref for audit — only Tier 2/3 produce images
```

**Asymmetry is by design:** Tier 0/1/2 return structured `data`; Tier 3 returns coarser results with `evidence` screenshots. The contract does **not** pretend the Java lane is as precise as the Windows lane — that asymmetry is a property of SAP, not a bug in the design.

### MCP tool surface (thin, tier-agnostic)

- `sap_execute(task, params, system, constraints)` — the router entry point (primary tool).
- `sap_query(read_spec, system)` — read-only convenience (routes to Tier 0 table read / OData).
- `sap_record(task, system)` → start/stop capture, persist Tier-1 script (promotion).
- Per-tier **escape hatches** (only surfaced when the AI must drive manually): `sap_cu_click/type/screenshot` (Tier 3), `sap_web_*` (Tier 2), `sap_com_findbyid` (Windows). These are the "manual gear" — the router uses them internally; exposing them lets the model recover when the router gives up.

---

## 7. Connection & security model

- Credentials come **only** from `creds exec <id>` (per global rules). The catalog and code never store secrets.
- **Tiers may open their own connection.** Tier 0 (RFC/OData/sapcli) authenticates headlessly and is *not* the user's live GUI session. `constraints.must_stay_in_live_session=true` forces the router to skip Tier 0 when a task needs the interactive session's context/authorizations.
- **Prod guard (non-negotiable):** any `execute` with `mutated=true` against an `env: prd` system refuses unless `constraints.allow_prod` is set *and* the run is explicitly authorized in-conversation. The router never sets `CREDS_ALLOW_PROD=1` on its own.
- **Dry-run first for writes:** write-capable tasks support `dry_run=true` (Tier 0: validate-only BAPI call / `TESTRUN`; Tier 2/3: stop before the final commit control) so a plan can be previewed before mutation.

---

## 8. Baseline & attribution

We **fork [Hochfrequenz/sapgui.mcp](https://github.com/Hochfrequenz/sapgui.mcp)** (MIT, Python) as the baseline. Rationale: it already implements the core idea of this project — a **backend-routed MCP** with a **COM desktop backend + Playwright WebGUI backend**, 60+ tools, transaction helpers, and session management. Their own docs concede the macOS build is *WebGUI-only* (no live Java desktop control), which is exactly the gap our **Tier 3 (computer-use)** lane fills.

What we add on top of the fork:
- **Tier 0** (RFC/BAPI via pyrfc, OData/RAP, sapcli/ADT) — headless, cheapest.
- **Tier 1** (recorded `script.js` / VBScript) + the **promotion** mechanism.
- **Tier 3** (SAP GUI for Java computer-use on macOS) — the marquee lane.
- **The router + capability catalog** (§4–§5) that ties all tiers into one cost-optimizing decision.

Credited references we borrow patterns from (all MIT):
- **[mario-andreschak/mcp-sap-gui](https://github.com/mario-andreschak/mcp-sap-gui)** — Tier-3 computer-use tool shapes (`sap_click`, `sap_type`, screenshot formats).
- **[kts982/mcp-sap-gui](https://github.com/kts982/mcp-sap-gui)** — Windows COM tool taxonomy (fields, ALV grids, table controls, trees, `sap_preview`, confirmation points).
- **[oisee/odata_mcp_go](https://github.com/oisee/odata_mcp_go)** / **[lemaiwo/btp-sap-odata-to-mcp-server](https://github.com/lemaiwo/btp-sap-odata-to-mcp-server)** — Tier-0 OData→MCP exposure.
- **[jfilak/sapcli](https://github.com/jfilak/sapcli)** (Apache-2.0) — Tier-0 ADT/table-read/report-run.

`LICENSE` and `NOTICE`/`README` will carry the upstream MIT license and this attribution list. Fork lineage kept visible (GitHub fork or an explicit "forked from" note + preserved history where practical).

## 9. Build order rationale

The router can't route without lanes, and cheap lanes are far easier to write reliable pass/fail tests for. So the build order is **Tier 0 → Router → Tier 2 → Tier 1 → Tier 3**, even though the **Java desktop (Tier 3) is the marquee surface you use daily**. Tier 3 lands last because (a) the router must have cheaper lanes to fall *from*, and (b) it's the hardest to test deterministically. If you'd rather see the Java lane working end-to-end first, we reorder — at the cost of building the expensive, hardest-to-verify lane before the cheap ones. See `docs/02-roadmap.md`.
