#!/usr/bin/env bash
# dismiss_modals.sh - The "modal reaper". Ableton GUI automation hangs when an
# UNEXPECTED dialog/menu is on screen (launch nags, "save changes?", overwrite
# prompts, plugin windows, alerts). This enumerates every window + sheet of the
# Live process (via `hands live modals`, whose AppleScript is
# hands/src/hands/live/reap_modals.applescript) and:
#   * CHECK mode (default): reports what modal(s) are present and their buttons,
#     without touching anything.
#   * REAP mode (--reap): auto-dismisses ONLY recognized, NON-destructive modals
#     by pressing their safe button (Cancel > Don't Save > No > Close > OK) or
#     Escape for button-less popups. It NEVER presses a destructive button
#     (Save, Replace, Overwrite, Yes, Delete, Don't Restore...). Anything it does
#     not recognize -> it ABORTS LOUDLY (exit 3) with the title + a cropped
#     screenshot path, so a human/agent can inspect manually instead of the
#     script blindly clicking.
#
# Exit codes: 0 = clean (no modal, or all safely reaped)
#             2 = modal(s) present (CHECK mode only; informational)
#             3 = ABORT: unrecognized / destructive-only modal needs inspection
#             4 = Live not running
#
# Usage:
#   bash dismiss_modals.sh            # check only, report
#   bash dismiss_modals.sh --reap     # dismiss safe modals, abort on unknown
#
# Every Apple event is wrapped in `with timeout` (in the .applescript) so a
# stalled accessibility tree fails fast. Still: prepend `timeout` at the CLI.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANDS="$(cd "$DIR/../../.." && pwd)"
MODE="check"
FLAG=""   # a string, not an array: macOS bash 3.2 calls an empty array unbound under set -u
[ "${1:-}" = "--reap" ] && MODE="reap" && FLAG="--reap"
modals() { uv run --quiet --project "$HANDS" hands live modals "$@" 2>/dev/null; }

REPORT="$(modals $FLAG)"
RC=$?
if [ $RC -ne 0 ]; then
  echo "reaper: osascript failed or timed out (rc=$RC). Live's UI may be wedged,"
  echo "  or this process lacks Accessibility permission (System Settings > Privacy)."
  exit 3
fi

case "$REPORT" in
  NO_LIVE) echo "Live is not running."; exit 4 ;;
  CLEAN)   echo "No modal dialogs present."; exit 0 ;;
esac

echo "$REPORT"

# If any line is an ABORT, snapshot and fail loudly for manual inspection.
if printf '%s\n' "$REPORT" | grep -q '^ABORT'; then
  SNAP="/tmp/modal_abort.png"
  bash "$DIR/snap.sh" "$SNAP" >/dev/null 2>&1 && echo "ABORT: unrecognized/destructive-only modal. Inspect: $SNAP"
  exit 3
fi

# CHECK mode: modals present but none acted on -> informational non-zero.
if [ "$MODE" = "check" ]; then
  exit 2
fi

# REAP mode with no aborts: verify it is now clean.
sleep 0.3
RECHK="$(modals)"
if [ "$RECHK" = "CLEAN" ]; then
  echo "All modals safely dismissed."
  exit 0
fi
echo "Modal(s) still present after reap; inspect manually."
exit 3
