#!/bin/bash
# Park the mouse cursor at the center of the primary physical display.
#
# Any skill that drives the pointer (cliclick clicks, System Events, GUI
# automation) leaves the cursor wherever its last action landed -- often on the
# virtual display or over a control the user did not put it on. Run this as the
# LAST step of any cursor takeover so the user gets their pointer back in a
# neutral, expected spot on their own screen.
#
# Usage: bash park-cursor.sh
set -euo pipefail

# Center of the MAIN display in global points (Quartz top-left origin), which is
# exactly the coordinate space cliclick uses. CGMainDisplayID() is the display
# that owns the menu bar -- the user's primary physical screen.
read -r CX CY < <(swift - <<'SWIFT'
import CoreGraphics
let id = CGMainDisplayID()
let b = CGDisplayBounds(id)
let cx = Int(b.origin.x + b.size.width / 2)
let cy = Int(b.origin.y + b.size.height / 2)
print("\(cx) \(cy)")
SWIFT
)

# Resolve cliclick: PATH first, then the Apple-Silicon / Intel Homebrew prefixes.
CLICLICK="$(command -v cliclick 2>/dev/null || true)"
if [ -z "${CLICLICK:-}" ]; then
  for cand in /opt/homebrew/bin/cliclick /usr/local/bin/cliclick; do
    [ -x "$cand" ] && CLICLICK="$cand" && break
  done
fi
if [ -z "${CLICLICK:-}" ]; then
  echo "error: cliclick not found on PATH or Homebrew prefixes (brew install cliclick)" >&2
  exit 1
fi

"$CLICLICK" m:"$CX","$CY"
echo "Parked cursor at ($CX,$CY) on the primary physical display."
