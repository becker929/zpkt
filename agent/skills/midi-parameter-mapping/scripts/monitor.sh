#!/usr/bin/env bash
# monitor.sh - Manage the all-ports MIDI monitor (under tmux) used to discover
# a hardware controller's CC/note numbers.
# Usage:
#   monitor.sh start          start a fresh monitor (clears the log)
#   monitor.sh dump           print the captured log
#   monitor.sh summary        per-port, per-CC/note counts (ignores SysEx)
#   monitor.sh stop
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$DIR/.." && pwd)"
PY="$SKILL_ROOT/venv/bin/python"
SESSION="midimon"
LOG="/tmp/agentmidi_monitor.log"
CMD="${1:-summary}"

case "$CMD" in
  start)
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    rm -f "$LOG"
    tmux new -d -s "$SESSION" "$PY $DIR/midi_monitor_all.py"
    sleep 1.5
    echo "monitoring; ports opened:"
    cat "$LOG"
    ;;
  dump)
    cat "$LOG" ;;
  summary)
    echo "== message counts by port + type =="
    grep -vE 'opened|listening|SYSEX' "$LOG" | awk '{print $1, $2, $3, $4, $5}' | sort | uniq -c | sort -rn
    ;;
  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "stopped" || echo "not running"
    ;;
  *)
    echo "usage: monitor.sh {start|dump|summary|stop}"; exit 1 ;;
esac
