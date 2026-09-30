#!/bin/bash
# Mirror high-priority ntfy messages into Apple Reminders. Runs forever under
# launchd on the always-on Mac. Needs: brew install ntfy ; ops/local.env with
# NTFY_TOPIC=... ; Reminders access granted to the terminal/launchd once.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$HERE/local.env"
LIST="${REMINDERS_LIST:-Techno harness}"

ntfy subscribe "$NTFY_TOPIC" | while read -r line; do
  prio=$(printf '%s' "$line" | python3 -c 'import sys,json; m=json.load(sys.stdin); print(m.get("priority",3))' 2>/dev/null || echo 3)
  [ "${prio:-3}" -ge 4 ] || continue          # 4 = high, 5 = urgent
  title=$(printf '%s' "$line" | python3 -c 'import sys,json; m=json.load(sys.stdin); print(m.get("title") or "Techno harness")')
  body=$(printf '%s' "$line" | python3 -c 'import sys,json; m=json.load(sys.stdin); print((m.get("message") or "") + ("\n" + m["click"] if m.get("click") else ""))')
  osascript - "$LIST" "$title" "$body" <<'APPLESCRIPT'
on run argv
  set listName to item 1 of argv
  set theTitle to item 2 of argv
  set theBody to item 3 of argv
  tell application "Reminders"
    if not (exists list listName) then make new list with properties {name:listName}
    tell list listName
      make new reminder with properties {name:theTitle, body:theBody, due date:(current date) + 1 * hours}
    end tell
  end tell
end run
APPLESCRIPT
done
