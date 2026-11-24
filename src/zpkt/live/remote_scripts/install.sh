#!/bin/bash
# Copy zpkt's Remote Scripts into Live's User Library. Live discovers new scripts only at launch,
# then each must be selected once in Settings -> Tempo & MIDI (a free row, Input/Output None).
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/Music/Ableton/User Library/Remote Scripts"
for d in "$SRC"/*/; do
  name=$(basename "$d")
  mkdir -p "$DEST/$name"
  cp "$d"*.py "$DEST/$name/"
  echo "installed $name -> $DEST/$name"
done
