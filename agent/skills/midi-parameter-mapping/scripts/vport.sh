#!/usr/bin/env bash
# vport.sh - Manage the AgentVirtualMIDI virtual port daemon (under tmux).
# Usage: vport.sh {start|stop|status}
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$DIR/.." && pwd)"
PY="$SKILL_ROOT/venv/bin/python"
SESSION="agentmidi"
CMD="${1:-status}"

case "$CMD" in
  start)
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    tmux new -d -s "$SESSION" "$PY $DIR/midi_vport.py"
    sleep 1.5
    echo "started; recent output:"
    tmux capture-pane -t "$SESSION" -p | grep -v '^$' | tail -3 || true
    ;;
  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "stopped" || echo "not running"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "running"
      "$PY" -c "import rtmidi; print('AgentVirtualMIDI present:', 'AgentVirtualMIDI' in rtmidi.MidiIn().get_ports())"
    else
      echo "not running"
    fi
    ;;
  *)
    echo "usage: vport.sh {start|stop|status}"; exit 1 ;;
esac
