"""Phase 3: reuse a packed set without reloading, and horizontal patterns.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_phase3.py reuse horiz

reuse: on the S=4 set, three rounds of (one batched LOM edit + one all-tracks export);
       S01 stays untouched, S02-S04 get a Reverb with a different Dry/Wet each round.
horiz: on a copy of the S=1 set, Duplicate Time to 2 and 4 patterns, export Main each
       time, then give each pattern its own Reverb Dry/Wet through clip envelopes.
"""
import os
import sys
import time

import pp
from pp import A, TO, log

LEAD, PAT = 8.0, 80.0          # beats: 2-bar lead-in, 20-bar pattern


def reuse():
    name = "HW002_121_pp_v04"
    pp.check("reuse:start")
    pp.prepare_switch()
    t = time.time(); pp.open_set(name); log("r_load", time.time() - t, S=4, **pp.live_footprint_gb())
    pp.check("reuse:loaded", expect_front=name)
    out = pp.DATA + "reuse/"
    os.makedirs(out, exist_ok=True)
    for k, wets in enumerate([(0.1, 0.2, 0.3), (0.3, 0.4, 0.5), (0.5, 0.6, 0.7)], 1):
        t = time.time()
        A.r(f"""
WETS = {list(wets)!r}
for j, w in enumerate(WETS):
    g = [t for t in song.tracks if t.name == "S%02d perc group" % (j + 2)][0]
    rev = [d for d in g.devices if d.class_name == "Reverb"]
    if not rev:
        g.insert_device("Reverb", len(list(g.devices)))
        rev = [d for d in g.devices if d.class_name == "Reverb"]
    p = [p for p in rev[0].parameters if p.name == "Dry/Wet"][0]
    p.value = p.min + w * (p.max - p.min)
result = True""")
        log("r_edit_batch", time.time() - t, round=k)
        pp.check(f"reuse:edited{k}", expect_front=name)
        t = time.time()
        pp.export(out + f"b{k}.wav", 0.0, LEAD + PAT, "All Individual Tracks")
        log("r_export_all", time.time() - t, round=k, S=4, **pp.live_footprint_gb())
        pp.check(f"reuse:exported{k}", expect_front=name)
    pp.save(name)


def horiz():
    name = "HW002_121_pp_h"
    pp.copy_set("HW002_121_pp_v01", name)
    pp.check("horiz:start")
    pp.prepare_switch()
    t = time.time(); pp.open_set(name); log("h_load", time.time() - t, P=1)
    pp.check("horiz:loaded", expect_front=name)
    out = pp.DATA + "horiz/"
    os.makedirs(out, exist_ok=True)
    t = time.time(); pp.export(out + "p1.wav", 0.0, LEAD + PAT, "Main"); log("h_export_main", time.time() - t, P=1); pp.check("horiz:p1", expect_front=name)
    t = time.time(); TO.duplicate(LEAD, PAT); log("h_duplicate_time", time.time() - t, to_P=2); pp.check("horiz:dup2", expect_front=name)
    t = time.time(); pp.export(out + "p2.wav", 0.0, LEAD + 2 * PAT, "Main"); log("h_export_main", time.time() - t, P=2); pp.check("horiz:p2", expect_front=name)
    t = time.time(); TO.duplicate(LEAD, 2 * PAT); log("h_duplicate_time", time.time() - t, to_P=4); pp.check("horiz:dup4", expect_front=name)
    t = time.time(); pp.export(out + "p4.wav", 0.0, LEAD + 4 * PAT, "Main"); log("h_export_main", time.time() - t, P=4); pp.check("horiz:p4", expect_front=name)
    # per-pattern settings through clip envelopes: Reverb Dry/Wet = 0, 0.2, 0.4, 0.6 by pattern
    t = time.time()
    n = A.r(f"""
LEAD, PAT = {LEAD}, {PAT}
made = 0
for t in song.tracks:
    if t.is_foldable or not t.is_grouped or t.group_track.name != "S01 perc group":
        continue
    if not [d for d in t.devices if d.class_name == "Reverb"]:
        t.insert_device("Reverb", len(list(t.devices)))
    rev = [d for d in t.devices if d.class_name == "Reverb"][0]
    p = [p for p in rev.parameters if p.name == "Dry/Wet"][0]
    for c in t.arrangement_clips:
        k = int((c.start_time - LEAD) // PAT)
        if k < 0:
            continue
        env = c.automation_envelope(p) or c.create_automation_envelope(p)
        env.insert_step(0.0, c.length, p.min + 0.2 * k * (p.max - p.min))
        made += 1
result = made""")
    log("h_clip_envelopes", time.time() - t, P=4, envelopes=n)
    pp.check("horiz:envelopes", expect_front=name)
    # read back: Dry/Wet value at the middle of each pattern on perc 2
    back = A.r(f"""
LEAD, PAT = {LEAD}, {PAT}
t = [t for t in song.tracks if t.name == "perc 2" and t.is_grouped and t.group_track.name == "S01 perc group"][0]
p = [p for p in [d for d in t.devices if d.class_name == "Reverb"][0].parameters if p.name == "Dry/Wet"][0]
out = []
for c in t.arrangement_clips:
    env = c.automation_envelope(p)
    out.append([round(c.start_time, 1), round(env.value_at_time(0.5), 3) if env else None])
result = out""")
    log("h_envelope_readback", 0, values=str(back))
    t = time.time(); pp.export(out + "p4_env.wav", 0.0, LEAD + 4 * PAT, "Main"); log("h_export_main", time.time() - t, P=4, env=1)
    pp.check("horiz:done", expect_front=name)
    pp.save(name)


if __name__ == "__main__":
    for part in sys.argv[1:]:
        {"reuse": reuse, "horiz": horiz}[part]()
