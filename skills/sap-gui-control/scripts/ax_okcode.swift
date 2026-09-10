// Drive SAP GUI for Java entirely in the BACKGROUND via the macOS Accessibility
// (AX) API. No screenshots, no coordinates, no keystrokes, no focus stealing —
// the target app never has to come forward.
//
// This exists because coordinate/vision control fails three ways on macOS:
//   1. computer-use refuses input based on which app is frontmost (a browser
//      blocks clicks AND typing; a terminal/IDE blocks typing but allows clicks)
//   2. SAP sessions open full-screen at identical coordinates, so a click lands
//      on whichever window is topmost, not the one you meant
//   3. neither failure is visible on screen, which invites inventing a cause
//
// MEASURED capability map (SAP GUI for Java 8.10rev4). Everything tested:
//   WORKS in the background:
//     - reading the whole UI tree (roles, labels, values) — replaces screenshots
//     - AXFocusedWindow to detect a SAP popup owning input
//     - writing text via AXSelectedTextRange + AXSelectedText
//     - AXPress on buttons, including ones that round-trip to the SAP server
//       (verified: "Create Session" spawned a real new session)
//   DOES NOT WORK:
//     - AXValue is settable nowhere (this is the trap: it silently reports
//       .success and discards the write — use AXSelectedText instead)
//     - AXFocused is accepted and silently discarded; focus is unsteerable
//     - CGEvent.postToPid does not reach the app while it is in the background
//     - AXEnhancedUserInterface / AXManualAccessibility are not implemented
//
//   probe <win>            read-only: command field, buttons, blocking popup
//   type  <win> <text>     write the command field (does NOT execute)
//   run   <win> <text>     write, then press Enter, e.g. run "ECD (2)" "/nSE16"
//   press <win> <button>   AXPress by name, e.g. "Back (F3)"
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
/// SAP labels controls in AXDescription, never AXValue — reading value shows nothing.
func label(_ e: AXUIElement) -> String { s(e, kAXDescriptionAttribute) ?? s(e, kAXTitleAttribute) ?? "" }
func walk(_ e: AXUIElement, _ d: Int = 0, _ f: (AXUIElement) -> Void) {
    if d > 9 { return }
    f(e)
    for c in kids(e) { walk(c, d + 1, f) }
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
let ax = AXUIElementCreateApplication(app.processIdentifier)

func windows() -> [AXUIElement] { attr(ax, kAXWindowsAttribute) as? [AXUIElement] ?? [] }
let matches = windows().filter { (s($0, kAXTitleAttribute) ?? "").contains(want) }
guard let win = matches.first else {
    print("FAIL: no window matching '\(want)'. Have: " +
          windows().map { s($0, kAXTitleAttribute) ?? "?" }.joined(separator: " | ")); exit(3)
}
// Silently picking among identical titles is how you drive the wrong session.
if matches.count > 1 { print("WARN: '\(want)' matched \(matches.count) windows; be more specific.") }
let title = s(win, kAXTitleAttribute) ?? "?"

/// The command toolbar holds, in order: [0] ✓ Enter, [1] show/hide toggle,
/// [2] the command field, [3] Save, [4] Back … Only [2] and [4]+ are labelled,
/// so Enter is addressed positionally as the toolbar's first button.
func commandToolbar() -> [AXUIElement] {
    var tb: AXUIElement?
    walk(win) { e in
        if tb == nil, role(e) == kAXToolbarRole as String,
           kids(e).contains(where: { role($0) == kAXTextFieldRole as String
                                     && label($0).lowercased().contains("command field") }) { tb = e }
    }
    return tb.map { kids($0) } ?? []
}
func commandField() -> AXUIElement? {
    commandToolbar().first { role($0) == kAXTextFieldRole as String
                             && label($0).lowercased().contains("command") }
}
func enterButton() -> AXUIElement? { commandToolbar().first { role($0) == kAXButtonRole as String } }

/// A SAP dynpro popup is a separate AXWindow with AXModal=false and no attached
/// sheet, so sheet/modal checks report all clear while input is fully blocked.
/// AXFocusedWindow is the signal that actually works.
func blockingPopup() -> String? {
    guard let fw = attr(ax, "AXFocusedWindow") else { return nil }
    let owner = s(fw as! AXUIElement, kAXTitleAttribute) ?? "?"
    return owner == title ? nil : owner
}

/// AXValue is NOT settable; selected-text replacement is the write channel.
func write(_ text: String) -> Bool {
    guard let f = commandField() else { return false }
    let n = (attr(f, "AXNumberOfCharacters") as? Int) ?? 0
    var r = CFRange(location: 0, length: n)
    if let rv = AXValueCreate(.cfRange, &r) {
        AXUIElementSetAttributeValue(f, "AXSelectedTextRange" as CFString, rv)
    }
    AXUIElementSetAttributeValue(f, "AXSelectedText" as CFString, text as CFTypeRef)
    usleep(400_000)
    return (s(f, kAXValueAttribute) ?? "") == text
}
func screenText() -> String {
    var out: [String] = []; var n = 0
    walk(win) { e in
        if n < 25, role(e) == "AXStaticText", let v = s(e, kAXValueAttribute), v.count > 2 {
            out.append(v); n += 1 }
    }
    return out.joined(separator: " ¦ ")
}

print("window: [\(title)]")

if mode == "probe" {
    if let p = blockingPopup() { print("BLOCKED: input owned by [\(p)]") }
    print("command field: [\(commandField().flatMap { s($0, kAXValueAttribute) } ?? "<not found>")]")
    print("enter button:  \(enterButton() != nil ? "found" : "MISSING")")
    var n = 0
    walk(win) { e in
        if role(e) == kAXButtonRole as String, !label(e).isEmpty,
           label(e) != "To activate, press the spacebar", n < 10 { n += 1; print("  button: \(label(e))") }
    }
    print("screen: \(screenText().prefix(160))")
    exit(0)
}

if let p = blockingPopup() {
    print("BLOCKED: input is owned by [\(p)], not [\(title)].")
    print("         Dismiss that popup, or target it directly.")
    exit(2)
}

if mode == "press" {
    var b: AXUIElement?
    walk(win) { e in if b == nil, role(e) == kAXButtonRole as String, label(e) == arg { b = e } }
    guard let btn = b else { print("FAIL: no button labelled '\(arg)'"); exit(3) }
    let r = AXUIElementPerformAction(btn, kAXPressAction as CFString)
    print("press [\(arg)] -> \(r == .success ? "success" : "err \(r.rawValue)")")
    exit(r == .success ? 0 : 1)
}

guard write(arg) else { print("FAIL: could not write the command field"); exit(1) }
print("wrote: [\(arg)]")

if mode == "run" {
    guard let b = enterButton() else { print("FAIL: Enter button not found"); exit(3) }
    let before = screenText()
    let r = AXUIElementPerformAction(b, kAXPressAction as CFString)
    usleep(1_500_000)
    let changed = screenText() != before
    print("submit -> \(r == .success ? "ok" : "err")  screenChanged=\(changed)")
    print("screen: \(screenText().prefix(200))")
    if !changed { print("WARN: screen did not change — command may have been rejected."); exit(1) }
}
