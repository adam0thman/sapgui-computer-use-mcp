# Installing the sap-gui-control skill

This directory is the versioned source. Claude reads skills from `~/.claude/skills/`,
so install (or re-install after changes) with:

```bash
cp -r skills/sap-gui-control ~/.claude/skills/
```

User-level (`~/.claude/skills/`) rather than project-level (`.claude/skills/`) on purpose:
SAP work happens in many sessions and directories, not just this repo. A user-level skill
loads everywhere.

Verify it is picked up by starting a new session and asking anything about driving SAP GUI —
or run the scripts directly:

```bash
bash ~/.claude/skills/sap-gui-control/scripts/tier3_preflight.sh
```
