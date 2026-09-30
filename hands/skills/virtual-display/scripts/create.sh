#!/bin/bash
# Create + connect a virtual display for headless GUI testing (macOS, BetterDisplay).
# Reuses an existing virtual screen if one is present (avoids duplicates), then
# prints the connected virtual display's macOS displayID and its global frame.
set -euo pipefail

NAME="${1:-HeadlessTest}"

# Ensure BetterDisplay is running (menu bar app that hosts the CLI).
open -ga BetterDisplay
sleep 2

# Reuse an existing virtual screen if there is one; otherwise create it.
TAG=$(betterdisplaycli get -deviceType=VirtualScreen -identifiers 2>/dev/null \
        | grep -m1 '"tagID"' | grep -oE '[0-9]+' || true)
if [ -z "${TAG:-}" ]; then
  betterdisplaycli create -type=VirtualScreen -virtualScreenName="$NAME" >/dev/null 2>&1 \
    || betterdisplaycli create -type=VirtualScreen >/dev/null 2>&1 || true
  sleep 1
  TAG=$(betterdisplaycli get -deviceType=VirtualScreen -identifiers 2>/dev/null \
          | grep -m1 '"tagID"' | grep -oE '[0-9]+' || true)
fi
if [ -z "${TAG:-}" ]; then
  echo "error: could not find/create a virtual screen" >&2
  exit 1
fi

# Make sure it's connected to WindowServer.
betterdisplaycli set -tagID="$TAG" -connected=on >/dev/null 2>&1 || true
sleep 2

echo "Virtual screen tagID=$TAG connected."
echo "Display arrangement (id / origin / size in points):"
swift - <<'SWIFT'
import CoreGraphics
var n: UInt32 = 0
CGGetActiveDisplayList(0, nil, &n)
var ids = [CGDirectDisplayID](repeating: 0, count: Int(n))
CGGetActiveDisplayList(n, &ids, &n)
for id in ids {
  let b = CGDisplayBounds(id)
  let main = CGDisplayIsMain(id) != 0 ? "  [MAIN/your screen]" : ""
  print("  id=\(id) origin=(\(Int(b.origin.x)),\(Int(b.origin.y))) size=\(Int(b.size.width))x\(Int(b.size.height))\(main)")
}
SWIFT
