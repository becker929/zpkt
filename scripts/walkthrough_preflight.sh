#!/usr/bin/env bash
# Read-only checks before the manual walkthrough (docs/walkthrough.md).
#
#   scripts/walkthrough_preflight.sh           # everything
#   scripts/walkthrough_preflight.sh --no-ui   # skip reading Live's window title and menu through System Events
#
# It reports: the checkout and its uv environment, which ports listen and which checkout each server runs from,
# the supervisor loops, whether Live runs and which set is in front (window title and the Save menu item only),
# the MiniLab, the files the walkthrough uses, other agents, and free disk.
# It never starts or stops anything, never writes a file, and never talks to Live's bridge (port 16619 is only
# looked up with lsof). Exit 0 when nothing needs attention, 1 when a WARN line was printed.
# Written for macOS's /bin/bash 3.2: no associative arrays, no mapfile.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UI=1
for arg in "$@"; do
  case "$arg" in
    --no-ui) UI=0 ;;
    -h | --help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

FINISH="HW002_121_pp_finish"
SETS="$HOME/Music/zpkt/sets"
WARNINGS=0

ok() { printf '  ok    %s\n' "$*"; }
info() { printf '  --    %s\n' "$*"; }
warn() {
  printf '  WARN  %s\n' "$*"
  WARNINGS=$((WARNINGS + 1))
}
section() { printf '\n== %s ==\n' "$*"; }

# The checkout a process runs from: the first ~/Desktop/<folder> or ~/<folder> path in its command line, else its
# working folder.
checkout_of() {
  local pid=$1 cmd cwd hit
  cmd=$(ps -o command= -p "$pid" 2>/dev/null)
  hit=$(printf '%s\n' "$cmd" | grep -oE "($HOME|~)/Desktop/[^/ ]+" | head -n 1)
  if [ -z "$hit" ]; then
    hit=$(printf '%s\n' "$cmd" | grep -oE "($HOME|~)/(zpkt-web|tailnet-home|gemini-web|journal-site)" | head -n 1)
  fi
  if [ -z "$hit" ]; then
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)
    hit="${cwd:-?} (working folder)"
  fi
  printf '%s\n' "${hit/#\~/$HOME}"
}

describe_pid() {
  local pid=$1 cmd
  cmd=$(ps -o command= -p "$pid" 2>/dev/null | cut -c1-110)
  printf 'pid %s, from %s\n            %s\n' "$pid" "$(checkout_of "$pid")" "$cmd"
}

# ---------------------------------------------------------------------------------------------------------------------
section "Checkout"
info "repo $REPO"
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$REPO" branch --show-current)
  head=$(git -C "$REPO" log --oneline -1)
  if [ "$branch" = "upgrade/integrate" ]; then ok "branch $branch ($head)"; else warn "branch is '$branch', not upgrade/integrate"; fi
  if [ -z "$(git -C "$REPO" status --porcelain)" ]; then ok "no uncommitted changes"; else info "uncommitted changes: $(git -C "$REPO" status --porcelain | wc -l | tr -d ' ') files (git status)"; fi
else
  warn "$REPO is not a git checkout"
fi

# ---------------------------------------------------------------------------------------------------------------------
section "uv environment (uv sync --all-extras)"
UV=$(command -v uv 2>/dev/null || true)
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -n "$UV" ]; then ok "uv: $UV ($("$UV" --version 2>/dev/null))"; else warn "uv not found (install it, or put ~/.local/bin on PATH)"; fi
if [ -d "$REPO/.venv" ]; then
  ok ".venv exists"
  for cmd in zpkt hands ears mlab; do
    if [ -x "$REPO/.venv/bin/$cmd" ]; then ok ".venv/bin/$cmd"; else warn ".venv/bin/$cmd missing: run uv sync --all-extras"; fi
  done
  site=$(ls -d "$REPO"/.venv/lib/python3*/site-packages 2>/dev/null | head -n 1)
  for pkg in librosa:audio pyloudnorm:audio cbor2:serum pedalboard:serum google/generativeai:gemini pytest:dev; do
    dir=${pkg%%:*}
    extra=${pkg##*:}
    if [ -n "$site" ] && [ -d "$site/$dir" ]; then ok "$dir ($extra)"; else warn "$dir missing (the $extra extra): run uv sync --all-extras"; fi
  done
  if [ -n "$UV" ]; then
    dry=$(cd "$REPO" && "$UV" sync --all-extras --locked --offline --dry-run 2>&1 | tail -n 1)
    case "$dry" in
      *"Would make no changes"*) ok "uv sync --all-extras would change nothing" ;;
      *) warn "uv sync --all-extras would change the environment ($dry): run it" ;;
    esac
  fi
