// Tier-2.5: drive SAP GUI for Java through the macOS Accessibility (AX) API.
//
// MEASURED capability map (SAP GUI for Java 8.10rev4, 312 elements scanned).
// Everything below was tested, not assumed:
//
//   WORKS with the app in the BACKGROUND (no frontmost, no coordinates, no vision):
//     - reading the whole UI tree: roles, labels, values, geometry
//     - AXFocusedWindow to detect a SAP popup owning input
//     - AXRaise on a specific window  -> unambiguous session targeting
//     - AXMain is settable
//     - AXPress on any button        -> real write capability
//
//   DOES NOT WORK:
//     - AXValue is settable NOWHERE, so text cannot be written via AX
//     - AXFocused is accepted and SILENTLY DISCARDED (IsAttributeSettable says
//       true, the set returns .success, focus never moves) - focus is unsteerable
//     - CGEvent.postToPid does NOT reach the app while it is in the background;
//       a full scan of every field showed no delivery. Keystrokes require the app
//       to be genuinely frontmost.
//
// Net: BUTTONS yes, TEXT no. Navigation and state-reading are free and robust;
// text entry still needs SAP GUI frontmost and is the one fragile step left.
//
//   probe <win>            read-only: command field + named buttons
//   press <win> <button>   AXPress by name, e.g. "Back (F3)" - background-safe
//   type  <win> <text>     type into the command field - REQUIRES frontmost
//   run   <win> <text>     ...then Enter (EXECUTES, e.g. "/nSE37")
//
import AppKit
import ApplicationServices

func attr(_ e: AXUIElement, _ a: String) -> CFTypeRef? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, a as CFString, &v) == .success ? v : nil
}
func s(_ e: AXUIElement, _ a: String) -> String? { attr(e, a) as? String }
func kids(_ e: AXUIElement) -> [AXUIElement] { attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? [] }
func role(_ e: AXUIElement) -> String { s(e, kAXRoleAttribute) ?? "?" }
/// SAP labels controls in AXDescription, not AXValue — reading value shows nothing.
func label(_ e: AXUIElement) -> String { s(e, kAXDescriptionAttribute) ?? s(e, kAXTitleAttribute) ?? "" }

func walk(_ e: AXUIElement, _ d: Int = 0, _ f: (AXUIElement, Int) -> Void) {
    if d > 8 { return }
    f(e, d)
    for c in kids(e) { walk(c, d + 1, f) }
}
func find(_ root: AXUIElement, role wantRole: String, label wantLabel: String) -> AXUIElement? {
    var hit: AXUIElement?
    walk(root) { e, _ in
        if hit == nil, role(e) == wantRole, label(e).caseInsensitiveCompare(wantLabel) == .orderedSame { hit = e }
    }
    return hit
}

/// Key events go to the pid, not to whatever happens to be frontmost.
func post(_ text: String, pid: pid_t) {
    let src = CGEventSource(stateID: .privateState)
    var u = Array(text.utf16)
    for down in [true, false] {
        guard let e = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: down) else { continue }
        e.keyboardSetUnicodeString(stringLength: u.count, unicodeString: &u)
        e.postToPid(pid)
    }
}
func postKey(_ code: CGKeyCode, pid: pid_t) {
    let src = CGEventSource(stateID: .privateState)
    for down in [true, false] {
        CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: down)?.postToPid(pid)
    }
}

let a = CommandLine.arguments
guard a.count >= 3 else {
    FileHandle.standardError.write("usage: probe|type|run|press <window-substring> [text|button]\n".data(using: .utf8)!)
    exit(64)
}
let mode = a[1], want = a[2], arg = a.count > 3 ? a[3] : ""

