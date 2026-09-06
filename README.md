# sapgui-mcp

**Cost-routed MCP server for SAP.** One tool, four tiers. It runs your SAP task via
the **cheapest mechanism that can do it**, and only falls back to expensive vision
loops when nothing else works.

```
Tier 0  API          RFC/BAPI · OData · sapcli/ADT        ~free, headless
Tier 1  Recorded     script.js (Java) · VBScript (Win)    ~free after capture
Tier 2  WebGUI       Playwright on the HTML GUI            low cost
Tier 3  Computer-use vision + mouse (SAP GUI for Java)     expensive — last resort
```

The router decides from a **capability catalog** (a free lookup — never a vision
loop just to pick a tier), falls down the ladder on failure, and can **promote** a
routine you did once in Tier 2/3 into a recorded Tier-1 script so the next run is
near-free.

> **Status:** M0 — scaffolding & contracts. The router, catalog, models, prod guard
> and test harness are in place; tier backends land in M1+. See
> [`docs/02-roadmap.md`](docs/02-roadmap.md).

## Why

SAP GUI for **Java** (macOS/Linux) has **no external live-attach** — COM scripting
is Windows-only — so interactive AI control of the Java desktop is only possible via
vision (Tier 3), which is costly. This project treats vision as the fuel of last
resort and pushes every task to a cheaper, deterministic tier first. See
[`docs/01-architecture.md`](docs/01-architecture.md).

## Design docs

- [`docs/01-architecture.md`](docs/01-architecture.md) — routing spec, capability-catalog schema, backend contract, security model.
- [`docs/02-roadmap.md`](docs/02-roadmap.md) — milestones, pass/fail criteria, positive + negative testing, the develop→test→verify→fix loop.

## Develop

```bash
uv sync --extra dev
uv run pytest          # unit tests (integration tests are opt-in: -m integration)
uv run ruff check .
uv run mypy
```

Credentials are resolved **only** through the `creds` CLI (`creds exec <id> -- ...`);
no secrets live in this repo or the catalog. Production writes are refused unless
explicitly authorized.

## Credits & kudos

This project **forks and builds on the excellent [Hochfrequenz/sapgui.mcp](https://github.com/Hochfrequenz/sapgui.mcp)** (MIT) —
which pioneered the backend-routed shape we extend (COM desktop + Playwright WebGUI).
Huge thanks to the maintainers.

Patterns and inspiration gratefully borrowed from (all MIT unless noted):

- [mario-andreschak/mcp-sap-gui](https://github.com/mario-andreschak/mcp-sap-gui) — the Tier-3 computer-use tool shapes.
- [kts982/mcp-sap-gui](https://github.com/kts982/mcp-sap-gui) — the Windows COM tool taxonomy (fields, ALV grids, table controls, trees, preview, confirmation points).
- [oisee/odata_mcp_go](https://github.com/oisee/odata_mcp_go) & [lemaiwo/btp-sap-odata-to-mcp-server](https://github.com/lemaiwo/btp-sap-odata-to-mcp-server) — Tier-0 OData→MCP exposure.
- [jfilak/sapcli](https://github.com/jfilak/sapcli) (Apache-2.0) — Tier-0 ADT / table-read / report-run.
- [playwright-sap](https://playwright-sap.dev) — SAP-aware locators for the WebGUI tier.
- [marianfoo/sap-ai-mcp-servers](https://github.com/marianfoo/sap-ai-mcp-servers) — the map of the SAP MCP ecosystem.

See [`NOTICE`](NOTICE) for license attributions.

Not affiliated with or endorsed by SAP SE. "SAP", "SAP GUI", "S/4HANA", "Fiori" are
trademarks of SAP SE.

## License

MIT — see [`LICENSE`](LICENSE).
