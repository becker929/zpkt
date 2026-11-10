#!/usr/bin/env bash
# doctor.sh - One-shot, non-destructive preflight for driving Ableton Live.
# Replaces the scattered manual checks (is Live up? which surfaces? OSC? MCP?
# cliclick? where's the window?) with a single deterministic report, so an agent
# knows its exact starting state before doing anything.
#
# Usage: bash doctor.sh
# Exit:  0 if at least one control path (MCP or OSC) is usable; 1 otherwise.
# Path B (MCP, TCP 16619) is the primary path; AbletonOSC (Path A) is optional.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANDS="$(cd "$DIR/../../.." && pwd)"
OK="  [ok]  "; NO="  [--]  "; WARN="  [??]  "

pass_osc=0; pass_mcp=0

echo "== Ableton control doctor =="

# 1) Live process
if pgrep -x Live >/dev/null 2>&1; then
  echo "${OK}Live process running (pid $(pgrep -x Live | head -n1))"
else
  echo "${NO}Live process NOT running  -> open a set: open -a 'Ableton Live 12 Suite' <set.als>"
fi

# 2) MCP reachable (Path B, TCP 16619) -- primary control path
if nc -z 127.0.0.1 16619 2>/dev/null; then
  if [ "$(uv run --quiet --project "$HANDS" hands live exec --timeout 5 --json 'result = 1 + 1' 2>/dev/null)" = "2" ]; then
    echo "${OK}Path B MCP reachable (TCP 16619); LOM round-trip OK"; pass_mcp=1
  else
    echo "${WARN}Path B port open but bridge not answering (surface wedged?)"
  fi
else
  echo "${NO}Path B MCP not listening  -> select AbletonLiveMCP control surface"
fi

# 3) AbletonOSC remote script installed on disk (optional)
OSC_DEST="$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC"
osc_installed=0
if [ -d "$OSC_DEST" ]; then
  echo "${OK}AbletonOSC installed ($OSC_DEST)"; osc_installed=1
elif [ $pass_mcp -eq 1 ]; then
  echo "${NO}AbletonOSC optional, not installed"
else
  echo "${NO}AbletonOSC not installed  -> bash $DIR/install_abletonosc.sh"
fi

# 4) OSC reachable (Path A, UDP 11000/11001; optional)
if [ "$(python3 "$DIR/live.py" --timeout 1.5 /live/test 2>/dev/null)" = "ok" ]; then
  echo "${OK}Path A OSC reachable (UDP 11000/11001)"; pass_osc=1
elif [ $osc_installed -eq 0 ]; then
  echo "${NO}Path A OSC skipped (AbletonOSC not installed)"
elif [ $pass_mcp -eq 1 ]; then
  echo "${NO}Path A OSC not answering (optional; surface not selected)"
else
  echo "${NO}Path A OSC not answering  -> enable surface in a free row: bash $DIR/enable_osc.sh <ROW>"
fi

# 5) cliclick (needed only for the one-time GUI enable / export)
if command -v cliclick >/dev/null 2>&1; then
  echo "${OK}cliclick present ($(command -v cliclick))"
else
  echo "${WARN}cliclick missing (only needed for GUI steps)  -> brew install cliclick"
fi

# 6) Where is Live's main window? (physical-display safety check)
if pgrep -x Live >/dev/null 2>&1; then
  POS="$(timeout 8 osascript <<'AS' 2>/dev/null || true
with timeout of 5 seconds
  tell application "System Events" to tell process "Live"
    try
      set w to window 1
      set p to position of w
      return ((item 1 of p) as text) & "," & ((item 2 of p) as text) & " :: " & (name of w as text)
    on error
      return "unknown"
    end try
  end tell
end timeout
AS
)"
  echo "${WARN}front window pos/name: ${POS:-unknown}  (x<0 or off-canvas = off-screen; small x = physical display)"

  # 7) Any blocking modal right now?
  MODAL="$(timeout 12 bash "$DIR/dismiss_modals.sh" 2>/dev/null | head -n1 || true)"
  if [ "$MODAL" = "No modal dialogs present." ]; then
    echo "${OK}No blocking modal dialogs"
  else
    echo "${WARN}Modal present: ${MODAL}  -> bash $DIR/dismiss_modals.sh --reap"
  fi
fi

echo "----"
if [ $pass_osc -eq 1 ] || [ $pass_mcp -eq 1 ]; then
  echo "READY: Path B (MCP, primary)=$([ $pass_mcp -eq 1 ] && echo up || echo down), Path A (OSC, optional)=$([ $pass_osc -eq 1 ] && echo up || echo down)"
  exit 0
else
  echo "NOT READY: no control path is up. See the arrows above."
  exit 1
fi
