// Tier-2.5: drive SAP GUI for Java via Accessibility + targeted key events.
//
// Coordinate/vision control fails three ways on macOS: the frontmost-app tier
// policy refuses input, sessions sharing geometry make clicks land on the wrong
// window, and neither failure is visible on screen. This path avoids all three.
//
// SAP GUI for Java exposes NO settable AXValue, so text cannot be written
// directly. What it does expose is settable AXFocused on every field and AXPress
// on every button. So: focus the target element by name inside ONE named window,
// then post key events straight to the process with CGEvent.postToPid — which
// does not require the app to be frontmost.
//
//   probe <win>            read-only: list the command field + named buttons
//   type  <win> <text>     focus command field, type, DO NOT execute
//   run   <win> <text>     ...then press Enter (EXECUTES, e.g. "/nSE37")
//   press <win> <button>   AXPress a button by name, e.g. "Back (F3)"
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
AXUIElementSetAttributeValue(cf, kAXFocusedAttribute as CFString, kCFBooleanTrue)
usleep(150_000)
let focused = (attr(cf, kAXFocusedAttribute) as? Bool) ?? false
print("focus set: \(focused)")

post(arg, pid: pid)
usleep(250_000)
print("after type: field=[\(s(cf, kAXValueAttribute) ?? "")]")

if mode == "run" {
    postKey(36, pid: pid)   // Return
    usleep(400_000)
    print("executed; window now [\(s(win, kAXTitleAttribute) ?? "?")]")
}
