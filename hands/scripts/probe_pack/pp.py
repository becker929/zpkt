"""Probe-packing helpers: timed Live operations for the render-packing experiment.

Builds on arrange_prototype (LOM over AbletonLiveMCP + Edit-menu time ops). Every
timed step appends a JSON line to ~/_agent_scratch/probepack/bench.jsonl.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "arrange_prototype"))
import arrange as A  # noqa: E402
import timeops as TO  # noqa: E402

PROJ = A.PROJ
DATA = os.path.expanduser("~/_agent_scratch/probepack/")
EXPORT = os.path.join(HERE, "..", "..", "skills", "ableton-live-control", "scripts", "export_audio.applescript")
CANON = "HW002_121_v_b43-01-splash-every-8-bars-30s"
os.makedirs(DATA, exist_ok=True)


def live_rss_gb():
    pid = subprocess.run(["pgrep", "-x", "Live"], capture_output=True, text=True).stdout.split()[0]
    kb = int(subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True).stdout)
    return round(kb / 1048576, 3)


def log(step, seconds, **kw):
    row = {"t": time.strftime("%FT%T"), "step": step, "s": round(seconds, 3), "rss_gb": live_rss_gb(), **kw}
    open(DATA + "bench.jsonl", "a").write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)
    return row


def timed(step, fn, *a, meta=None):
    t = time.time()
    out = fn(*a)
    log(step, time.time() - t, **(meta or {}))
    return out


def copy_set(src_name, dst_name):
    shutil.copyfile(os.path.join(PROJ, src_name + ".als"), os.path.join(PROJ, dst_name + ".als"))
    return os.path.join(PROJ, dst_name + ".als")


def open_set(name):
    """Open a set and wait until the window title and the LOM both answer (no save first:
    call prepare_switch() before timing this, or Live may ask about unsaved changes)."""
    subprocess.run(["open", "-a", "Ableton Live 12 Suite", os.path.join(PROJ, name + ".als")])
    for _ in range(1200):
        if A.front() == name:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f"Live did not open {name}; front window is {A.front()!r}")
    for _ in range(300):
        try:
            A.r("song.tempo")
            return
        except RuntimeError:
            time.sleep(0.1)


def prepare_switch():
    """Save the current set (untimed) so the next open never meets an unsaved-changes prompt."""
    cur = A.front()
    if cur and os.path.exists(os.path.join(PROJ, cur + ".als")):
        save(cur)


def save(name):
    """Save and wait until the .als file is rewritten (mtime changes). Returns False if it never was."""
    path = os.path.join(PROJ, name + ".als")
    before = os.path.getmtime(path)
    en = A.osa('tell application "System Events" to tell process "Live" to get enabled of menu item "Save Live Set" of menu "File" of menu bar 1')
    if en != "true":
        return "clean"            # nothing changed: Live greys the item out
    A.menu("File", "Save Live Set")
    for _ in range(600):
        try:                      # Live replaces the file, so it is briefly missing
            if os.path.getmtime(path) != before:
                return True
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    return False


CLOSE_DIALOGS_OSA = '''tell application "System Events" to tell process "Live"
  try
    perform action "AXPress" of (first button of splitter group 1 of window "Save" whose title is "Cancel")
  end try
  delay 0.5
  try
    perform action "AXPress" of (first button of group 1 of window "Export Audio/Video" whose description is "Cancel")
  end try
end tell'''


def close_dialogs():
    """Cancel a leftover Save panel / Export dialog (an interrupted export leaves both open)."""
    A.osa(CLOSE_DIALOGS_OSA)
    time.sleep(0.5)


def export(out_path, start_beat, length_beats, mode="Main", tries=2):
    """Offline export via Live's Export dialog. Range = the arrangement selection (no slider typing).

    The target must be empty (no file starting with the out name in its folder): re-exporting over
    files makes Live trash old files and de-duplicate names. If the script errors but the render
    wrote its files and no dialog is left, that is a success (the error came from the window-closing
    race). Retry only when nothing was written. Returns the written .wav names."""
    folder = os.path.dirname(out_path)
    os.makedirs(folder, exist_ok=True)
    prefix = os.path.splitext(os.path.basename(out_path))[0]
    if any(f.startswith(prefix) for f in os.listdir(folder)):
        raise Guard(f"export target not empty: {prefix}* already in {folder}")
    err = ""
    for attempt in range(tries):
        t0 = time.time()
        TO.select(start_beat, length_beats)
        r = subprocess.run(["osascript", EXPORT, out_path, "WAV", "32", "44100", "0", mode, "-1"],
                           capture_output=True, text=True, timeout=900)
        written = sorted(f for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(".wav")
                         and os.path.getmtime(os.path.join(folder, f)) >= t0 - 1)
        if r.returncode == 0 and written:
            for _ in range(120):          # the progress/Export windows close a moment after the file lands
                if dialogs() == 0:
                    return written
                time.sleep(0.5)
            raise Guard(f"export wrote {len(written)} files but a dialog stayed open for 60 s")
        err = r.stderr.strip()[-400:]
        if written:
            time.sleep(3)
            if dialogs() != 0:
                close_dialogs()
            if dialogs() != 0:
                raise Guard(f"export wrote {len(written)} files but a dialog stayed open: {err}")
            log("export_script_error_files_ok", time.time() - t0, files=len(written), err=err[-120:])
            return written
        close_dialogs()
        if dialogs() != 0:
            raise Guard(f"export failed and a dialog stayed open: {err}")
    raise RuntimeError(f"export failed, nothing written: {err}")


def mem():
    """Machine memory state: swap used, compressed and free memory (GB)."""
    sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    used = float(sw.split("used = ")[1].split("M")[0]) / 1024
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout

    def pages(label):
        line = next(l for l in vm.splitlines() if l.startswith(label))
        return int(line.split(":")[1].strip().rstrip(".")) * 16384 / 1073741824
    return {"swap_used_gb": round(used, 2), "compressed_gb": round(pages("Pages occupied by compressor"), 2),
            "free_gb": round(pages("Pages free"), 2)}


def record(name, length_beats):
    """Real-time resampling record (the pipeline's current method)."""
    return A.record_arrangement(transport=A.T, filename=name + ".wav", duration_beats=length_beats,
                                output_dir=DATA + "takes", tail_beats=2.0)


# ---------------------------------------------------------------- guardrails
class Guard(RuntimeError):
    """Live is not in the state a step expects. Stop; do not continue the run."""


DIALOGS_OSA = '''tell application "System Events" to tell process "Live"
  set n to 0
  repeat with w in every window
    try
      if subrole of w is "AXDialog" then set n to n + 1
    end try
  end repeat
  return n
end tell'''


def dialogs():
    out = A.osa(DIALOGS_OSA)
    return int(out) if out.strip().isdigit() else -1


def check(where, expect_front=None, ours=True):
    """Pre/post-flight: no dialog, Live answers, the expected (or one of our) sets in front."""
    n = dialogs()
    if n != 0:
        raise Guard(f"{where}: {n} dialog(s) open in Live (or Live not reachable)")
    front = A.front()
    if expect_front and front != expect_front:
        raise Guard(f"{where}: front set is {front!r}, expected {expect_front!r}")
    if ours and not front.startswith(("HW002_121_pp", "HW002_121_v_")):
        raise Guard(f"{where}: front set {front!r} is not one of ours; another agent may be using Live")
    try:
        A.r("result = 1")
    except RuntimeError as e:
        raise Guard(f"{where}: Live does not answer LOM: {e}")
    return front


def duplicate_submixes(S):
    """Make S submixes from the stripped content, one submix per LOM call (each well under 12 s)."""
    for k in range(S - 1):
        t = time.time()
        A.r('''
def idx(name):
    return [i for i, t in enumerate(song.tracks) if t.name == name][0]
song.duplicate_track(idx("perc group"))
song.duplicate_track(idx("kick group"))
result = len(song.tracks)''')
        log("dup_one_submix", time.time() - t, k=k + 2)
    A.r('''
count = {"kick group": 0, "perc group": 0}
for t in song.tracks:
    for g in count:
        if t.is_foldable and t.name.startswith(g):
            count[g] += 1
            t.name = "S%02d %s" % (count[g], g)
result = count''')
    return A.r("result = len(song.tracks)")


def live_footprint_gb():
    """Live's memory incl. compressed pages (top's MEM), which RSS undercounts under compression."""
    pid = subprocess.run(["pgrep", "-x", "Live"], capture_output=True, text=True).stdout.split()[0]
    out = subprocess.run(["top", "-l", "1", "-pid", pid, "-stats", "mem,cmprs"], capture_output=True, text=True).stdout
    mem, cmp = out.strip().splitlines()[-1].split()[:2]

    def gb(v):
        unit = v[-1]
        num = float(v[:-1].rstrip("+-"))
        return round(num / 1024 if unit == "M" else num if unit == "G" else num / 1048576, 2)
    return {"live_mem_gb": gb(mem), "live_compressed_gb": gb(cmp)}


def live_running_ls():
    """LaunchServices' view: right after a quit it can still say running, and `open` then fails (-600)."""
    out = subprocess.run(["osascript", "-e", 'application "Ableton Live 12 Suite" is running'],
                         capture_output=True, text=True).stdout.strip()
    return out == "true"


def launch_live(tries=5):
    """`open` Live, checking the result; retry while LaunchServices still holds the old instance."""
    for k in range(tries):
        r = subprocess.run(["open", "-a", "Ableton Live 12 Suite"], capture_output=True, text=True)
        if r.returncode == 0:
            return
        time.sleep(3 + 2 * k)
    raise Guard(f"launch: open failed {tries} times: {r.stderr.strip()[-200:]}")


def restart_live(timeout=240):
    """Quit and relaunch Live (current set must be saved). Waits for the MCP bridge to answer."""
    cur = A.front()
    if cur and os.path.exists(os.path.join(PROJ, cur + ".als")):
        save(cur)
    if dialogs() != 0:
        raise Guard("restart: dialog open before quit")
    subprocess.run(["osascript", "-e", 'tell application "Ableton Live 12 Suite" to quit'], timeout=60)
    for _ in range(120):
        if subprocess.run(["pgrep", "-x", "Live"], capture_output=True).returncode != 0 and not live_running_ls():
            break
        time.sleep(1)
    else:
        raise Guard("restart: Live did not quit (a prompt may be open)")
    launch_live()
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            A.r("result = 1")
            return time.time() - t0
        except Exception:
            time.sleep(2)
    raise Guard("restart: Live did not answer LOM after relaunch")
