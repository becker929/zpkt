#!/bin/bash
# Is GUI automation actually allowed right now, and if not, exactly what to fix.
#
# Run this FIRST in any session that will drive Live's GUI, and any time an
# automation starts failing with error -1728. A Claude Code update silently
# breaks the grant, because the granted path carries the version number.
set -uo pipefail
BASE="$HOME/Library/Application Support/Claude/claude-code"
RUNNING=$(ps auxww | grep -o "claude-code/[0-9.]*/claude.app" | sort -u | head -1 | cut -d/ -f2)
# Every probe is time-boxed: a preflight must never hang the caller.
AX=$(timeout 10 osascript -e 'tell application "System Events" to return UI elements enabled' 2>/dev/null || echo unknown)
if command -v hs >/dev/null; then
  HS=$(timeout 25 hs -c 'return tostring(hs.accessibilityState())' 2>/dev/null | grep -v Loading | tail -1)
  HS=${HS:-timeout}
else
  HS="no-hs"
fi

echo "running claude-code : ${RUNNING:-unknown}"
echo "versions on disk    : $(ls -1 "$BASE" 2>/dev/null | tr '\n' ' ')"
echo "direct osascript AX : $AX"
echo "Hammerspoon AX      : $HS"
echo

if [ "$AX" = "true" ]; then
  echo "[ok] GUI automation is allowed. Full auto runs will work."
  exit 0
fi

echo "[BLOCKED] osascript has no assistive access. Fix, in order of effort:"
echo
echo "1. Turn the CURRENT version on in System Settings:"
echo "     open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility\""
echo "   Remove any existing lower-case 'claude.app' entry (it points at an old"
echo "   version and grants nothing), then add this exact path with the + button"
echo "   and Command-Shift-G:"
echo
echo "     $BASE/${RUNNING:-<running version>}/claude.app"
echo
echo "   Then QUIT Claude fully and reopen it. The grant is read at process start."
echo "   Note: the lower-case claude.app with the blank grey icon is the one that"
echo "   matters. The upper-case Claude.app with the orange icon is the desktop"
echo "   app and is NOT what runs the shell."
echo
if [ "$HS" = "true" ]; then
  echo "2. Or route around it entirely: Hammerspoon HAS access and lives at a"
  echo "   stable path, so it never goes stale. Use scripts/osa.sh instead of"
  echo "   calling osascript directly; it falls back through Hammerspoon."
fi
exit 1
