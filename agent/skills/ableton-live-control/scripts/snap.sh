#!/usr/bin/env bash
# snap.sh - The ONLY sanctioned screenshot path. It always crops/downscales and
# enforces a hard size budget, so a raw ~15 MB Retina PNG can never reach an
# agent's context. Writes to a single scratch path by default (overwrite, no
# gallery).
#
# Usage:
#   bash snap.sh [OUT_PNG] [CROP_GEOMETRY] [MAX_WIDTH]
#     OUT_PNG        output path              (default /tmp/vd_snap.png)
#     CROP_GEOMETRY  ImageMagick crop WxH+X+Y (default: none -> whole capture)
#     MAX_WIDTH      downscale target width   (default 1000)
#
# Examples:
#   bash snap.sh                                   # whole screen, downscaled
#   bash snap.sh /tmp/cs.png 1050x380+1220+680     # crop the Control Surfaces table
#
# Env: DISPLAY_ID (screencapture -D display id, default 1), BUDGET_KB (default 700).
set -euo pipefail
OUT="${1:-/tmp/vd_snap.png}"
CROP="${2:-}"
MAXW="${3:-1000}"
DISPLAY_ID="${DISPLAY_ID:-1}"
BUDGET_KB="${BUDGET_KB:-700}"

command -v screencapture >/dev/null 2>&1 || { echo "ERROR: screencapture missing"; exit 1; }
command -v magick >/dev/null 2>&1 || { echo "ERROR: ImageMagick 'magick' missing (brew install imagemagick)"; exit 1; }

RAW="$(mktemp -t snapraw).png"
trap 'rm -f "$RAW"' EXIT

# -x = no capture sound; -D = which display.
screencapture -x -D "$DISPLAY_ID" "$RAW" 2>/dev/null || screencapture -x "$RAW"

# crop (optional) then downscale to MAXW, capped so it never exceeds the budget.
if [ -n "$CROP" ]; then
  magick "$RAW" -crop "$CROP" +repage -resize "${MAXW}>" -strip "$OUT"
else
  magick "$RAW" -resize "${MAXW}>" -strip "$OUT"
fi

# Hard budget guard: if still too big, step the width down until it fits.
w="$MAXW"
while [ "$(du -k "$OUT" | cut -f1)" -gt "$BUDGET_KB" ] && [ "$w" -gt 200 ]; do
  w=$(( w * 3 / 4 ))
  magick "$RAW" ${CROP:+-crop "$CROP" +repage} -resize "${w}>" -strip "$OUT"
done

KB="$(du -k "$OUT" | cut -f1)"
DIM="$(magick identify -format '%wx%h' "$OUT")"
echo "wrote $OUT  (${DIM}, ${KB} KB, budget ${BUDGET_KB} KB)"
[ "$KB" -le "$BUDGET_KB" ] || { echo "WARNING: still over budget at min width"; }
