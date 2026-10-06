"""E5: horizontal probes with automation written into the set file.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_e5_als.py template   # Live, once
  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_e5_als.py batch 1    # offline write + Live load + export
  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_e5_als.py batch 2

template: copy v01, delete everything after the 22-bar shape, Duplicate Time to P=16 patterns,
          save as HW002_121_pp_t16 (Edit-menu ops; every step guarded and read back).
batch k:  write a Reverb on "S01 perc group" with Dry/Wet stepped per pattern into a copy of the
          template (als_probe, offline), load it, export Main over all 16 patterns.
"""
import os
import sys
import time

import als_probe as X
import pp
from pp import A, TO, log

LEAD, PAT, P = 8.0, 80.0, 16
TEMPLATE = "HW002_121_pp_t16"
VALUES = {1: [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75],
          2: [0.0, 0.6, 0.0, 0.6, 0.0, 0.6, 0.0, 0.6, 0.0, 0.6, 0.0, 0.6, 0.0, 0.6, 0.0, 0.6]}


def last_event():
    return A.r("result = song.last_event_time")


END_SLACK = 2.0     # an automation breakpoint may sit just past the shape (seen: beat 89)


def kick_clips():
    """Kick clips overlapping the pattern area (end > LEAD): doubles exactly with each Duplicate Time."""
    return A.r(f"result = len([c for c in [t for t in song.tracks if t.name == 'kick'][0].arrangement_clips if c.end_time > {LEAD}])")


def patterns_now():
    """How many 80-beat patterns the open template already holds (1 if the song ends near 88)."""
    end = last_event()
    n = round((end - LEAD) / PAT)
    return max(1, n)


def duplicate_region(start, length):
    """Edit > Duplicate Time on [start, start+length). Verified by the caller from the clip layout:
    TO.duplicate's song-end check fails here because a breakpoint just past the shape is absorbed."""
    TO.select(start, length)
    if not A.menu("Edit", "Duplicate Time", tries=6):
        raise pp.Guard("Edit > Duplicate Time stayed disabled")
    time.sleep(1.0)


def template():
    """Build or (if TEMPLATE is already open and trimmed) continue building the P-pattern template."""
    front = pp.check("t:start")
    if front != TEMPLATE:                      # fresh build: copy v01 and trim it to the 22-bar shape
        pp.copy_set("HW002_121_pp_v01", TEMPLATE)
        pp.prepare_switch()
        t = time.time(); pp.open_set(TEMPLATE); log("e5_t_load", time.time() - t)
        pp.check("t:loaded", expect_front=TEMPLATE)
        end = last_event()
        if end > LEAD + PAT + END_SLACK:
            t = time.time(); TO.delete(LEAD + PAT, end - (LEAD + PAT)); log("e5_t_trim", time.time() - t)
            pp.check("t:trimmed", expect_front=TEMPLATE)
        end0 = last_event()
        if not (LEAD + PAT <= end0 <= LEAD + PAT + END_SLACK):
            raise pp.Guard(f"t: after trim the set ends at {end0}, expected {LEAD + PAT}..{LEAD + PAT + END_SLACK}")
    # continuing an open template: never trim; the pattern count comes from the song end
    n = patterns_now()
    while n < P:
        before = kick_clips()
        t = time.time(); duplicate_region(LEAD, n * PAT); log("e5_t_duplicate", time.time() - t, to_P=2 * n)
        n *= 2
        pp.check(f"t:dup{n}", expect_front=TEMPLATE)
        end, after = last_event(), kick_clips()
        if abs(end - (LEAD + n * PAT)) > 1e-6 or after != 2 * before:
            raise pp.Guard(f"t: after duplicating to {n}: end {end} (want {LEAD + n * PAT}), kick clips in patterns "
                           f"{after} (want {2 * before})")
    t = time.time(); ok = pp.save(TEMPLATE); log("e5_t_save", time.time() - t, wrote=str(ok))
    pp.check("t:saved", expect_front=TEMPLATE)


def write_batch(k):
    """Offline: template + donor Reverb on S01 perc group, Dry/Wet stepped per pattern."""
    t = time.time()
    donor = X.find_device(X.find_track(X.load(os.path.join(pp.PROJ, "HW002_121_pp_v04.als")), "S02 perc group"), "Reverb")
    tree = X.load(os.path.join(pp.PROJ, TEMPLATE + ".als"))
    track = X.find_track(tree, "S01 perc group")
    rev = X.add_device_from_donor(tree, track, donor)
    steps = [(0.0 if j == 0 else LEAD + j * PAT, v) for j, v in enumerate(VALUES[k])]
    X.set_steps(tree, track, rev, "MixDirect", steps)
    name = f"HW002_121_pp_x16_b{k}"
    X.save(tree, os.path.join(pp.PROJ, name + ".als"), overwrite=True)
    problems = X.check(os.path.join(pp.PROJ, name + ".als"))
    if problems:
        raise pp.Guard(f"als_probe check failed: {problems}")
    log("e5_write_als", time.time() - t, batch=k)
    return name


def batch(k):
    name = write_batch(k)
    pp.check(f"b{k}:start")
    pp.prepare_switch()
    t = time.time(); pp.open_set(name); log("e5_load", time.time() - t, batch=k, **pp.live_footprint_gb())
    pp.check(f"b{k}:loaded", expect_front=name)
    back = A.r("""
g = [t for t in song.tracks if t.name == "S01 perc group"][0]
rev = [d for d in g.devices if d.class_name == "Reverb"]
result = {"reverbs": len(rev), "dry_wet_now": round([p for p in rev[0].parameters if p.name == "Dry/Wet"][0].value, 3) if rev else None,
          "end": song.last_event_time}""")
    log("e5_readback", 0, batch=k, **back)
    out = pp.DATA + f"e5/b{k}.wav"
    t = time.time(); pp.export(out, 0.0, LEAD + P * PAT, "Main"); log("e5_export_main", time.time() - t, batch=k, P=P)
    pp.check(f"b{k}:exported", expect_front=name)


if __name__ == "__main__":
    if sys.argv[1] == "template":
        template()
    elif sys.argv[1] == "batch":
        batch(int(sys.argv[2]))
