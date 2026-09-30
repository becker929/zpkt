#!/bin/bash
# Poll the "Agent mailbox" pull request for new comments addressed to @mac and
# hand each one to a headless Claude Code run. Runs every five minutes under
# launchd. Needs: gh auth login ; ops/local.env with MAILBOX_REPO and
# MAILBOX_PR ; claude on PATH.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$HERE/local.env"
STATE="$HERE/mac/.mailbox_last_id"
last=$(cat "$STATE" 2>/dev/null || echo 0)
LOG="$HERE/mac/mailbox_poll.log"
echo "$(date -u +%FT%TZ) poll start, last_id=$last, PATH=$PATH" >> "$LOG"
for bin in claude gh; do
  command -v "$bin" >/dev/null 2>&1 || { echo "$(date -u +%FT%TZ) ERROR: $bin not on PATH; nothing done" >> "$LOG"; exit 0; }
done
[ "${MAILBOX_PR:-0}" != "0" ] || { echo "$(date -u +%FT%TZ) MAILBOX_PR is 0; nothing done" >> "$LOG"; exit 0; }

gh api "repos/$MAILBOX_REPO/issues/$MAILBOX_PR/comments?per_page=50&since=$(date -u -v-1d +%Y-%m-%dT%H:%M:%SZ)" \
  --jq '.[] | select(.body | startswith("@mac")) | [.id, .user.login, .body] | @json' |
while read -r row; do
  id=$(printf '%s' "$row" | python3 -c 'import sys,json; print(json.load(sys.stdin)[0])')
  [ "$id" -gt "$last" ] || continue
  body=$(printf '%s' "$row" | python3 -c 'import sys,json; print(json.load(sys.stdin)[2])')
  who=$(printf '%s' "$row" | python3 -c 'import sys,json; print(json.load(sys.stdin)[1])')
  echo "$id" > "$STATE"
  echo "$(date -u +%FT%TZ) handling comment $id from $who" >> "$LOG"
  # Run the request. The prompt tells the agent how to answer: a comment back on
  # the same PR, addressed to whoever asked, never to itself.
  (cd "$HERE/.." && claude -p "You are the Live/Mac agent. A message arrived on the agent mailbox PR from $who:

$body

Do what it asks, within the rules in research/mac-lab.md and research/channels.md. When done or blocked, reply with exactly one comment on the same PR using: gh pr comment $MAILBOX_PR --repo $MAILBOX_REPO --body '...'. Start the reply with @research (or @anthony if only he can act). Never start a reply with @mac." \
    >> "$HERE/mac/mailbox_runs.log" 2>&1)
done