else
  warn "no .venv: run 'cd $REPO && uv sync --all-extras'"
fi
for old in hands/.venv ears/.venv ears/mlab/.venv; do
  if [ -d "$REPO/$old" ]; then info "$old exists in this checkout but is no longer used (the root .venv is)"; fi
done
link=$(readlink "$HOME/.local/bin/hands" 2>/dev/null || true)
if [ -n "$link" ]; then info "~/.local/bin/hands (what Zpkt web runs) -> $link"; else info "~/.local/bin/hands is not a link"; fi

# ---------------------------------------------------------------------------------------------------------------------
section "Ports (lsof only; nothing is contacted)"
# name|protocol|port
while IFS='|' read -r name proto port; do
  [ -z "$name" ] && continue
  if [ "$proto" = tcp ]; then
    pids=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u)
  else
    pids=$(lsof -nP -iUDP:"$port" -t 2>/dev/null | sort -u)
  fi
  label=$(printf '%-5s %-5s %s' "$proto" "$port" "$name")
  if [ -z "$pids" ]; then
    info "$label: free"
  else
    for pid in $pids; do
      printf '  on    %s: %s\n' "$label" "$(describe_pid "$pid")"
    done
  fi
done <<'PORTS'
Live's bridge (AbletonLiveMCP)|tcp|16619
mix desk|tcp|8985
mix desk pager datagrams|udp|8986
mix desk meter|udp|8987
arranger|tcp|8975
arranger, walkthrough copy|tcp|8976
harness|tcp|8787
harness, walkthrough copy|tcp|8877
Zpkt web|tcp|8789
Zpkt web (second port)|tcp|8797
image wall|tcp|8796
booth (music-bot)|tcp|8794
tailnet home page|tcp|8800
PORTS

desk_pids=$(lsof -nP -iTCP:8985 -sTCP:LISTEN -t 2>/dev/null | sort -u)
for pid in $desk_pids; do
  case "$(checkout_of "$pid")" in
    */zpkt-main) info "the desk on 8985 is the running one from zpkt-main: stop it before starting the upgraded desk (walkthrough step 7)" ;;
    */zpkt-upgrade) info "the desk on 8985 runs from zpkt-upgrade (the walkthrough's)" ;;
    *) info "the desk on 8985 runs from $(checkout_of "$pid")" ;;
  esac
done

# ---------------------------------------------------------------------------------------------------------------------
section "Supervisors"
loops=$(ps -axo pid=,command= | grep -E "while (true|:); do" | grep -v grep || true)
if [ -n "$loops" ]; then
  printf '%s\n' "$loops" | while read -r pid cmd; do info "loop pid $pid: $(printf '%s' "$cmd" | cut -c1-120)"; done
else
  info "no shell restart loops"
fi
hs_pid=$(pgrep -x Hammerspoon | head -n 1)
if [ -n "$hs_pid" ]; then
  kids=$(pgrep -P "$hs_pid" 2>/dev/null | tr '\n' ' ')
  info "Hammerspoon pid $hs_pid supervises the harness; its children: ${kids:-none}"
  for kid in $kids; do info "  child $(describe_pid "$kid")"; done
else
  info "Hammerspoon is not running (it supervises the harness)"
fi
if launchctl list 2>/dev/null | grep -q me.anthonybecker.zpkt-web; then info "launchd job me.anthonybecker.zpkt-web is loaded (Zpkt web)"; fi
if command -v tmux >/dev/null 2>&1; then
  sessions=$(tmux ls 2>/dev/null | cut -d: -f1 | tr '\n' ' ')
  info "tmux sessions: ${sessions:-none}"
fi

# ---------------------------------------------------------------------------------------------------------------------
section "Live"
live_pid=$(pgrep -x Live | head -n 1)
if [ -z "$live_pid" ]; then
  info "Live is not running"
