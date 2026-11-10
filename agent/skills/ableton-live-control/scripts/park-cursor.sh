#!/bin/bash
# Move the pointer to the centre of the main display, so a scripted click never leaves it
# hovering over Live. Does nothing without cliclick (brew install cliclick).
command -v cliclick >/dev/null 2>&1 || exit 0
bounds=$(osascript -e 'tell application "Finder" to get bounds of window of desktop' 2>/dev/null) || exit 0
w=$(echo "$bounds" | awk -F', ' '{print $3}'); h=$(echo "$bounds" | awk -F', ' '{print $4}')
[ -n "$w" ] && [ -n "$h" ] && cliclick "m:$((w / 2)),$((h / 2))"
