"""Build one batch-4 version: grid sections with repeats, drop gaps, hat layers.

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
    lead_beats = (lead[1] - lead[0] + 1) * 4.0
    made = H.rewrite(A.r, [(lead_beats + (bar - 1) * 4.0, n * 4.0, L) for bar, n, L in plan["hats"]], pats)
    bars = sum(b - a + 1 for a, b in full)
    A.r("song.loop = False")
    A.menu("File", "Save Live Set")
    time.sleep(1.5)
    wav = A.record_arrangement(transport=A.T, filename=f"{vid}.wav", duration_beats=bars * 4.0, output_dir=A.OUT, tail_beats=2.0)
    A.menu("File", "Save Live Set")
    time.sleep(1.5)
    return {"id": vid, "set": path, "plan": plan, "lead_bars": LEAD, "raw": wav, "automation_fixes": fixes, "hat_clips": len(made)}


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1], json.loads(sys.argv[2]))))
