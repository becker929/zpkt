#!/bin/bash
# Load the two launchd jobs for the current user. Re-run after editing.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
chmod +x "$HERE"/*.sh
for bin in claude gh ntfy; do
  if ! command -v "$bin" >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/$bin" ]; then
    echo "warning: $bin not found on PATH or in ~/.local/bin; the jobs will log this and do nothing"
  fi
done
cat > "$LA/me.anthonybecker.ntfy-reminders.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>me.anthonybecker.ntfy-reminders</string>
  <key>ProgramArguments</key><array><string>$HERE/ntfy_to_reminders.sh</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$HOME/.local/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string><key>HOME</key><string>$HOME</string></dict>
  <key>StandardErrorPath</key><string>$HERE/ntfy_reminders.log</string>
</dict></plist>
PLIST
cat > "$LA/me.anthonybecker.mailbox-poll.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>me.anthonybecker.mailbox-poll</string>
  <key>ProgramArguments</key><array><string>$HERE/mailbox_poll.sh</string></array>
  <key>StartInterval</key><integer>300</integer><key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$HOME/.local/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string><key>HOME</key><string>$HOME</string></dict>
  <key>StandardErrorPath</key><string>$HERE/mailbox_poll.log</string>
</dict></plist>
PLIST
# shellcheck disable=SC1091
source "$HERE/../local.env"
JOBS="me.anthonybecker.ntfy-reminders"
if [ "${MAILBOX_PR:-0}" != "0" ]; then JOBS="$JOBS me.anthonybecker.mailbox-poll"; else echo "MAILBOX_PR is 0: mailbox poll not loaded yet; re-run after the PR exists"; fi
for j in $JOBS; do
  launchctl bootout "gui/$(id -u)/$j" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LA/$j.plist"
done
echo "loaded: $JOBS"
