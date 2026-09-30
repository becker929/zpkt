#!/bin/bash
# Shared "polite interaction" helpers for the virtual-display skill.
# Source this file; do not run it directly.
#
# - user_is_present(): true if keyboard/pointer activity was seen in the
#   last PRESENCE_WINDOW_SECS (default 600s = 10 minutes).
# - request_control "description": if the user is present, shows a 10-second
#   countdown notice before proceeding (asks first, then takes control). If
#   the user is away, proceeds immediately and leaves a sticky note about it.

PRESENCE_WINDOW_SECS="${PRESENCE_WINDOW_SECS:-600}"   # 10 minutes
COUNTDOWN_SECS="${COUNTDOWN_SECS:-10}"

# Seconds since the last keyboard or pointer event, system-wide.
idle_seconds() {
  ioreg -c IOHIDSystem 2>/dev/null \
    | awk -F'= ' '/HIDIdleTime/ {gsub(/[^0-9]/,"",$2); print $2/1000000000; exit}'
}

user_is_present() {
  local idle
  idle="$(idle_seconds)"
  [ -n "$idle" ] || return 1   # unknown -> assume present (safer default)
  awk -v i="$idle" -v w="$PRESENCE_WINDOW_SECS" 'BEGIN{exit !(i < w)}'
}

# Leaves a macOS Stickies note recording that the agent took control.
leave_sticky_note() {
  local msg="$1"
  osascript <<OSA >/dev/null 2>&1
tell application "Stickies" to activate
delay 0.3
tell application "System Events" to tell process "Stickies"
  keystroke "n" using command down
  delay 0.3
  keystroke "$msg"
end tell
tell application "Stickies" to set visible of every window to true
OSA
}

# Ask before taking control of the screen (opening/moving app windows) or
# taking a screenshot. Call with a short human-readable description.
request_control() {
  local action="${1:-take control of your screen}"
  if user_is_present; then
    osascript -e "display dialog \"Agent wants to: $action\\n\\nProceeding automatically in ${COUNTDOWN_SECS}s...\" giving up after ${COUNTDOWN_SECS} buttons {\"OK\"} default button 1 with title \"Agent requesting control\"" >/dev/null 2>&1 || true
  else
    leave_sticky_note "Agent took control at $(date '+%H:%M:%S') while you were away, to: $action"
  fi
}