else
  ok "Live is running (pid $live_pid)"
  if [ "$UI" = 0 ]; then
    info "window title and Save menu not read (--no-ui)"
  else
    title=$(osascript -e 'tell application "System Events" to get name of front window of process "Live"' 2>/dev/null)
    dialogs=$(osascript -e 'tell application "System Events" to tell process "Live"
  set n to 0
  repeat with w in every window
    try
      if (subrole of w as text) is "AXDialog" then set n to n + 1
    end try
  end repeat
  return n
end tell' 2>/dev/null)
    unsaved=$(osascript -e 'tell application "System Events" to tell process "Live" to get enabled of menu item "Save Live Set" of menu "File" of menu bar 1' 2>/dev/null)
    case "$unsaved" in
      true) unsaved_text="yes" ;;
      false) unsaved_text="no" ;;
      *) unsaved_text="unknown (no Accessibility grant for this terminal?)" ;;
    esac
    if [ -n "$title" ]; then ok "set in front: $title"; else info "no set window in front (a plug-in window, a dialog, or loading)"; fi
    info "unsaved changes: $unsaved_text"
    case "$dialogs" in
      "" | 0) ok "no dialog open in Live" ;;
      *) warn "$dialogs dialog(s) open in Live: look at Live before any step" ;;
    esac
    if [ "${title%\*}" = "$FINISH" ] && [ "$unsaved" != false ]; then
      warn "$FINISH is in front and may have unsaved changes: do walkthrough step 4 yourself before anything else"
    fi
  fi
fi
if ioreg -p IOUSB -w0 2>/dev/null | grep -qi minilab; then ok "MiniLab 3 is connected"; else info "no MiniLab on USB (the [you] desk steps need it)"; fi

# ---------------------------------------------------------------------------------------------------------------------
section "Files the walkthrough uses"
for f in "$FINISH" HW002_121_pp_walk HW002_121_pp_mix HW002_121_pp_loops; do
  if [ -f "$SETS/$f.als" ]; then ok "set $f.als ($(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$SETS/$f.als"))"; else info "no $SETS/$f.als"; fi
done
for p in \
  "$HOME/_agent_scratch/mixdesk/history/$FINISH.json" \
  "$SETS/state/$FINISH" \
  "$SETS/surfaces/$FINISH" \
  "$HOME/_agent_scratch/mixdesk/viz/analysis.json" \
  "$HOME/_agent_scratch/arranger/arrangements/short-8d2a2.json" \
  "$HOME/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/zpkt desk meter.amxd" \
  "$HOME/.cache/zpkt/models/dclap"; do
  if [ -e "$p" ]; then ok "${p/#$HOME/~}"; else info "missing: ${p/#$HOME/~}"; fi
done
backups=$(ls -d "$HOME"/_agent_scratch/walk/backup-* 2>/dev/null | tail -n 1)
if [ -n "$backups" ]; then ok "latest walkthrough backup: ${backups/#$HOME/~}"; else info "no walkthrough backup yet (step 5)"; fi
for l in "$HOME/_agent_scratch/zpkt-e2e" "$HOME/_agent_scratch/booth"; do
  if [ -L "$l" ] && [ ! -e "$l" ]; then
    info "${l/#$HOME/~} is a link to $(readlink "$l"), which is not there now"
  elif [ -e "$l" ]; then
    ok "${l/#$HOME/~} is reachable"
  else
    info "no ${l/#$HOME/~}"
  fi
done
for d in "$HOME/Desktop/music-bot" "$HOME/Desktop/zpkt-demo" "$HOME/Desktop/image-wall" "$HOME/zpkt-web"; do
  if [ -d "$d" ]; then ok "${d/#$HOME/~}"; else info "missing: ${d/#$HOME/~}"; fi
done
if command -v ffmpeg >/dev/null 2>&1; then ok "ffmpeg"; else info "no ffmpeg (the codec rows of mlab deliver and calibrate need it)"; fi

# ---------------------------------------------------------------------------------------------------------------------
section "Other agents"
gem=$(pgrep -lf "bin/gemini|gemini-cli" 2>/dev/null | grep -v GeminiMacOS || true)
if [ -n "$gem" ]; then
  warn "a Gemini CLI process runs; it may share Live: $(printf '%s' "$gem" | head -n 1 | cut -c1-100)"
else
  ok "no Gemini CLI process"
fi

# ---------------------------------------------------------------------------------------------------------------------
section "Disk"
free_gb=$(df -g / | awk 'NR == 2 {print $4}')
if [ "${free_gb:-0}" -ge 20 ]; then ok "$free_gb GiB free on /"; else warn "only ${free_gb:-?} GiB free on /: renders and bounces need room (see the disk-space notes)"; fi

printf '\n'
if [ "$WARNINGS" -eq 0 ]; then
  echo "preflight: nothing needs attention"
  exit 0
fi
echo "preflight: $WARNINGS line(s) marked WARN need attention"
exit 1
