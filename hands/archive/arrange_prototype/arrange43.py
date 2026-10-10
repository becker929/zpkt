"""Build one batch-4.3/4.4 version (batch 4.2 + "keep": mute every instrument not listed): grid sections with repeats, drop gaps, hat layers.

uv run python arrange4.py ID 'PLAN_JSON'
PLAN: {"segs": [[a,b], ...]        source bars, consecutive repeats allowed
       "gaps": [[j, beats], ...]   silence replacing the last `beats` before segment j
       "hats": [[bar, n, "AB"], ...]}  version bars (1-based), layers per hats.py
"""
import json
import os
import shutil
import sys
import time

import arrange as A
import fx
import hats as H
import timeops as TO

LEAD = 2
SILENT_SRC_BAR = 192  # past the end of the music; only the muted reference plays here


def build(vid, plan):
    segs = [tuple(s) for s in plan["segs"]]
    a0 = segs[0][0]
    lead = (a0 - LEAD, a0 - 1)
    full = [lead] + segs                      # what will be on the timeline, in order
    # collapse consecutive repeats for the delete pass
    uniq = []
    for s in full:
        if uniq and uniq[-1][0] == s:
            uniq[-1][1] += 1
        else:
            uniq.append([s, 1])
    name = f"HW002_121_v_{vid}"
    path = os.path.join(A.PROJ, name + ".als")
    # A retry finds this version still open: open_set would save the edited set over
    # the fresh copy, and re-opening an open file does nothing. Switch away first.
    if A.front() == name:
        A.open_set(A.SRC, "HW002_121_full")
    shutil.copyfile(A.SRC, path)
    A.open_set(path, name)
    pats = H.patterns(A.r)

    # 1. delete everything between the unique segments (latest first)
    gaps_src, prev = [], 0
    for (a, b), _ in uniq:
        if a > prev + 1:
            gaps_src.append((prev + 1, a - 1))
        prev = b
    deleted = 0
    for a, b in reversed(gaps_src):
        TO.delete((a - 1) * 4.0, (b - a + 1) * 4.0)
        deleted += (b - a + 1) * 4.0
    # 2. duplicate repeated segments (latest first, so earlier positions hold)
    pos = []
    p = 0.0
    for (a, b), n in uniq:
        pos.append(p)
        p += (b - a + 1) * 4.0
    added = 0
    for i in reversed(range(len(uniq))):
        (a, b), n = uniq[i]
        for _ in range(n - 1):
            TO.duplicate(pos[i], (b - a + 1) * 4.0)
            added += (b - a + 1) * 4.0
    # 3. drop gaps: replace the last beats before segment j with silence
    starts, p = [], 0.0
    for a, b in full:
        starts.append(p)
        p += (b - a + 1) * 4.0
    silent = (SILENT_SRC_BAR - 1) * 4.0 - deleted + added
    for j, beats in sorted(plan.get("gaps", []), reverse=True):
        d = starts[j + 1]  # +1: the lead is segment 0 on the timeline
        TO.copy(silent, beats)
        TO.delete(d - beats, beats)
        TO.paste(d - beats, beats)
    # 4. automation state at every segment start
    fixes = A.restore_automation(full)
    # 5. hats
    lead_beats = lead_beats_p = (lead[1] - lead[0] + 1) * 4.0
    made = H.rewrite(A.r, [(lead_beats + (bar - 1) * 4.0, n * 4.0, L) for bar, n, L in plan["hats"]], pats)
    # 6. clip-level fx (batch 4.2)
    fxinfo = {}
    seg_beat = lambda j: starts[j + 1]  # timeline beat where plan segment j starts
    sp = plan.get("splash")
    if sp:
        found = fx.clips_near(A.r, fx.SPLASH_TRACK, 0, 1e6)
        drop_at = seg_beat(sp["drop_segment"])
        src = [st for st, _, _ in found if abs(st - drop_at) < 1e-6]
        if not src:
            raise RuntimeError(f"no splash at the drop (beat {drop_at}); found {[st for st, _, _ in found]}")
        fx.splash(A.r, drop_at, sp["drop_beats"])
        times = [lead_beats_p + (bar - 1) * 4.0 for bar in sp.get("short_at_bars", [])]
        fx.splash_copies(A.r, drop_at, times, sp["short_beats"])
        fxinfo["splash"] = {"drop_at": drop_at, "drop_beats": sp["drop_beats"], "short_at": times, "short_beats": sp["short_beats"]}
    w = plan.get("wuh")
    if w:
        j = w["segment"]
        lo, hi = seg_beat(j), (starts[j + 2] if j + 2 < len(starts) else p)
        wuh_start = lo + w["start"]
        ph_start, ph_end, end_beat = fx.phrase_at(A.r, wuh_start, w["beats"], lo, hi)
        sl = w.get("slices")
        if sl:
            times = [lo + sl["start"] + k * sl["every"] for k in range(sl["count"])]
            fx.tail_slices(A.r, ph_start, end_beat, times, sl["len"])
        fxinfo["wuh"] = {"phrase": [round(ph_start, 3), round(ph_end, 3)], "wuh_start": wuh_start, "beats": w["beats"], "slices": sl}
    if plan.get("break_db") is not None:
        fxinfo["break_fader"] = fx.break_level(A.r, plan["break_db"])
    if plan.get("keep") is not None:
        # small surface area: leave only these tracks (indices) audible; groups stay on
        fxinfo["muted"] = A.r(f"""
KEEP = {sorted(plan["keep"])}
out = []
for i, t in enumerate(song.tracks):
    if not t.is_foldable and i not in KEEP:
        t.mute = True
        out.append(i)
result = out""")
    bars = sum(b - a + 1 for a, b in full)
    A.r("song.loop = False")
    A.menu("File", "Save Live Set")
    time.sleep(1.5)
    wav = A.record_arrangement(transport=A.T, filename=f"{vid}.wav", duration_beats=bars * 4.0, output_dir=A.OUT, tail_beats=2.0)
    A.menu("File", "Save Live Set")
    time.sleep(1.5)
    return {"id": vid, "set": path, "plan": plan, "lead_bars": LEAD, "raw": wav, "automation_fixes": fixes, "hat_clips": len(made), "fx": fxinfo}


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1], json.loads(sys.argv[2]))))
