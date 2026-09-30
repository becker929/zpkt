#!/usr/bin/env bash
# install.sh - One-time setup for the midi-parameter-mapping skill.
#   1. Creates a venv with python-rtmidi (for the virtual port + monitor).
#   2. Installs the AgentMap MIDI Remote Script into Live's User Library.
#
# It does NOT overwrite an existing AgentMap/config.json (your live mappings).
# After running, you must (once) RESTART Live, then select "AgentMap" on a free
# Control Surface row and set its Input port (see SKILL.md).
#
# Usage: bash install.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$DIR/.." && pwd)"
VENV="$SKILL_ROOT/venv"
DEST="$HOME/Music/Ableton/User Library/Remote Scripts/AgentMap"

echo "== venv + python-rtmidi =="
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip python-rtmidi
"$VENV/bin/python" -c "import rtmidi; print('  rtmidi OK')"

echo "== install AgentMap Remote Script =="
mkdir -p "$DEST"
cp "$DIR/AgentMap/__init__.py" "$DEST/__init__.py"
if [ ! -f "$DEST/config.json" ]; then
  cp "$DIR/AgentMap/config.json" "$DEST/config.json"
  echo "  wrote fresh config.json"
else
  echo "  kept existing config.json"
fi
"$VENV/bin/python" -c "import ast; ast.parse(open('$DEST/__init__.py').read()); print('  __init__.py syntax OK')"

cat <<EOF

Installed.
  venv:      $VENV
  AgentMap:  $DEST

Next (one-time GUI, because Live only discovers new Remote Scripts at launch):
  1. Restart Ableton Live.
  2. Settings -> Link / Tempo & MIDI -> a free Control Surface row:
       Control Surface = AgentMap
       Input           = your controller port, OR AgentVirtualMIDI (virtual port)
  3. Start the virtual port daemon:  bash "$DIR/vport.sh" start
Config file to edit (hot-reloads ~2x/sec):
  $DEST/config.json
EOF
