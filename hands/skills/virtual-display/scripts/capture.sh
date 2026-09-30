#!/bin/bash
# Capture a screenshot of the virtual (secondary) display only.
# Requires: Screen Recording permission granted to the app running this (Zed/terminal).
#   System Settings > Privacy & Security > Screen Recording > enable the app, then relaunch it.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_polite.sh
source "$DIR/_polite.sh"

OUT="${1:-/tmp/vdisplay.png}"

# -D 2 = secondary display (the virtual one). Default target is the virtual
# display, not the real one (built-in is main/-D 1). Override with DISPLAY_ID
# if you deliberately need the real screen.
DISPLAY_ID="${DISPLAY_ID:-2}"

# Polite interaction: ask first (10s countdown) if the human is around;
# otherwise proceed and leave a sticky note recording what happened.
request_control "take a screenshot of the virtual display"

if screencapture -x -D "$DISPLAY_ID" "$OUT" 2>/tmp/vcap.err; then
  echo "Captured virtual display -> $OUT"
  sips -g pixelWidth -g pixelHeight "$OUT" 2>/dev/null | grep -iE "pixel" || true
else
  echo "Capture failed. Most likely cause: Screen Recording permission not granted." >&2
  echo "Open the settings pane with:" >&2
  echo "  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'" >&2
  cat /tmp/vcap.err >&2 || true
  exit 1
fi
