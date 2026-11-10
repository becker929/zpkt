#!/bin/bash
# Run a pointer-driving command, then park the cursor whatever happened. Keeps the exit code.
#   bash scripts/with-cursor-parked.sh cliclick c:1200,680
"$@"; rc=$?
bash "$(dirname "$0")/park-cursor.sh" >/dev/null 2>&1 || true
exit $rc
