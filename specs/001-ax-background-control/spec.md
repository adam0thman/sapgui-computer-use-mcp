# Feature Specification: AX Tier — Background Control of SAP GUI for Java

**Feature Branch**: `001-ax-background-control`

**Created**: 2026-09-10

**Status**: Draft

**Input**: User description: "Add a new AX tier between WebGUI and computer-use to the sapgui-mcp cost ladder: background control of SAP GUI for Java on macOS via the Accessibility API, with no screenshots, no coordinates, no keystrokes and no focus stealing."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read a SAP screen without paying for vision (Priority: P1)

An operator asks the assistant what is currently on a SAP screen, or the assistant needs to
confirm the result of a step it just took. Today the only way to see a SAP GUI for Java screen
is to capture an image and interpret it, which is the single most expensive action in the
system and must be repeated after every step. Instead, the assistant asks the operating system
what the window contains and receives it as structured text.

**Why this priority**: This is the dominant cost in the existing desktop lane and the reason
the lane is avoided. It is also the foundation every other story depends on — you cannot act
reliably on a screen you cannot read. It delivers value alone: even with no ability to *act*,
cheap reliable reading replaces the most expensive part of the current workflow.

**Independent Test**: Ask for the contents of a named open SAP session and confirm the returned
text matches what is on screen, with zero images captured.

**Acceptance Scenarios**:

1. **Given** a named SAP session is open, **When** the assistant requests the screen contents,
   **Then** it receives the visible labels, field values and control names as text, and no image
   is captured or interpreted.
2. **Given** a SAP session showing a data table, **When** the assistant requests screen contents,
   **Then** row and list structure is preserved rather than flattened into one blob.
3. **Given** the operator is working in another application, **When** the assistant reads a SAP
   screen, **Then** the operator's foreground application is unchanged and nothing is raised.

---

### User Story 2 - Complete a SAP task while the operator keeps working (Priority: P2)

The assistant runs a transaction — enters a code, fills fields, presses buttons — while the
operator continues using their machine for something else. Nothing steals focus, no window
jumps forward, and the operator's typing is never intercepted.

**Why this priority**: This is the capability the operator actually asked for, but it depends on
P1 for verification. It removes the two failure modes that make the existing desktop lane
unreliable: refusal of input based on which application happens to be in front, and actions
landing on the wrong window.

**Independent Test**: Start a transaction in a named session while a different application is in
front, and confirm from the screen text afterwards that the transaction ran and the foreground
application never changed.

**Acceptance Scenarios**:

1. **Given** a named SAP session and a different application in the foreground, **When** the
   assistant runs a transaction code, **Then** the session advances to the expected screen and
   the foreground application is still the operator's.
2. **Given** a screen with a named button, **When** the assistant presses it by name, **Then**
   the corresponding SAP action occurs, including actions that require a server round trip.
3. **Given** several SAP sessions open at identical size and position, **When** the assistant
   acts on one by name, **Then** the action affects only that session.
4. **Given** an action that changes data on a production system, **When** it is attempted without
   explicit authorization, **Then** it is refused before anything reaches SAP.

---

### User Story 3 - Never act blind, and never fail silently (Priority: P3)

When something prevents the assistant from acting, it says precisely what — naming the dialog or
window that currently owns input — instead of appearing to succeed, or guessing at a cause.

**Why this priority**: Silent failure is the root cause of the problem this feature exists to
fix. On two occasions an assistant reported an imaginary blocking dialog after an action quietly
did nothing. Correctness of the *failure* path is what makes the tier trustworthy enough to use
unattended; without it the other stories produce confident wrong answers.

**Independent Test**: Open a SAP dialog that takes over input, attempt an action, and confirm the
refusal names that dialog and that nothing was written.

**Acceptance Scenarios**:

1. **Given** a SAP dialog owns input, **When** any write or submit is attempted, **Then** it is
   refused, the refusal names the window that owns input, and the target screen is unmodified.
2. **Given** a write is attempted, **When** the value does not actually reach the field, **Then**
   the attempt reports failure rather than success.
3. **Given** a requested window name matches more than one open window, **When** an action is
   requested, **Then** the ambiguity is reported rather than silently resolved.
4. **Given** a blocking dialog is present, **When** the operator asks to dismiss it, **Then** its
   message and available choices can be read and a named choice taken.

---

### Edge Cases

- A dialog appears *between* reading the screen and acting on it — the action must not proceed
  on stale assumptions.
- The SAP session disconnects mid-task, replacing the screen with a reconnect or logon screen.
- The named session is closed by the operator while a task is in progress.
- SAP GUI is not running at all, or the requested session name does not exist.
- The assistant lacks the operating-system permission required to inspect or control other
  applications.
- A control cannot be identified because it carries no name.
- The operator is actively typing into the same session the assistant is driving.
- The application has been running long enough to accumulate large numbers of dismissed dialogs,
  slowing inspection.

## Requirements *(mandatory)*

### Functional Requirements

**Reading**

- **FR-001**: System MUST return the contents of a named SAP session window as structured text,
  including control names, field values and visible labels, without capturing any image.
