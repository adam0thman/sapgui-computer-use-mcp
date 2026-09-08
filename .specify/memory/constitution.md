# sapgui-mcp Constitution

The governing principles for this project. Every spec, plan, task and
implementation produced by the `/speckit-*` workflow must comply with these.
Where this document and a generated artifact disagree, this document wins.

## Core Principles

### I. Cheapest Tier That Can Do The Job (NON-NEGOTIABLE)

Every capability is placed on the cost ladder and routed to the cheapest tier that
can perform it:

```
Tier 0 API (RFC/OData/sapcli) → 1 recorded script → 2 WebGUI → 3 computer-use
      ~free, deterministic                                      expensive, vision
```

- Vision loops (Tier 3) are the fuel of last resort, never the default.
- **Tier selection must itself be free** — a catalog lookup, never a discovery loop.
  Paying vision cost merely to decide not to use vision is a defect.
- A cache miss may probe **once**; the answer is written back and never re-paid.
- Anything routine that had to be done in Tier 2/3 is a candidate for promotion to
  Tier 1 so the next run is near-free.

### II. Programmatic Over Screen-Driving

Prefer CLI/API/SDK/HTTP over anything that drives a GUI or takes over the screen —
`gh` over a browser, `git` over a Git GUI, RFC/OData over SAP GUI. Computer-use is
acceptable only when no programmatic route exists, and must be flagged explicitly
before use. This applies to how we *build* the project, not only what it does.

### III. Test-First, Positive AND Negative (NON-NEGOTIABLE)

- Tests precede implementation; red → green → refactor.
- Every feature ships **both** a positive test (the happy path returns the expected
  structured result) and negative tests (bad input, missing auth, locked object,
  dropped session, prod guard, broken UI) proving it fails *gracefully and correctly*:
  right typed error, `mutated=false` on failure, no partial commit.
- Unit tests are hermetic and mock the backends. Anything touching real SAP is an
  opt-in `@integration` test.
- Minimum 80% coverage on changed modules.

### IV. Honest Results

- `Result` reports which tier ran and why; a fallback is logged, never hidden.
- `mutated` is set truthfully; write paths honour `dry_run`.
- A failure is reported as a failure, with its output. Never claim a step passed,
  was verified, or was live-tested when it was not. "Code complete" and
  "verified against a real system" are different claims and must be stated separately.

### V. Safety Boundaries Are Not Routable

- **Production writes are refused** unless explicitly authorized in-conversation.
  The guard runs before any tier executes and before any probe cost. No tier
  selection, constraint, or convenience may relax it.
- Credentials come **only** from `creds exec`. Nothing secret is ever written to the
  repo, the capability catalog, logs, or the conversation.
- Input reaching a query/WHERE clause is validated at the boundary — rejected, not
  escaped.
- Never silently swallow an error; log it or surface it.

### VI. Laziness With Comprehension

Simplest thing that works: no interface with one implementation, no abstraction
before the second use, no config for a value that never changes. Deletion beats
addition; boring beats clever.

But laziness shortens the *solution*, never the *understanding*. Read the whole flow
before choosing an approach. A small diff in the wrong place is a second bug, not a
win. Deliberate corner-cuts with a known ceiling get a comment naming the ceiling
and the upgrade path.

## Platform Constraints

These are properties of SAP, not choices, and specs must not assume them away:

- **SAP GUI for Java (macOS/Linux) has no external live-attach.** COM scripting is
  Windows-only. Interactive control of the Java desktop is possible only via Tier 3
  (vision), or non-interactively via `GuiStartS.jar` scripts (Tier 1).
- **SAP GUI for Windows** exposes the full COM Scripting API (`findById`) — precise,
  but Windows-only.
- **S/4HANA Cloud blocks RFC/BAPI/IDoc** — Tier 0 there means OData/REST only.
- Tier 0 opens its own headless connection, which is *not* the user's live GUI
  session. Tasks needing live-session context must set `must_stay_in_live_session`.
- Backend capability is asymmetric by design. Tier 0/1/2 return structured data;
  Tier 3 is coarser with screenshot evidence. Do not build abstractions that pretend
  the tiers are equivalent.

## Development Workflow & Quality Gates

Every task follows: **develop → test (positive) → test (negative) → verify against a
real non-prod system → fix → re-test → re-verify.**

Definition of Done — all must hold before a task closes:

- [ ] Positive tests pass.
- [ ] Negative tests pass (each applicable failure mode has a test).
- [ ] Verified against a real non-prod system, or explicitly marked N/A with a reason.
- [ ] Coverage ≥ 80% on changed modules.
- [ ] `ruff` clean; `mypy --strict` clean.
- [ ] Router reports correct tier and reason on every path.
- [ ] `mutated` correct; write paths honour `dry_run` and the prod guard.
- [ ] No secret in code, catalog, or logs.
- [ ] Code review pass; CRITICAL/HIGH resolved.

Testing safety: real-system tests use a **non-prod** `creds` id only. Production is
never in the automated suite. Negative tests never run destructive operations
against production.

## Governance

This constitution supersedes other practices. Amendments require an explicit change
here with a version bump and a note of what changed and why.

Generated specs, plans and tasks are proposals — they do not override these
principles. `/speckit-analyze` should flag any artifact that conflicts with this
document. Complexity must be justified against Principle VI; an unjustified
abstraction is a review blocker.

Design detail lives in `docs/01-architecture.md`; milestone and test criteria live in
`docs/02-roadmap.md`. Those describe *how*; this document constrains *what is allowed*.

**Version**: 1.0.0 | **Ratified**: 2026-09-08 | **Last Amended**: 2026-09-08
