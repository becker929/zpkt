#!/bin/bash
# Open a GUI app DIRECTLY on the virtual display with no flash on the user's screen.
#
# How it works: the app is launched hidden and in the background (`open -gj`), so
# its window is never drawn. While still hidden, its window is moved onto the
# virtual display; only then is the app revealed. The window therefore appears
# solely on the virtual display and never on the user's built-in screen.
#
# Requires:
#   - A connected virtual display (run ./create.sh first).
#   - Accessibility permission for the app running this (Zed/terminal), so System
#     Events can reposition windows: System Settings > Privacy & Security > Accessibility.
#
# Usage: ./run-on-vdisplay.sh "AppName" [X] [Y] [ProcessName]
#   X,Y default to (1500,100); use an X >= the virtual display's origin.x printed by
#   create.sh. ProcessName defaults to AppName; pass it when the System Events
#   process name differs from the app name (e.g. app "Visual Studio Code" -> "Code").
#
# Note: this is for launching an app that is NOT already running. If the app is
# already open, quit it first (`osascript -e 'tell application "AppName" to quit'`)
# so it can be relaunched hidden.
#
# Works for apps that open a window on launch. Some document apps (e.g. TextEdit)
# do not auto-open a window; for those, create the window while the app is still
# hidden before positioning, e.g. between launch and reveal:
#   open -gj -a TextEdit
#   osascript -e 'tell application "TextEdit" to make new document'
#   osascript -e 'tell application "System Events" to tell process "TextEdit" to set position of window 1 to {1600,150}'
#   osascript -e 'tell application "TextEdit" to activate'
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_polite.sh
source "$DIR/_polite.sh"

APP="${1:?usage: run-on-vdisplay.sh AppName [X] [Y] [ProcessName]}"
X="${2:-1500}"
Y="${3:-100}"
PROC="${4:-$APP}"

# Polite interaction: ask first (10s countdown) if the human is around;
# otherwise proceed and leave a sticky note recording what happened.
request_control "open '$APP' on the virtual display"

# Launch hidden (-j) and without foregrounding (-g): the window is never rendered.
open -gj -a "$APP"

# Wait (up to ~10s) for a window to exist, all while the app stays hidden.
for _ in $(seq 1 40); do
  n=$(osascript -e "tell application \"System Events\" to tell process \"$PROC\" to count windows" 2>/dev/null || echo 0)
  [ "${n:-0}" -ge 1 ] && break
  sleep 0.25
done

# Move the window onto the virtual display while hidden, then reveal it there.
osascript <<OSA
tell application "System Events" to tell process "$PROC"
  if (count of windows) > 0 then
    set position of window 1 to {$X, $Y}
  end if
end tell
tell application "$APP" to activate
OSA

echo "Opened '$APP' directly on the virtual display at ($X,$Y) — no flash on the main screen."