guard AXIsProcessTrusted() else { print("FAIL: not trusted for Accessibility"); exit(3) }
guard let app = NSWorkspace.shared.runningApplications.first(where: { $0.localizedName == "SAPGUI" })
else { print("FAIL: SAPGUI not running"); exit(3) }
let pid = app.processIdentifier
let axApp = AXUIElementCreateApplication(pid)
let wins = attr(axApp, kAXWindowsAttribute) as? [AXUIElement] ?? []
let matches = wins.filter { (s($0, kAXTitleAttribute) ?? "").contains(want) }
guard let win = matches.first else {
    print("FAIL: no window matching '\(want)'. Have: " +
          wins.map { s($0, kAXTitleAttribute) ?? "?" }.joined(separator: " | ")); exit(3)
}
// Ambiguity is the bug that makes agents drive the wrong session — never pick silently.
if matches.count > 1 { print("WARN: '\(want)' matched \(matches.count) windows; be more specific.") }
print("window: [\(s(win, kAXTitleAttribute) ?? "?")]  pid=\(pid)")

if mode == "probe" {
    guard let cf = find(win, role: kAXTextFieldRole as String, label: "command field") else {
        print("FAIL: command field not found"); exit(3)
    }
    var f: DarwinBoolean = false
    AXUIElementIsAttributeSettable(cf, kAXFocusedAttribute as CFString, &f)
    print("command field: value=[\(s(cf, kAXValueAttribute) ?? "")] focusable=\(f.boolValue)")
    var n = 0
    walk(win) { e, _ in
        if role(e) == kAXButtonRole as String, !label(e).isEmpty, n < 12 { n += 1; print("  button: \(label(e))") }
    }
    exit(0)
}

if mode == "press" {
    guard let b = find(win, role: kAXButtonRole as String, label: arg) else {
        print("FAIL: no button labelled '\(arg)'"); exit(3)
    }
    let r = AXUIElementPerformAction(b, kAXPressAction as CFString)
    print("press [\(arg)] -> \(r == .success ? "success" : "error \(r.rawValue)")")
    exit(r == .success ? 0 : 1)
}


// A SAP dynpro popup is a separate AXWindow with AXModal=false, so "no modal"
// checks miss it while it holds all input. Typing anyway silently does nothing —
// which is precisely what invites "some invisible dialog must be blocking me".
// Refuse, and name the window that actually owns input.
if let fw = attr(axApp, "AXFocusedWindow") {
    let owner = s(fw as! AXUIElement, kAXTitleAttribute) ?? "?"
    let target = s(win, kAXTitleAttribute) ?? "?"
    if owner != target {
        print("BLOCKED: input is owned by [\(owner)], not [\(target)].")
        print("         Dismiss that popup, or target it directly with `press`.")
        exit(2)
    }
}

guard let cf = find(win, role: kAXTextFieldRole as String, label: "command field") else {
    print("FAIL: command field not found"); exit(3)
}
// SAP GUI for Java ACCEPTS AXFocused writes and silently discards them:
// IsAttributeSettable reports true, the set returns .success, focus never moves.
// So focus cannot be steered via AX. What does work is AXRaise on the specific
// window (unambiguous targeting even when sessions share geometry) followed by
// key events posted to the pid — which land without the app being frontmost.
let raised = AXUIElementPerformAction(win, kAXRaiseAction as CFString) == .success
print("raise: \(raised)")
// Keystrokes are dropped unless the app is genuinely frontmost - verified by
// scanning every field after a background post and finding no change anywhere.
NSWorkspace.shared.runningApplications.first { $0.processIdentifier == pid }?.activate(options: [])
usleep(900_000)
let fm = NSWorkspace.shared.frontmostApplication?.localizedName ?? "?"
if fm != "SAPGUI" {
    print("WARN: frontmost is [\(fm)], not SAPGUI - keystrokes will be dropped.")
}

let before = s(cf, kAXValueAttribute) ?? ""
post(arg, pid: pid)
usleep(500_000)
let after = s(cf, kAXValueAttribute) ?? ""
print("type: before=[\(before)] after=[\(after)] delivered=\(after.contains(arg))")

// Keystrokes land wherever SAP's own focus already sits. That is usually the
// command field, but it is NOT selectable from outside — verify, never assume.
if !after.contains(arg) {
    print("WARN: text did not reach the command field; SAP focus is elsewhere.")
    exit(1)
}

if mode == "run" {
    postKey(36, pid: pid)   // Return
    usleep(400_000)
    print("executed; window now [\(s(win, kAXTitleAttribute) ?? "?")]")
}
