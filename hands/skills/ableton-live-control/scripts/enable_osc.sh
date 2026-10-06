#!/usr/bin/env bash
# enable_osc.sh - Select "AbletonOSC" as a Control Surface in Live's Settings so
# the OSC server starts. This is the ONE setup step that needs GUI automation,
# because Live's Control Surface chooser is a custom-drawn list (not a native
# AXMenu the accessibility API can select from). Once selected, the choice
# PERSISTS across Live restarts, so this is normally a one-time action.
#
# Usage: bash enable_osc.sh [ROW]      (ROW defaults to 2)
#
# PRECONDITIONS (the caller/agent must set these up first):
#   1. Live is running (ideally on the virtual display).
#   2. The Settings window is OPEN and on the "Link/Tempo/MIDI" page, showing the
#      Control Surfaces table. (Live menu -> Settings...  -> Link/Tempo/MIDI.)
#   3. cliclick is installed (brew install cliclick).
#
# SAFETY:
#   * Row 1 is frequently a real hardware controller. NEVER pass ROW=1 unless you
#     have visually confirmed row 1 reads "None". Default ROW=2.
#   * Pixel offsets below are tuned for a 2x (Retina) display at Live's default UI
#     zoom. On a different scale they may be off; verify with a screenshot and
#     adjust OFF_* / ROW_PITCH, or select the item manually.
#   * After running, ALWAYS verify with a screenshot that the intended row (and
#     only that row) now shows "AbletonOSC".
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROW="${1:-2}"

# already up?
if [ "$(python3 "$DIR/live.py" --timeout 1.5 /live/test 2>/dev/null)" = "ok" ]; then
  echo "AbletonOSC already responding - nothing to do."
  exit 0
fi

command -v cliclick >/dev/null 2>&1 || { echo "ERROR: cliclick not installed (brew install cliclick)"; exit 1; }

# read Settings window origin (global logical coords)
read -r WX WY < <(osascript <<'AS'
tell application "System Events" to tell process "Live"
  set p to position of window "Settings"
  return (item 1 of p as text) & " " & (item 2 of p as text)
end tell
AS
) || { echo "ERROR: Settings window not found. Open Live -> Settings -> Link/Tempo/MIDI first."; exit 1; }

# offsets (logical points) from Settings window top-left to row-1 Control Surface dropdown center
OFF_X=217
OFF_Y=198
ROW_PITCH=15          # vertical spacing between rows
ITEM_DX=-15           # AbletonOSC list item offset from the dropdown, x
ITEM_DY=31            # ...and y (AbletonOSC is the 2nd item: None, AbletonOSC, ...)

DROP_X=$(( WX + OFF_X ))
DROP_Y=$(( WY + OFF_Y + ROW_PITCH * (ROW - 1) ))
ITEM_X=$(( DROP_X + ITEM_DX ))
ITEM_Y=$(( DROP_Y + ITEM_DY ))

echo "Settings window at ($WX,$WY). Row $ROW dropdown -> ($DROP_X,$DROP_Y); AbletonOSC item -> ($ITEM_X,$ITEM_Y)."

# From here on we drive the physical pointer, so this is a cursor takeover.
# Deterministically return the cursor to the center of the primary physical
# display on EVERY exit path (success, failure, or signal) -- the agent never
# has to remember to park it. Armed only now, so the early "already up" /
# "cliclick missing" exits above do not move the user's pointer needlessly.
PARK="$HOME/.agents/skills/virtual-display/scripts/park-cursor.sh"
trap 'bash "$PARK" >/dev/null 2>&1 || true' EXIT

osascript -e 'tell application "Live" to activate' >/dev/null 2>&1 || true
sleep 0.3
osascript -e 'tell application "System Events" to tell process "Live" to perform action "AXRaise" of window "Settings"' >/dev/null 2>&1 || true
sleep 0.3

cliclick "c:${DROP_X},${DROP_Y}"     # open the dropdown
sleep 0.7
cliclick "c:${ITEM_X},${ITEM_Y}"     # click the AbletonOSC item
sleep 1.2

if [ "$(python3 "$DIR/live.py" --timeout 2 /live/test 2>/dev/null)" = "ok" ]; then
  echo "SUCCESS: AbletonOSC is now responding on UDP 11000/11001."
  echo "Verify with a screenshot that row $ROW shows 'AbletonOSC' and row 1 is unchanged."
  exit 0
else
  echo "AbletonOSC did not come up. Likely the pixel offsets are off for this UI scale."
  echo "Take a cropped screenshot of the Control Surfaces table, then select AbletonOSC"
  echo "manually (open row $ROW's Control Surface dropdown, pick 'AbletonOSC')."
  exit 1
fi
