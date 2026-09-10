---
name: "sap-gui-control"
description: "Read and control SAP GUI for Java on macOS without screenshots, coordinates or stealing focus. Use whenever driving, reading, clicking or typing into SAP GUI, running a transaction or OK-code (e.g. /nSE37, SNOTE, SE16), or when input to SAP GUI appears blocked, typing does nothing, or an action silently fails. ALWAYS use this instead of computer-use screenshots for SAP GUI."
user-invocable: true
disable-model-invocation: false
---

# Controlling SAP GUI for Java (macOS)

Drive SAP GUI **in the background** through the macOS Accessibility (AX) API: no screenshots,
no coordinate clicking, no keystrokes, no focus stealing. The user keeps working while you work.

Scripts are in `scripts/` next to this file. Set `SK` to that directory:

```bash
SK=~/.claude/skills/sap-gui-control/scripts
```

## Rule 1 — never guess why input failed

If an action on SAP GUI does nothing, **do not speculate.** There is almost never a "macOS
Open/Save dialog attached to the window" — that exact confabulation has been reported by three
separate sessions and was false every time. Run the preflight; it tells you the real reason:

```bash
bash $SK/tier3_preflight.sh
```

Exit `0` clear · `1` warnings · `2` blocked. It reports, in order:

1. **Frontmost-app policy** — computer-use refuses input based on which app is in front. A
   browser blocks clicks *and* typing; a terminal/IDE blocks typing but *allows* clicks. If
   clicks work and typing doesn't, that asymmetry alone means a terminal/IDE is frontmost —
   it is NOT a dialog, because a modal blocks both.
2. **A SAP popup owning input** — SAP renders dynpro popups ("Information", "Multiple Selection
   for…") as separate windows with `AXModal=false` and no attached sheet, so sheet/modal checks
   report "all clear" while the session is fully blocked. `AXFocusedWindow` is the only reliable
   signal.
3. **Geometry-ambiguous sessions** — multiple sessions open full-screen at identical coordinates.
   A coordinate click lands on the topmost window, not the one you think you're driving.
4. **Retained off-screen dialogs** — SAP leaks dismissed dialog windows (seen climbing 10→22 in
   one session). Usually stale; restart the SAP session if it grows and input misbehaves.

## Rule 2 — use AX, not vision

Reading a screen costs nothing and is exact. Never screenshot SAP GUI to find out what's on it.

```bash
# what's on screen, which buttons exist, is anything blocking
swift $SK/ax_okcode.swift probe "ECD (2)"

# run a transaction (writes the OK-code, presses Enter, verifies the screen changed)
swift $SK/ax_okcode.swift run  "ECD (2)" "/nSE37"

# write the command field without executing
swift $SK/ax_okcode.swift type "ECD (2)" "/nSE16"

# press any button by its accessible name
swift $SK/ax_okcode.swift press "ECD (2)" "Back (F3)"

# clear a blocking popup by taking a named choice
swift $SK/ax_okcode.swift press "Information" "Continue"
```

Always address a session by its **window name** (`ECD (2)`), never coordinates. The script warns
if a name matches more than one window rather than silently picking one.

## What works and what doesn't (measured, don't re-derive)

**Works with SAP in the background:**

- reading the whole screen as text (roles, labels, values)
- writing text via `AXSelectedTextRange` + `AXSelectedText`
- `AXPress` on buttons — including ones that round-trip to the SAP server
- detecting a blocking popup via `AXFocusedWindow`
- selecting/highlighting text **inside input fields**

**Does not work — do not retry these:**

- `AXValue` — settable nowhere. **It reports `.success` and silently discards the write.** This
  is the trap that makes AX look impossible. Always verify a write landed.
- `AXFocused` — accepted and silently discarded; focus is not steerable from outside.
- `CGEvent.postToPid` while SAP is backgrounded — never delivered.
- `AXEnhancedUserInterface` / `AXManualAccessibility` — not implemented by SAP GUI for Java.
- selecting text in `AXStaticText` (ordinary screen content) — readable, not selectable.
- `screencapture` of an occluded SAP window — returns a blank buffer.

## Prefer a cheaper route first

GUI control is the **last** resort. Before driving the GUI, check whether the task can be done:

1. **RFC/BAPI** (`pyrfc`) — headless, deterministic, no GUI at all
2. **OData / sapcli / ADT** — table reads, running reports, dev-object work
3. **This skill (AX)** — when it genuinely needs the GUI
4. **Vision + mouse** — only when AX cannot address the control

For SNOTE specifically, much is reachable over RFC — check before opening the GUI.

## Requirements

macOS + SAP GUI for Java, and Accessibility permission granted to the calling process. The
scripts report unavailability clearly rather than failing obscurely. Sessions must already be
open and logged on; these scripts drive existing sessions, they do not log on.

Full background and the reasoning behind every point above:
`~/Dropbox/Projects/sapgui-computer-use-mcp` (`docs/`, `specs/001-ax-background-control/`).
