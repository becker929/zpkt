#!/bin/bash
# Run AppleScript with assistive access that survives Claude Code updates.
#
# Direct `osascript` only works while the CURRENT claude-code version bundle
# is switched on in Privacy & Security > Accessibility. That path carries the
# version number, so every Claude update silently revokes it and every GUI
# automation starts failing with error -1728.
#
# Hammerspoon is granted at a stable path (/Applications/Hammerspoon.app) and
# runs all the time. A child process it spawns inherits its grant. So: try
# direct first, and fall back through Hammerspoon when direct is not allowed.
#
#   osa.sh script.applescript [args...]
#   osa.sh -e 'tell application "System Events" to ...'
set -uo pipefail

run_direct() { osascript "$@" 2>&1; }

run_via_hs() {
  command -v hs >/dev/null || { echo "osa.sh: hs CLI not found" >&2; return 127; }
  local tmp; tmp=$(mktemp -t osa_via_hs)
  { printf '#!/bin/bash\nexec osascript'
    for a in "$@"; do printf ' %q' "$a"; done
    printf '\n'
  } > "$tmp"
  chmod +x "$tmp"
  hs -c "local out, ok = hs.execute([[$tmp]]); return (out or '') .. (ok and '' or '\\n__OSA_FAIL__')" 2>/dev/null \
    | grep -v '^-- Loading extension' | grep -v '__OSA_FAIL__'
  local rc=${PIPESTATUS[0]}
  rm -f "$tmp"
  return $rc
}

out=$(run_direct "$@"); rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q '\-1728\|not allowed assistive access'; then
  echo "osa.sh: direct osascript lacks assistive access, routing via Hammerspoon" >&2
  run_via_hs "$@"
  exit $?
fi
printf '%s\n' "$out"
exit $rc
