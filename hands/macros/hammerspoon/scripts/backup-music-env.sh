#!/usr/bin/env bash
set -euo pipefail

ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs"

rsync -a --delete \
  "$HOME/Music/Ableton/" \
  "$ICLOUD/Ableton User Library/"

rsync -a --delete \
  "$HOME/Library/Application Support/Ableton/" \
  "$ICLOUD/Ableton App Support/"

{
  echo "=== /Library/Audio/Plug-Ins ==="
  find /Library/Audio/Plug-Ins -type d 2>/dev/null || true
  echo ""
  echo "=== ~/Library/Audio/Plug-Ins ==="
  find "$HOME/Library/Audio/Plug-Ins" -type d 2>/dev/null || true
  echo ""
  echo "=== ~/Music/Ableton ==="
  find "$HOME/Music/Ableton" -type d 2>/dev/null || true
  echo ""
  echo "=== ~/Library/Application Support/Ableton ==="
  find "$HOME/Library/Application Support/Ableton" -type d 2>/dev/null || true
} > "$ICLOUD/Snapshots/plugin-dir-snapshot.txt"
