#!/usr/bin/env bash
# Tier-3 (computer-use) preflight for SAP GUI for Java on macOS.
#
# Answers ONE question before any click/type is attempted:
#   "If input fails right now, why?"
#
# It exists because a failed synthetic click/type on macOS gives no visible cause,
# which invites the agent to invent one ("a dialog must be blocking it"). Every
# check below is read-only — nothing is clicked, typed, focused, or raised.
set -uo pipefail

APP="${1:-SAPGUI}"
verdict=0   # 0=ok 1=warn 2=block

say()   { printf '%s\n' "$*"; }
block() { printf 'BLOCK  %s\n' "$*"; verdict=2; }
warn()  { printf 'WARN   %s\n' "$*"; [ "$verdict" -lt 1 ] && verdict=1; return 0; }
ok()    { printf 'ok     %s\n' "$*"; }

say "=== Tier-3 preflight: $APP ==="

# ---------------------------------------------------------------- 1. frontmost
# computer-use enforces a frontmost-app tier check. Browsers are tier "read"
# (clicks AND typing refused); terminals/IDEs are tier "click" (typing refused).
# When one of those is in front, input is blocked by POLICY with nothing visible
# on screen to explain it. This is the most common invisible blocker.
front=$(osascript -e 'tell application "System Events" to get name of first process whose frontmost is true' 2>/dev/null)
case "$front" in
  Safari|"Google Chrome"|Firefox|"Microsoft Edge"|Arc|Brave*|Chromium)
    block "frontmost is '$front' (browser = tier 'read'): clicks AND typing are refused" ;;
  Terminal|iTerm*|"Visual Studio Code"|Code|*JetBrains*|IntelliJ*|PyCharm*|Warp|Ghostty|Alacritty|kitty)
    block "frontmost is '$front' (terminal/IDE = tier 'click'): typing is refused" ;;
  "$APP")
    ok "frontmost is '$APP'" ;;
  *)
    warn "frontmost is '$front', not '$APP' — input will go to that app, not SAP" ;;
esac

# ------------------------------------------------------- 2. real modal blockers
# A genuine attached sheet or modal window legitimately blocks the parent.
sheets=$(osascript -e "with timeout of 15 seconds
tell application \"System Events\" to tell process \"$APP\"
set n to 0
set m to 0
repeat with w in windows
try
set n to n + (count of sheets of w)
end try
try
if (value of attribute \"AXModal\" of w) is true then set m to m + 1
end try
end repeat
return (n as text) & \" \" & (m as text)
end tell
end timeout" 2>/dev/null)
nsheet=$(echo "$sheets" | awk '{print $1+0}')
nmodal=$(echo "$sheets" | awk '{print $2+0}')
if [ "${nsheet:-0}" -gt 0 ]; then
  block "$nsheet attached sheet(s) — a real dialog owns input; dismiss it first"
elif [ "${nmodal:-0}" -gt 0 ]; then
  block "$nmodal modal window(s) — dismiss before driving the session"
else
  ok "no attached sheets, no modal windows"
fi

# ------------------------------------------------------ 3. AX-visible windows
axwins=$(osascript -e "with timeout of 15 seconds
tell application \"System Events\" to tell process \"$APP\"
set o to \"\"
repeat with w in windows
try
set o to o & (name of w) & \"|\"
end try
end repeat
return o
end tell
end timeout" 2>/dev/null)
say "       AX windows: ${axwins:-<none>}"

# --------------------------------------- 4. off-screen dialog graveyard (Java)
# Swing retains dismissed dialogs; the window server still lists them while the
# AX API does not. Stale ones are harmless, but a LIVE unrendered modal swallows
# all input while the screenshot looks perfectly normal — the real "invisible
# dialog" failure mode. A high count means SAP dialogs are not being reaped.
tmp=$(mktemp -t wins).swift
cat > "$tmp" <<'SWIFT'
import CoreGraphics
import Foundation
let app = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "SAPGUI"
guard let list = CGWindowListCopyWindowInfo(CGWindowListOption(arrayLiteral: .optionAll),
                                            kCGNullWindowID) as? [[String: Any]] else { exit(0) }
for w in list {
  guard (w[kCGWindowOwnerName as String] as? String) == app else { continue }
  guard let name = w[kCGWindowName as String] as? String, !name.isEmpty else { continue }
  let on = w[kCGWindowIsOnscreen as String] as? Bool ?? false
  if !on { print(name) }
}
SWIFT
if command -v swift >/dev/null 2>&1; then
  offscreen=$(swift "$tmp" "$APP" 2>/dev/null | sort | uniq -c | sort -rn)
  n=$(printf '%s\n' "$offscreen" | grep -c . || true)
  if [ "${n:-0}" -gt 0 ]; then
    warn "$n off-screen $APP dialog window(s) retained (invisible to AX):"
    printf '%s\n' "$offscreen" | sed 's/^/         /'
    say  "         -> stale unless input is also failing; if it is, one may be a live"
    say  "            unrendered modal. Restart the SAP GUI session to clear them."
  else
    ok "no off-screen dialog windows"
  fi
else
  warn "swift unavailable — skipped off-screen window scan"
fi
rm -f "$tmp"

# ------------------------------------- 5. ambiguous stacked sessions (targeting)
# Multiple SAP sessions open full-screen at identical coordinates are
# indistinguishable to a coordinate click: input lands on whichever is TOPMOST,
# not on the session the agent believes it is driving. It then screenshots the
# intended window, sees no change, and concludes "typing is blocked".
geo=$(osascript -e "with timeout of 15 seconds
tell application \"System Events\" to tell process \"$APP\"
set o to \"\"
repeat with w in windows
try
set o to o & (name of w) & tab & ((value of attribute \"AXPosition\" of w) as text) & \"x\" & ((value of attribute \"AXSize\" of w) as text) & linefeed
end try
end repeat
return o
end tell
end timeout" 2>/dev/null)
dupes=$(printf '%s\n' "$geo" | grep -c . >/dev/null 2>&1; printf '%s\n' "$geo" | awk -F'\t' 'NF>1{c[$2]++} END{n=0; for(k in c) if(c[k]>1) n++; print n+0}')
if [ "${dupes:-0}" -gt 0 ]; then
  top=$(printf '%s\n' "$geo" | head -1 | cut -f1)
  warn "$dupes group(s) of windows share identical geometry — coordinate input is ambiguous"
  printf '%s\n' "$geo" | grep . | sed 's/^/         /'
  say  "         -> topmost (receives input): [$top]"
  say  "            Target by window, not coordinates, or close the extra sessions."
else
  ok "no geometry-ambiguous windows"
fi

say "=== verdict: $([ $verdict -eq 0 ] && echo CLEAR || { [ $verdict -eq 1 ] && echo 'CLEAR-WITH-WARNINGS' || echo BLOCKED; }) ==="
exit $verdict
