#!/usr/bin/env bash
# osc_up.sh - exit 0 if AbletonOSC is responding, 1 otherwise.
# Usage: bash osc_up.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(python3 "$DIR/live.py" --timeout 1.5 /live/test 2>/dev/null)" = "ok" ]; then
  echo "AbletonOSC is up (UDP 11000/11001)."
  exit 0
else
  echo "AbletonOSC is NOT responding on 11000/11001."
  exit 1
fi
