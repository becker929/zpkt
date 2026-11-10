"""Cut HW002_121_full into a version that keeps given source bars, then render.

uv run python arrange.py VERSION_ID "125-132" "95-96,125-138" ...
Each version: copy the set, open it, Delete Time over every gap (latest first,
checking last_event_time drops by exactly the gap), save, render, save.
"""
import json
import os
import shutil
import subprocess
import sys
import time

from hands.recorder import record_arrangement
from hands.transport import LiveMcpTransport

PROJ = os.path.expanduser("~/_agent_scratch/HW002")
SRC = os.path.join(PROJ, "HW002_121_full.als")
OUT = os.path.expanduser("~/_agent_scratch/renders/versions")
T = LiveMcpTransport()


def r(code):
    x = T.execute(code)
    if x.status != "ok":
        raise RuntimeError(f"{code[:70]!r}: {x.error}")
    return x.result


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30).stdout.strip()


def menu(menu_name, item, tries=6):
    for _ in range(tries):
        en = osa(f'tell application "System Events" to tell process "Live" to get enabled of menu item "{item}" of menu "{menu_name}" of menu bar 1')
        if en == "true":
            osa(f'tell application "System Events" to tell process "Live" to click menu item "{item}" of menu "{menu_name}" of menu bar 1')
            return True
        time.sleep(0.4)
    return False


def front():
    return osa('tell application "System Events" to get name of front window of process "Live"')


def open_set(path, name):
    menu("File", "Save Live Set")
    time.sleep(1.5)
    subprocess.run(["open", "-a", "Ableton Live 12 Suite", path])
    for _ in range(90):
        time.sleep(1)
        if front() == name:
            break
    else:
        raise RuntimeError(f"Live did not open {name}; front window is {front()!r}")
    for _ in range(30):
        try:
            r("song.tempo")
            return
        except RuntimeError:
            time.sleep(1)


def delete_bars(a, b):
    """Delete source-grid bars a..b (1-based, inclusive) at their current position."""
    start, length = (a - 1) * 4.0, (b - a + 1) * 4.0
    before = r("song.last_event_time")
    r("song.stop_playing()")
    r('Live.Application.get_application().view.show_view("Arranger")')
    r('Live.Application.get_application().view.focus_view("Arranger")')
    r(f"song.loop_start = {start}")
    r(f"song.loop_length = {length}")
    for _ in range(4):
        menu("Edit", "Select Loop")
        time.sleep(0.3)
        if menu("Edit", "Delete Time", tries=3):
            time.sleep(0.8)
            after = r("song.last_event_time")
            if abs((before - after) - length) < 1e-6:
                return
            raise RuntimeError(f"delete {a}-{b}: last event moved {before - after}, expected {length}")
    raise RuntimeError(f"Delete Time stayed disabled for bars {a}-{b}")


def make(vid, segs):
    name = f"HW002_121_v_{vid}"
    path = os.path.join(PROJ, name + ".als")
    if front() == name:  # see arrange4.build: never re-open the same set in place
        open_set(SRC, "HW002_121_full")
    shutil.copyfile(SRC, path)
    open_set(path, name)
    gaps, prev = [], 0
    for a, b in segs:
        if a > prev + 1:
            gaps.append((prev + 1, a - 1))
        prev = b
    for a, b in reversed(gaps):  # latest first, so earlier bars keep their numbers
        delete_bars(a, b)
    bars = sum(b - a + 1 for a, b in segs)
    fixes = restore_automation(segs)
    r("song.loop = False")
    menu("File", "Save Live Set")
    time.sleep(1.5)
    os.makedirs(OUT, exist_ok=True)
    wav = record_arrangement(transport=T, filename=f"{vid}.wav", duration_beats=bars * 4.0, output_dir=OUT, tail_beats=2.0)
    menu("File", "Save Live Set")
    time.sleep(1.5)
    return {"id": vid, "set": path, "segments": segs, "bars": bars, "raw": wav, "automation_fixes": fixes}


def restore_automation(segs):
    """Make every automated parameter at each segment start match the full set.

    Delete Time drops an envelope whose breakpoints all fall in the cut, and
    the parameter then sits at its static value (the kick scoop EQ stuck on).
    Static ones are set back; a still-automated mismatch is an error."""
    import autostate as AS
    ref = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "full_autostate.json")))
    names = [(p["track"], p["param"]) for p in ref["params"]]
    starts, pos = [], 0
    for a, b in segs:
        starts.append((a, pos * 4.0))
        pos += b - a + 1
    fixes = []
    for attempt in range(2):
        cur = AS.values_at(r, ref["params"], [beat for _, beat in starts])
        bad = []
        for (src, beat) in starts:
            want = ref["values"][str(src)]
            for i, p in enumerate(ref["params"]):
                if abs(cur[beat][i] - want[i]) > 1e-3:
                    bad.append((src, i, want[i], cur[beat][i]))
        if not bad:
            return fixes
        if attempt:
            raise RuntimeError(f"automation still differs: {bad}")
        for i in sorted({i for _, i, _, _ in bad}):
            wants = {ref["values"][str(src)][i] for src, _ in starts}
            st, _ = AS.state(r, ref["params"][i]["path"])
            if st != 0 or len(wants) != 1:
                raise RuntimeError(f"cannot fix {names[i]} statically: state {st}, wants {wants}")
            AS.set_static(r, ref["params"][i]["path"], wants.pop())
            fixes.append(names[i])
    return fixes


if __name__ == "__main__":
    vid = sys.argv[1]
    segs = [tuple(int(v) for v in s.split("-")) for s in sys.argv[2].split(",")]
    res = make(vid, segs)
    print(json.dumps(res))
