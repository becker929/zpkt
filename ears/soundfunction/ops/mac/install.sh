#!/bin/bash
# Load the two launchd jobs for the current user. Re-run after editing.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
chmod +x "$HERE"/*.sh
cat > "$LA/me.anthonybecker.ntfy-reminders.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>me.anthonybecker.ntfy-reminders</string>
  <key>ProgramArguments</key><array><string>$HERE/ntfy_to_reminders.sh</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardErrorPath</key><string>$HERE/ntfy_reminders.log</string>
</dict></plist>
PLIST
cat > "$LA/me.anthonybecker.mailbox-poll.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>me.anthonybecker.mailbox-poll</string>
  <key>ProgramArguments</key><array><string>$HERE/mailbox_poll.sh</string></array>
  <key>StartInterval</key><integer>300</integer><key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardErrorPath</key><string>$HERE/mailbox_poll.log</string>
</dict></plist>
PLIST
for j in me.anthonybecker.ntfy-reminders me.anthonybecker.mailbox-poll; do
  launchctl bootout "gui/$(id -u)/$j" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LA/$j.plist"
done
echo "loaded: ntfy-reminders (always on), mailbox-poll (every 5 min)"
