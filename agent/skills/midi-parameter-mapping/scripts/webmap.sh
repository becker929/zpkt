#!/usr/bin/env bash
# webmap.sh - Manage the MiniLab 3 web-controller bridge daemon (under tmux).
#
# Serves the web page + a live labels.json derived from AgentMap's config.json,
# so mapping changes show up on the on-screen controller automatically.
#
# Usage: webmap.sh {start|stop|status|url}
# Env:   WEBMAP_PORT (default 8731), WEBMAP_PAGE (default ~/arturia-minilab3.html),
#        WEBMAP_RESOLVE=1 to resolve friendly Live names via AbletonOSC.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="agentmidi-webmap"
PORT="${WEBMAP_PORT:-8731}"
PAGE="${WEBMAP_PAGE:-$HOME/arturia-minilab3.html}"
CMD="${1:-status}"

RESOLVE_FLAG=""
if [ "${WEBMAP_RESOLVE:-0}" = "1" ]; then RESOLVE_FLAG="--resolve-names"; fi

case "$CMD" in
  start)
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    tmux new -d -s "$SESSION" \
      "python3 '$DIR/webmap.py' --port '$PORT' --page '$PAGE' $RESOLVE_FLAG"
    sleep 1
    echo "started; open http://localhost:$PORT/"
    tmux capture-pane -t "$SESSION" -p | grep -v '^$' | tail -3 || true
    ;;
  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "stopped" || echo "not running"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "running on http://localhost:$PORT/"
      curl -s "http://localhost:$PORT/labels.json" | head -c 400 || true
      echo
    else
      echo "not running"
    fi
    ;;
  url)
    echo "http://localhost:$PORT/"
    ;;
  *)
    echo "usage: webmap.sh {start|stop|status|url}"; exit 1 ;;
esac
