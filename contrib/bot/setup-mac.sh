#!/bin/bash
# Installs the music bot into roombot, the room bot's own standard macOS user (world2's bot/setup-mac.sh made it):
# one bot user on this Mac, two programs in it, each with its own LaunchAgent. Run from your admin account, in the repo:
#
#   sudo contrib/bot/setup-mac.sh             # install the bot, copy its state and secrets, start it
#   sudo contrib/bot/setup-mac.sh --update    # install the repo's current bot/ (after you've read the diff), restart
#   sudo contrib/bot/setup-mac.sh --secrets   # copy ~/_agent_scratch/music-bot/{secrets,config}.json over again, and the booth
#                                     # token from your Keychain (zpkt-booth-token), then restart
#   sudo contrib/bot/setup-mac.sh --uninstall # remove the music bot (its LaunchAgent and code); roombot and the room bot stay
#
# What it does, and nothing else:
#   - refuses to run until roombot exists and is a standard user, and your home folder is closed to it (world2's
#     setup does both);
#   - the code is copied to /usr/local/musicbot, owned by root: roombot can run it but never change it (bot/ only;
#     dependencies from the lockfile, without install scripts);
#   - root never writes into anything roombot owns: its state folder, secrets and LaunchAgent are written by roombot
#     itself (sudo -u), so a compromised roombot can't plant symlinks that turn a later run of this script on you;
#   - if the bot was running as you (the LaunchAgent me.anthonybecker.musicbot in your session), that one is stopped
#     and its plist renamed .disabled, so two bots never answer the same account.
# What roombot then holds for the music bot: its Bluesky app password, its Anthropic key and the booth token. A booth
# token can queue scores and nothing else (docs/design/bluesky-bot.md, "The one rule").
set -euo pipefail

USER_NAME=roombot
HOME_DIR=/Users/$USER_NAME
CODE_DIR=/usr/local/musicbot
STATE_REL=_agent_scratch/music-bot
LABEL=me.anthonybecker.musicbot
PLIST=$HOME_DIR/Library/LaunchAgents/$LABEL.plist
KEYCHAIN_ITEM=zpkt-booth-token
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

[ "$(uname)" = Darwin ] || { echo "This is for macOS."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Run with sudo (from your admin account)."; exit 1; }
ADMIN_USER="${SUDO_USER:-}"
[ -n "$ADMIN_USER" ] && [ "$ADMIN_USER" != root ] || { echo "Run with sudo from your own account, not as root."; exit 1; }
ADMIN_HOME="$(dscl . -read "/Users/$ADMIN_USER" NFSHomeDirectory | sed 's/^NFSHomeDirectory: //')"
[ -d "$ADMIN_HOME" ] || { echo "Couldn't find your home folder ($ADMIN_HOME)."; exit 1; }
command -v realpath >/dev/null || { echo "Needs macOS 13 or newer (realpath)."; exit 1; }

uid_of() { id -u "$USER_NAME" 2>/dev/null || true; }
# roombot's commands never get your terminal: stdin from /dev/null unless piped, and sudo gives every command its own
# pty (use_pty, set by world2's setup), so nothing roombot runs can push keystrokes into your shell
as_bot() { sudo -u "$USER_NAME" -H "$@"; }
as_admin() { sudo -u "$ADMIN_USER" -H "$@"; }

[ -n "$(uid_of)" ] || { echo "There is no $USER_NAME user yet: run world2's bot/setup-mac.sh first (it makes the user and closes your home folder)."; exit 1; }
dseditgroup -o checkmember -m "$USER_NAME" admin >/dev/null 2>&1 && { echo "$USER_NAME is an admin. Make it a standard user first."; exit 1; }

if [ "${1:-}" = --uninstall ]; then
  U=$(uid_of)
  as_bot launchctl bootout "gui/$U/$LABEL" </dev/null 2>/dev/null || launchctl bootout "gui/$U/$LABEL" 2>/dev/null || true
  as_bot /bin/rm -f "$PLIST" </dev/null || true
  rm -rf "$CODE_DIR"
  cat <<GONE
Removed the music bot's LaunchAgent and $CODE_DIR. $USER_NAME and the room bot are untouched.
Its state and secrets are still in $HOME_DIR/$STATE_REL (bot.db keeps every score it made). To remove them too:
  sudo -u $USER_NAME rm -rf $HOME_DIR/$STATE_REL
GONE
  exit 0
fi

NODE_BIN=""
for n in /opt/homebrew/bin/node /usr/local/bin/node; do [ -x "$n" ] && { NODE_BIN="$n"; break; }; done
[ -n "$NODE_BIN" ] || { echo "Need Node.js from Homebrew (brew install node). A Node inside your home folder (nvm) won't do."; exit 1; }
case "$(realpath "$NODE_BIN")" in "$ADMIN_HOME"*) echo "$NODE_BIN resolves into your home folder; install Node with Homebrew."; exit 1;; esac
"$NODE_BIN" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' || { echo "The bot needs Node 22 or newer (node:sqlite)."; exit 1; }
NPM_BIN="$(dirname "$NODE_BIN")/npm"
BREW_BIN="$(dirname "$NODE_BIN")"

