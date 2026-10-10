#!/usr/bin/env bash
# mcp_up.sh - Path B (LOM/MCP) reachability check, the twin of osc_up.sh.
# Confirms the AbletonLiveMCP control surface is actually responding on TCP
# 16619 by round-tripping a trivial expression (1+1 -> 2), not just probing the
# port. Exits 0 and prints an "up" line if healthy; non-zero otherwise.
#
# Usage: bash mcp_up.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANDS="$(cd "$DIR/../../.." && pwd)"
HOST="${MCP_HOST:-127.0.0.1}"
PORT="${MCP_PORT:-16619}"

# Fast port probe first (cheap, avoids waiting on a client timeout when Live is down).
if ! nc -z "$HOST" "$PORT" 2>/dev/null; then
  echo "AbletonLiveMCP is DOWN: nothing listening on ${HOST}:${PORT}."
  echo "  -> Live not running, or the AbletonLiveMCP control surface is not selected."
  exit 1
fi

OUT="$(uv run --quiet --project "$HANDS" hands live exec --host "$HOST" --port "$PORT" --timeout 5 --json "result = 1 + 1" 2>/dev/null || true)"
if [ "$OUT" = "2" ]; then
  echo "AbletonLiveMCP is up (TCP ${HOST}:${PORT}); LOM round-trip OK."
  exit 0
fi
echo "AbletonLiveMCP port is open but the bridge did not answer (got: '${OUT:-<none>}')."
echo "  -> The surface may be wedged; try a single simple call or re-select the surface."
exit 1
