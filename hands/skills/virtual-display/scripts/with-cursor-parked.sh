#!/bin/bash
# Run a command that takes over the physical pointer, and ALWAYS return the
# cursor to the center of the primary physical display when it finishes --
# whether it succeeds, fails, or is interrupted.
#
# This is the deterministic enforcement of the cursor-return rule: it does not
# rely on the caller (human or agent) remembering to park. Any ad-hoc cursor
# takeover -- a raw `cliclick`, a manual dropdown-selection fallback, a one-off
# GUI-automation osascript -- MUST be run through this wrapper instead of
# directly, so the pointer is guaranteed to come back.
#
# Usage:
#   bash with-cursor-parked.sh <command> [args...]
#
# Examples:
#   bash with-cursor-parked.sh cliclick c:1200,680 c:1185,711
#   bash with-cursor-parked.sh osascript /path/to/some-gui.applescript
#
# The wrapped command's exit status is preserved.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -eq 0 ]; then
  echo "usage: with-cursor-parked.sh <command> [args...]" >&2
  exit 2
fi

# Park on EVERY exit path (normal return, error, or signal). The trap fires once,
# after the wrapped command has finished, regardless of how it ended.
park() { bash "$DIR/park-cursor.sh" >&2 || true; }
trap park EXIT

"$@"
