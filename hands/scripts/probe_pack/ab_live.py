"""Render a batch 8 experiment in Live: the baseline and three alternatives across a target range.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/ab_live.py kick_distortion
  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/ab_live.py source_chord   # offline, once

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

CHORD = "12-2022-06-02-001 [2026-05-25 092256]"   # the processed synth chord loop (SFX group)
CHORD_SRC = "HW002_121_pp_c01"                    # canonical shape + the chord loop on (source_chord)

# Each experiment: the kit (default the batch 6 kit), the knobs it moves (track, device, parameter)
# and, per alternative, their values.
EXPERIMENTS = {
    # Batch 7.1 tracks 3-4 were best: Decapitator drive on rumble and COLDFIRE drive on the kick
    # group, moved together, at 37% and 50%. Target range 37-50%: both ends and the centre.
    "kick_distortion": {
        "knobs": [("rumble", C.DEC, "Drive"), ("S01 kick group", C.CF, "Distortion A Drive")],
        "alternatives": [[0.37, 0.37], [0.435, 0.435], [0.50, 0.50]],
    },
    # Batch 8.2: the chord loop under the intro, peak and outro is quiet; colour should bring it
    # forward (Anthony, 9 Oct). Its own first EQ Eight has a high shelf at 1.2 kHz, +3.1 dB.
    # Kit c8x4: the batch 6 kit's 8 bars with the chord loop on, 4 patterns.
    "chord_colour": {
        "kit": "c8x4",
        "knobs": [(CHORD, ("Eq8", 0), "Bands.1/ParameterA/Gain")],
        "alternatives": [[6.0], [9.0], [12.0]],
    },
}


BREAK_SRC = "HW002_121_pp_k01"                    # the full song, groups renamed (source_break)


def source_chord():
    """Offline: the canonical shape with the chord loop unmuted, its groups named like the batch 6
    kit's ("S01 kick group", "S01 perc group") so the baseline steps resolve. Build the kit from it:
    probe_kit.py template c8x4 HW002_121_pp_c01 24 56 4 (the d8x32 kit's section)."""
    return make_source(pp.CANON, CHORD_SRC, unmute=[CHORD])


def source_break():
    """Offline: the full song with its groups named like the batch 6 kit's, for kits from the break
    (bars 81-96, the synths): probe_kit.py template k8x16 HW002_121_pp_k01 320 352 16."""
    return make_source("HW002_121_full", BREAK_SRC)


def make_source(src, out, unmute=()):
    tree = PK.X.load(os.path.join(pp.PROJ, src + ".als"))
    for old in ("kick group", "perc group"):
        tr = PK.X.find_track(tree, old)
        for tag in ("EffectiveName", "UserName"):
            tr.find(f"./Name/{tag}").set("Value", "S01 " + old)
    for name in unmute:
        PK.X.find_track(tree, name).find("./DeviceChain/Mixer/Speaker/Manual").set("Value", "true")
    path = os.path.join(pp.PROJ, out + ".als")
    PK.X.save(tree, path)
    problems = PK.X.check(path).problems
    if problems:
        raise pp.Guard(f"als check failed: {problems}")
    return path


def baseline_steps(P):
    """Batch 6 "all": every improved b6 aspect at its best, in every pattern."""
    steps = []
    for a in ["kick_distortion", "density", "deep_sub", "mono_low", "colour", "space"]:
        sp = pp.DATA + f"climb_b6_{a}/state.json"
        if not os.path.exists(sp):
            continue
        st = json.load(open(sp))
        if any(h["improved"] for h in st["history"]):
            steps += C.steps_for(C.DESIGNS[f"b6_{a}"], [st["best_u"]] * P)
    return steps


def main():
    name = sys.argv[1]
    if name in ("source_chord", "source_break"):
        print(globals()[name]())
        return
    ex = EXPERIMENTS[name]
    kit = ex.get("kit", C.KIT)
    meta = json.load(open(PK.KITS + kit + ".json"))
    P = meta["P"]
    steps = baseline_steps(P)
    taken = {(tr, str(dev), p) for tr, dev, p, _ in steps}
    tree = PK.X.load(os.path.join(pp.PROJ, meta["set"] + ".als"))
    knobs = []
    for j, (tr, dev, p) in enumerate(ex["knobs"]):
        if (tr, str(dev), p) in taken:
            raise pp.Guard(f"{tr}/{p} is already set by the baseline")
        base = PK.current_value(tree, tr, dev, p)
        alts = [a[j] for a in ex["alternatives"]]
        values = [base] + alts + [base] * (P - 1 - len(alts))
        steps.append((tr, dev, p, values))
        knobs.append({"knob": f"{tr}/{dev[1] if isinstance(dev, tuple) else dev}/{p}", "baseline": base, "alternatives": alts})
    batch = PK.write_batch(kit, f"b8_{name}", devices=[], steps=steps)
    out = pp.DATA + f"ab8/{name}/"
    man = PK.render(batch, kit, out)
    json.dump({"experiment": name, "batch_set": batch, "knobs": knobs, "patterns": {"baseline": 0, "alternatives": [1, 2, 3]},
               "render": {k: man[k] for k in ("load_s", "export_s")}}, open(out + "ab.json", "w"), indent=1)
    print(json.dumps({"experiment": name, "knobs": knobs, "seconds": round(man["load_s"] + man["export_s"], 1)}))


if __name__ == "__main__":
    main()
