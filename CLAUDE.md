# sapgui-mcp

Cost-routed MCP server for SAP. See `docs/01-architecture.md` for the tier ladder and
`docs/02-roadmap.md` for milestones and the Definition of Done.

## Driving SAP GUI

**Use the `sap-gui-control` skill.** Never screenshot SAP GUI to find out what is on screen,
and never guess at why an action failed.

If input to SAP GUI does nothing, run the preflight before forming any theory:

```bash
bash ~/.claude/skills/sap-gui-control/scripts/tier3_preflight.sh
```

Three separate sessions have reported "a macOS Open/Save dialog is attached to the SAP GUI,
blocking input". That dialog has never existed. The real causes are the frontmost-app tier
policy, a SAP dynpro popup owning input (invisible to sheet/modal checks), or several sessions
sharing identical geometry. The preflight distinguishes them.

## Working rules

- Cheapest tier that can do the job: RFC/OData/sapcli → recorded script → WebGUI → AX → vision.
- Tier selection must itself be free — a catalog lookup, never a discovery loop.
- Credentials only via `creds exec <id>`; never echo `CREDS_PASSWORD`.
- Production writes are refused unless explicitly authorized in-conversation.
- Prefer programmatic routes over anything that takes over the screen.
- Report honestly: "code complete" and "verified against a real system" are different claims.

## Verify

```bash
uv run --no-sync pytest -q      # or: PYTHONPATH=src .venv/bin/python -m pytest -q
uv run --no-sync ruff check .
uv run --no-sync mypy
```
