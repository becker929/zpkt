#!/bin/bash
# Ask before a disruptive action with a cancellable on-screen countdown (Hammerspoon).
#
#   rig-confirm.sh "Reloading the Live set" [SECONDS]  &&  do_the_thing
#
# Exit 0 = go (the countdown ran out), 1 = the user cancelled, 2 = could not show it (Hammerspoon
# not running / no hs CLI). Never blocks longer than SECONDS + 5.
set -uo pipefail
MSG=${1:?usage: rig-confirm.sh "<what is about to happen>" [seconds]}
SECS=${2:-10}
MODULE="$(cd "$(dirname "$0")/.." && pwd)/modules/countdown.lua"
OUT=$(mktemp -t rig-confirm)
rm -f "$OUT"

command -v hs >/dev/null || { echo "rig-confirm: hs CLI not found" >&2; exit 2; }
lua_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
if ! hs -c "if not RIG_COUNTDOWN then RIG_COUNTDOWN = dofile(\"$(lua_str "$MODULE")\") end
return RIG_COUNTDOWN.start(\"$(lua_str "$MSG")\", $SECS, \"$OUT\")" >/dev/null 2>&1; then
  echo "rig-confirm: Hammerspoon did not answer" >&2
  exit 2
fi

for ((i = 0; i < (SECS + 5) * 5; i++)); do
  if [ -f "$OUT" ]; then
    R=$(cat "$OUT"); rm -f "$OUT"
    [ "$R" = go ] && { echo "go: $MSG"; exit 0; }
    echo "cancelled: $MSG"; exit 1
  fi
  sleep 0.2
done
hs -c 'if RIG_COUNTDOWN then RIG_COUNTDOWN.cancel() end' >/dev/null 2>&1
echo "rig-confirm: no answer from the countdown, treating as cancelled" >&2
exit 1
