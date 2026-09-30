#!/bin/zsh
# Bring up the headless Live rig: virtual display, no sleep, Live placed on
# screen, MCP port listening, audio clock running.
#
#   scripts/start_headless.sh            # full bring-up + checks
#   LIVE_APP="Ableton Live 12 Standard" scripts/start_headless.sh
#
# Needs: BetterDisplay (virtual display), Caffeine, the AbletonLiveMCP Remote
# Script enabled in Live, and Accessibility/Automation permission for the
# calling app (window placement goes through System Events).
set -euo pipefail

LIVE_APP=${LIVE_APP:-"Ableton Live 12 Suite"}
WIN_POS=${WIN_POS:-"80, 30"}
WIN_SIZE=${WIN_SIZE:-"2400, 1300"}
PORT=${ABLETON_TCP_PORT:-16619}
BOOT_TIMEOUT=${BOOT_TIMEOUT:-120}
REPO=${0:A:h:h}

step() { print -P "%B==>%b $*"; }
fail() { print -P "%F{red}FAIL%f $*" >&2; exit 1; }

step "Starting BetterDisplay and Caffeine"
open -g -a BetterDisplay
open -g -a Caffeine
sleep 3

step "Displays"
swift - <<'EOF'
import CoreGraphics
var n: UInt32 = 0; var d = [CGDirectDisplayID](repeating: 0, count: 8)
CGGetActiveDisplayList(8, &d, &n)
for i in 0..<Int(n) { print("   ", d[i], CGDisplayBounds(d[i]), CGDisplayIsMain(d[i]) != 0 ? "(main)" : "") }
EOF

# Caffeine drops and re-creates its assertion every ~10 s, so poll briefly.
# Capture before grepping: with pipefail, grep -q's early exit SIGPIPEs pmset.
caffeinated() { local a; a=$(pmset -g assertions); [[ $a == *"Caffeine prevents sleep"* ]]; }
for ((i = 0; i < 10; i++)); do
  caffeinated && break
  sleep 1
done
if caffeinated; then
  step "Caffeine is holding a sleep assertion"
else
  print "    warning: no Caffeine assertion — turn it on in the menu bar or the Mac may sleep"
fi

step "Launching $LIVE_APP (waiting up to ${BOOT_TIMEOUT}s for port $PORT)"
open -a "$LIVE_APP"
for ((i = 0; i < BOOT_TIMEOUT; i += 2)); do
  lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 2
done
lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 \
  || fail "port $PORT not listening. Is AbletonLiveMCP selected under Settings → Link, Tempo & MIDI? Is a dialog (crash recovery, updates) blocking Live's startup?"

step "Placing Live's window at {$WIN_POS} size {$WIN_SIZE}"
osascript -e "tell application \"System Events\" to tell process \"Live\"
  set position of window 1 to {$WIN_POS}
  set size of window 1 to {$WIN_SIZE}
end tell" >/dev/null || fail "window placement failed; grant Accessibility/Automation to this app"

step "Checking MCP control and the audio clock"
cd "$REPO"
export PATH=$HOME/.local/bin:$PATH
uv run python - <<'EOF' || fail "Live is up but not usable (see above)"
import sys, time
from hands.transport import LiveMcpTransport
t = LiveMcpTransport()
res = t.execute('result = {"tempo": song.tempo, "tracks": len(song.tracks)}')
if res.status != "ok":
    sys.exit(f"    MCP error: {res.error}")
print("    set:", res.result)
t.execute("song.start_playing()"); time.sleep(1.2)
pos = t.execute("song.current_song_time").result
t.execute("song.stop_playing()")
if not pos:
    sys.exit("    audio clock frozen (current_song_time = 0): no audio device. "
             "Check the USB interface and Live's Settings → Audio.")
print(f"    audio clock ok ({pos:.2f} beats in 1.2 s)")
EOF

step "Ready"