- **FR-002**: System MUST preserve table and list structure when present, rather than returning
  undifferentiated text.
- **FR-003**: System MUST identify controls by their accessible name, and MUST report a control
  as unnamed rather than inventing an identity for it.

**Acting**

- **FR-004**: System MUST write text into an identified input field of a named session.
- **FR-005**: System MUST verify after every write that the value actually reached the field, and
  MUST report failure when it did not.
- **FR-006**: System MUST press a control identified by name, including controls whose effect
  requires a server round trip.
- **FR-007**: System MUST submit an entered command and report whether the screen changed as a
  result.
- **FR-008**: System MUST support selecting a range of text within an input field and reading the
  selected text back.
- **FR-009**: System MUST NOT require the SAP application to be the foreground application for any
  read or action.
- **FR-010**: System MUST NOT change which application is in the foreground.

**Targeting**

- **FR-011**: System MUST address a session by name, and MUST affect only the named session.
- **FR-012**: System MUST report ambiguity when a name matches multiple windows, rather than
  choosing one.

**Blocking and failure**

- **FR-013**: System MUST detect when a dialog owns input for the target session, including
  dialogs that are separate windows and are not marked modal by the operating system.
- **FR-014**: System MUST refuse writes and submits while input is owned elsewhere, and MUST name
  the owning window in the refusal.
- **FR-015**: System MUST allow reading a blocking dialog's message and available choices, and
  taking a named choice, so the block can be cleared.
- **FR-016**: System MUST distinguish "action was refused" from "action was performed and had no
  effect", and MUST never report success for an action that did nothing.
- **FR-017**: System MUST report a diagnosable reason for every failure — never a bare failure
  that invites the caller to guess a cause.

**Integration**

- **FR-018**: System MUST expose these capabilities as a tier within the existing cost ladder,
  ranked cheaper than the image-based desktop tier and more expensive than headless API tiers.
- **FR-019**: System MUST be selectable through the existing routing and capability-catalog
  mechanism, and MUST participate in fallback when it cannot handle a task.
- **FR-020**: System MUST apply the existing production-write protection before any action that
  changes SAP state.
- **FR-021**: System MUST report which tier serviced a request and why, consistent with existing
  tiers.
- **FR-022**: System MUST declare itself unavailable, rather than failing at use time, when the
  platform, the application, or the required permission is absent.

### Key Entities

- **Session**: One SAP session the operator has open, addressed by its visible name. Several may
  exist at once, at identical size and position.
- **Screen snapshot**: The readable contents of a session at a moment — labels, field values,
  control names, and table structure.
- **Control**: An addressable element of a screen — an input field or a named button.
- **Blocking dialog**: A window that currently owns input for a session, carrying a message and a
  set of named choices.
- **Capability record**: The existing catalog entry describing how a task can be performed and by
  which tier, extended to record this tier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Reading a SAP screen consumes no image capture or interpretation — the per-read
  cost is text only.
- **SC-002**: An operator can continue using their machine uninterrupted for the full duration of
  an assistant-driven SAP task; the foreground application never changes.
- **SC-003**: 100% of actions affect only the named session, verified with multiple sessions open
  at identical size and position.
- **SC-004**: When input is blocked, 100% of attempts are refused with the blocking window named,
  and 0% write partial data to the target screen.
- **SC-005**: No action reports success unless its effect was verified; zero false-success reports
  across the acceptance suite.
- **SC-006**: A multi-step task that previously required one image capture per step completes
  with the same end state and zero image captures.
- **SC-007**: Every failure returned identifies its cause specifically enough to act on, with no
  case requiring the caller to infer why.

## Assumptions

- **Platform**: macOS with SAP GUI for Java. The equivalent capability for SAP GUI for Windows is
  out of scope for this feature; that client exposes a different automation surface.
- **Permission**: The host process has been granted the operating-system permission required to
  inspect and control other applications. Absence is reported as unavailability (FR-022), not
  as a task failure.
- **Session ownership**: The operator already has SAP sessions open and authenticated. This
  feature drives existing sessions; it does not log on.
- **Tier ranking**: This tier is preferred over the image-based desktop tier whenever a suitable
  session is open, because it is cheaper and deterministic. It remains below headless API tiers,
  which stay preferred when a task can be done without a GUI at all.
- **Ranking vs. the browser tier**: Preferred over the browser tier when a Java session is
  already open, since it reuses the operator's authenticated session and needs no browser.
- **Reading is safe**: Reading a screen is treated as non-mutating and is not subject to the
  production-write protection; writes and submits are.
- **Text selection scope**: Selecting text applies to input fields. Static screen text is
  readable but not selectable — a platform limitation, not a gap to close.
- **Unnamed controls**: A small number of controls carry no accessible name and must be addressed
  by their position within their container. This is accepted, and such addressing is expected to
  be documented where used rather than spread implicitly through the code.
- **Existing reference**: Working reference implementations exist at `scripts/ax_okcode.swift`
  and `scripts/tier3_preflight.sh` and establish feasibility of every requirement above.
