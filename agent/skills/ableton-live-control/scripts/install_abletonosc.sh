#!/usr/bin/env bash
# install_abletonosc.sh - Download and install the AbletonOSC remote script into
# the Ableton User Library. Idempotent: skips download if already present unless
# --force is passed.
#
# Usage: bash install_abletonosc.sh [--force]
set -euo pipefail

DEST="$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC"
FORCE="${1:-}"

if [ -d "$DEST" ] && [ "$FORCE" != "--force" ]; then
  echo "AbletonOSC already installed at:"
  echo "  $DEST"
  echo "(pass --force to reinstall)"
  exit 0
fi

TMP="$(mktemp -d)"
echo "Downloading AbletonOSC (master) from GitHub..."
curl -fsSL "https://github.com/ideoforms/AbletonOSC/archive/refs/heads/master.zip" -o "$TMP/aosc.zip"
echo "Unzipping..."
unzip -q "$TMP/aosc.zip" -d "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'AbletonOSC-*' | head -1)"
if [ -z "$SRC" ]; then
  echo "ERROR: could not find unzipped AbletonOSC directory" >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"
rm -rf "$TMP"
echo "Installed AbletonOSC to:"
echo "  $DEST"
echo
echo "Next: (re)start Ableton Live, then enable it in"
echo "  Settings -> Link/Tempo/MIDI -> Control Surface -> AbletonOSC"
echo "(see enable_osc.sh and SKILL.md). Selection persists across restarts."
