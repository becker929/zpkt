"""Render a batch 8 experiment in Live: the baseline and three alternatives across a target range.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/ab_live.py kick_distortion

From Anthony's review of batches 6 and 7 (docs/hw002/batch-6-7-decisions.md): the baseline is
batch 6 "all" (every b6 aspect whose climb improved, at its best, as combine_live.py), and an
experiment is three alternatives at the low end, centre and high end of a target range, never
outside it. Pattern 0 = the baseline, patterns 1-3 = the alternatives, the rest repeat the
baseline. One kit batch, one load, one Main export (probe_kit). Writes
~/_agent_scratch/probepack/ab8/<experiment>/pattern_XX.wav + ab.json; the A/B tracks are cut
from those offline (ears/mlab/spikes/hw002_mixclimb/publish8.py).
"""
import json
import os
import sys

import climb_live as C
import pp
import probe_kit as PK

# Each experiment: the knobs it moves (track, device, parameter) and, per alternative, their values.
EXPERIMENTS = {
    # Batch 7.1 tracks 3-4 were best: Decapitator drive on rumble and COLDFIRE drive on the kick
    # group, moved together, at 37% and 50%. Target range 37-50%: both ends and the centre.
    "kick_distortion": {
        "knobs": [("rumble", C.DEC, "Drive"), ("S01 kick group", C.CF, "Distortion A Drive")],
        "alternatives": [[0.37, 0.37], [0.435, 0.435], [0.50, 0.50]],
    },
}


def baseline_steps():
    """Batch 6 "all": every improved b6 aspect at its best, in every pattern."""
    steps = []
    for a in ["kick_distortion", "density", "deep_sub", "mono_low", "colour", "space"]:
        sp = pp.DATA + f"climb_b6_{a}/state.json"
        if not os.path.exists(sp):
            continue
        st = json.load(open(sp))
        if any(h["improved"] for h in st["history"]):
            steps += C.steps_for(C.DESIGNS[f"b6_{a}"], [st["best_u"]] * C.P)
    return steps


def main():
    name = sys.argv[1]
    ex = EXPERIMENTS[name]
    steps = baseline_steps()
    taken = {(tr, str(dev), p) for tr, dev, p, _ in steps}
    meta = json.load(open(PK.KITS + C.KIT + ".json"))
    tree = PK.X.load(os.path.join(pp.PROJ, meta["set"] + ".als"))
    knobs = []
    for j, (tr, dev, p) in enumerate(ex["knobs"]):
        if (tr, str(dev), p) in taken:
            raise pp.Guard(f"{tr}/{p} is already set by the baseline")
        base = PK.current_value(tree, tr, dev, p)
        alts = [a[j] for a in ex["alternatives"]]
        values = [base] + alts + [base] * (C.P - 1 - len(alts))
        steps.append((tr, dev, p, values))
        knobs.append({"knob": f"{tr}/{dev[1] if isinstance(dev, tuple) else dev}/{p}", "baseline": base, "alternatives": alts})
    batch = PK.write_batch(C.KIT, f"b8_{name}", devices=[], steps=steps)
    out = pp.DATA + f"ab8/{name}/"
    man = PK.render(batch, C.KIT, out)
    json.dump({"experiment": name, "batch_set": batch, "knobs": knobs, "patterns": {"baseline": 0, "alternatives": [1, 2, 3]},
               "render": {k: man[k] for k in ("load_s", "export_s")}}, open(out + "ab.json", "w"), indent=1)
    print(json.dumps({"experiment": name, "knobs": knobs, "seconds": round(man["load_s"] + man["export_s"], 1)}))


if __name__ == "__main__":
    main()