# your home folder must already be yours alone (world2's setup made it 700): the music bot needs nothing from it
if as_bot /bin/ls "$ADMIN_HOME" </dev/null >/dev/null 2>&1; then echo "$USER_NAME can list $ADMIN_HOME: run world2's bot/setup-mac.sh (it closes your home folder), or fix its permissions/ACLs."; exit 1; fi

stop_admin_bot() {
  local AU P
  AU=$(id -u "$ADMIN_USER")
  P="$ADMIN_HOME/Library/LaunchAgents/$LABEL.plist"
  launchctl bootout "gui/$AU/$LABEL" 2>/dev/null && echo "Stopped the music bot that was running as $ADMIN_USER." || true
  if [ -f "$P" ] && [ ! -L "$P" ]; then as_admin mv -f "$P" "$P.disabled" && echo "Renamed $P to .disabled."; fi
}

# the code: a root-owned copy of bot/ (the bot needs nothing else from the repo)
install_code() {
  local tmp
  tmp="$(mktemp -d /tmp/musicbot.XXXXXX)"
  mkdir -p "$tmp/bot"
  cp "$REPO"/contrib/bot/*.mjs "$REPO/contrib/bot/package.json" "$REPO/contrib/bot/package-lock.json" "$tmp/bot/"
  cp -R "$REPO/contrib/bot/fixtures" "$tmp/bot/"
  (cd "$tmp/bot" && HOME="$tmp" "$NPM_BIN" ci --ignore-scripts --omit=dev --no-audit --no-fund --cache "$tmp/.npm" >/dev/null)
  rm -rf "$tmp/.npm"
  chown -R root:wheel "$tmp"
  chmod -R u=rwX,go=rX "$tmp"
  rm -rf "$CODE_DIR.old"
  [ -e "$CODE_DIR" ] && mv "$CODE_DIR" "$CODE_DIR.old"
  mv "$tmp" "$CODE_DIR"
  rm -rf "$CODE_DIR.old"
  echo "Installed the music bot in $CODE_DIR (root-owned)."
}

# copy one file from your state folder into roombot's, written by roombot itself (0600)
copy_state() {
  local name="$1" src="$ADMIN_HOME/$STATE_REL/$1"
  [ -f "$src" ] && [ ! -L "$src" ] || return 1
  as_admin /bin/cat "$src" | as_bot /bin/sh -c 'umask 077; d="$HOME/'"$STATE_REL"'"; mkdir -p "$d"; f="$d/$1"; [ -L "$f" ] && rm -f "$f"; cat > "$f.new" && mv -f "$f.new" "$f"' _ "$name" || { echo "  couldn't copy $name"; return 1; }
  echo "  copied $name"
}

# the booth token, from your Keychain into roombot's secrets.json as BOOTH_TOKEN: read as you, merged by roombot itself
# (the token travels on a pipe, never on a command line)
copy_token() {
  local token
  token="$(as_admin security find-generic-password -s "$KEYCHAIN_ITEM" -w 2>/dev/null || true)"
  [ -n "$token" ] || { echo "  no $KEYCHAIN_ITEM in your Keychain (the booth makes it): BOOTH_TOKEN not copied"; return 1; }
  case "$token" in zb1_*) ;; *) echo "  $KEYCHAIN_ITEM doesn't start zb1_: not copied"; return 1;; esac
  printf '%s' "$token" | as_bot "$NODE_BIN" -e '
    const fs = require("fs"), path = require("path");
    const dir = path.join(process.env.HOME, process.argv[1]), file = path.join(dir, "secrets.json");
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    if (fs.existsSync(file) && fs.lstatSync(file).isSymbolicLink()) fs.rmSync(file);
    const s = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
    s.BOOTH_TOKEN = fs.readFileSync(0, "utf8").trim();
    fs.writeFileSync(file + ".new", JSON.stringify(s, null, 2) + "\n", { mode: 0o600 });
    fs.chmodSync(file + ".new", 0o600);
    fs.renameSync(file + ".new", file);
  ' "$STATE_REL" || { echo "  couldn't save BOOTH_TOKEN"; return 1; }
  echo "  copied BOOTH_TOKEN from your Keychain ($KEYCHAIN_ITEM)"
}

restart_bot() {
  local U
  U=$(uid_of)
  as_bot launchctl kickstart -k "gui/$U/$LABEL" </dev/null 2>/dev/null && echo "Restarted the music bot." || echo "It starts next time $USER_NAME logs in."
}

if [ "${1:-}" = --update ]; then
  [ -d "$CODE_DIR" ] || { echo "The music bot isn't installed yet: run without --update first."; exit 1; }
  install_code
  restart_bot
  exit 0
fi
if [ "${1:-}" = --secrets ]; then
  copy_state secrets.json || echo "  no $ADMIN_HOME/$STATE_REL/secrets.json"
  copy_state config.json || true
  copy_token || true
  restart_bot
  exit 0
fi

# 1. one bot at a time: stop the copy that ran as you
stop_admin_bot

# 2. the code
install_code

# 3. state and secrets: roombot's own folder, filled from yours if you had one, and the booth token
as_bot /bin/sh -c 'umask 077; mkdir -p "$HOME/'"$STATE_REL"'"' </dev/null
if [ -d "$ADMIN_HOME/$STATE_REL" ]; then
  echo "Copying the music bot's state from $ADMIN_HOME/$STATE_REL:"
  copy_state secrets.json || true
  copy_state config.json || true
  if [ -f "$ADMIN_HOME/$STATE_REL/bot.db" ]; then
    # the database must be quiet to copy: the bot that ran as you was stopped above, and a leftover journal means it
    # stopped mid-write (copying bot.db alone would copy a half-written database)
    if ls "$ADMIN_HOME/$STATE_REL"/bot.db-* >/dev/null 2>&1; then
      echo "  not copying bot.db: a journal file is next to it. Run the bot as you once more, stop it cleanly, then: sudo contrib/bot/setup-mac.sh"
    elif as_bot /bin/test -e "$HOME_DIR/$STATE_REL/bot.db" </dev/null; then
      echo "  not copying bot.db: $USER_NAME already has one (its pieces are the ones posted)"
    else
      copy_state bot.db || true
    fi
  fi
fi
copy_token || true
if ! as_bot /bin/test -s "$HOME_DIR/$STATE_REL/secrets.json" </dev/null; then
  cat <<NOSECRETS
No secrets yet. Enter them as roombot (it asks for each, typing hidden):
  sudo -u $USER_NAME -H $NODE_BIN $CODE_DIR/bot/secrets.mjs
NOSECRETS
fi

# 4. the LaunchAgent, written by roombot into its own Library (it can only ever affect itself there)
as_bot /bin/sh -c "umask 022; mkdir -p \"\$HOME/Library/LaunchAgents\"; p=\"\$HOME/Library/LaunchAgents/$LABEL.plist\"; [ -L \"\$p\" ] && rm -f \"\$p\"; cat > \"\$p\"" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$NODE_BIN</string><string>$CODE_DIR/bot/main.mjs</string></array>
  <key>WorkingDirectory</key><string>$CODE_DIR/bot</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$BREW_BIN:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$HOME_DIR/$STATE_REL/launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/$STATE_REL/launchd.log</string>
</dict>
</plist>
PL
U=$(uid_of)
if launchctl print "gui/$U" >/dev/null 2>&1; then
  # loaded by roombot itself, so root never opens a path roombot controls
  as_bot launchctl bootout "gui/$U/$LABEL" </dev/null 2>/dev/null || true
  as_bot launchctl bootstrap "gui/$U" "$PLIST" </dev/null && echo "Music bot started in $USER_NAME's session."
else
  echo "The music bot starts the next time $USER_NAME logs in."
fi

cat <<DONE

Done. Left for you:
  1. $USER_NAME must be logged in (fast user switching) for its LaunchAgents to run, as for the room bot.
  2. The booth runs as you, on 127.0.0.1:8794; the bot waits for it at start-up and while it's closed.
  3. Run these as shown: roombot opens its own files, and cat -v defuses anything a stranger's post put in them.
     Check:   sudo -u $USER_NAME -H $NODE_BIN $CODE_DIR/bot/main.mjs --check </dev/null 2>&1 | cat -v
     Status:  sudo -u $USER_NAME -H $NODE_BIN $CODE_DIR/bot/main.mjs --status </dev/null 2>&1 | cat -v
     Pause:   sudo -u $USER_NAME touch $HOME_DIR/$STATE_REL/PAUSE     (rm it to resume)
     Logs:    sudo -u $USER_NAME tail -f $HOME_DIR/$STATE_REL/bot.log | cat -v
  4. Once it runs here, delete your own copies of its secrets: rm $ADMIN_HOME/$STATE_REL/secrets.json
DONE
