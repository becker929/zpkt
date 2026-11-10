"""Phase 2: vertical packing. S copies of the canonical shape's content in one set.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_vertical.py 1 2 4 8

Per S: strip unused tracks, duplicate the kick and perc groups S-1 times (renamed
"S<k> ..."), save, reload, then export all tracks in one offline pass. Logs build,
save, load and export times, the set file size, Live's memory and the machine's swap.
"""
import os
import sys
import time

import pp
from pp import A, log

BEATS = 22 * 4.0
STRIP = ("1-01 - Lethal Storm", "SFX group", "Break group")   # muted in the canonical shape


def build(S):
    """One LOM call per phase, so the ~0.85 s round trip is paid a few times, not per track."""
    t = time.time()
    n = A.r(f"""
STRIP = {STRIP!r}
# Delete whole groups (that takes their children; Live refuses to delete a group's last child
# on its own), then loose tracks. Re-scan after each delete: indices shift.
def strip_one():
    for want_group in (True, False):
        for i, t in enumerate(song.tracks):
            if t.name in STRIP and t.is_foldable == want_group:
                song.delete_track(i)
                return True
    return False
while strip_one():
    pass
result = len(song.tracks)""")
    log("v_strip", time.time() - t, S=S, tracks=n)
    t = time.time()
    n = A.r(f"""
def idx(name):
    return [i for i, t in enumerate(song.tracks) if t.name == name][0]
for k in range({S} - 1):
    for g in ("perc group", "kick group"):
        song.duplicate_track(idx(g))
count = {{"kick group": 0, "perc group": 0}}
for t in song.tracks:
    for g in count:
        if t.is_foldable and t.name.startswith(g):
            count[g] += 1
            t.name = "S%02d %s" % (count[g], g)
result = len(song.tracks)""")
    log("v_duplicate", time.time() - t, S=S, tracks=n)
    return n


def main():
    sizes = [int(a) for a in sys.argv[1:]] or [1, 2, 4, 8]
    out = pp.DATA + "vertical/"
    os.makedirs(out, exist_ok=True)
    for S in sizes:
        name = f"HW002_121_pp_v{S:02d}"
        pp.copy_set(pp.CANON, name)
        pp.prepare_switch()
        pp.open_set(name)
        log("v_mem_before", 0, S=S, **pp.mem())
        n = build(S)
        t = time.time(); ok = pp.save(name); log("v_save", time.time() - t, S=S, wrote=str(ok),
                                                 mb=round(os.path.getsize(os.path.join(pp.PROJ, name + ".als")) / 1e6, 2))
        # reload from disk: switch away to a small set first so this is a real load
        pp.prepare_switch()
        pp.open_set("HW002_121_pp_render")
        pp.prepare_switch()
        t = time.time(); pp.open_set(name); log("v_load", time.time() - t, S=S, tracks=n, **pp.mem())
        t = time.time()
        pp.export(out + f"v{S:02d}.wav", 0.0, BEATS, "All Individual Tracks")
        files = [f for f in os.listdir(out) if f.startswith(f"v{S:02d} ")]
        log("v_export_all", time.time() - t, S=S, files=len(files), **pp.mem())


if __name__ == "__main__":
    main()
