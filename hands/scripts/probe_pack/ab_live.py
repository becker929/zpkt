"""Render a batch 8 experiment in Live: the baseline and three alternatives across a target range.

  cd hands && uv run python scripts/probe_pack/ab_live.py kick_distortion
  cd hands && uv run python scripts/probe_pack/ab_live.py source_chord   # offline, once

From Anthony's review of batches 6 and 7 (docs/hw002/batch-6-7-decisions.md): the baseline is
batch 6 "all" (every b6 aspect whose climb improved, at its best, as combine_live.py), and an
experiment is three alternatives at the low end, centre and high end of a target range, never
outside it. Pattern 0 = the baseline, patterns 1-3 = the alternatives, the rest repeat the
baseline. One kit batch, one load, one Main export (hands.probe_kit). Writes
<data_dir>/ab8/<experiment>/pattern_XX.wav + ab.json; the A/B tracks are cut
from those offline (ears/mlab/spikes/hw002_mixclimb/publish8.py).
"""
import json
import os
import sys

import climb_live as C

from hands import als, config
from hands import probe_kit as PK
from hands.live.knobs import Knob
from hands.live.transport import LiveClient

CHORD = "12-2022-06-02-001 [2026-05-25 092256]"   # the processed synth chord loop (SFX group)
CANON = "HW002_121_v_b43-01-splash-every-8-bars-30s"   # the canonical shape (batch 4.3, track 1)
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
    hands kit template c8x4 HW002_121_pp_c01 24 56 4 (the d8x32 kit's section)."""
    return make_source(CANON, CHORD_SRC, unmute=[CHORD])


def source_break():
    """Offline: the full song with its groups named like the batch 6 kit's, for kits from the break
    (bars 81-96, the synths): hands kit template k8x16 HW002_121_pp_k01 320 352 16."""
    return make_source("HW002_121_full", BREAK_SRC)


def make_source(src, out, unmute=()):
    rig = config.rig()
    tree = als.load(rig.set_path(src))
    for old in ("kick group", "perc group"):
        als.rename_track(tree, old, "S01 " + old)
    for name in unmute:
        als.set_speaker(tree, name, True)
    path = als.save(tree, rig.set_path(out))
    problems = als.check(path).problems
    if problems:
        raise SystemExit(f"als check failed: {problems}")
    return path


def baseline_steps(P):
    """Batch 6 "all": every improved b6 aspect at its best, in every pattern."""
    steps = []
    for a in ["kick_distortion", "density", "deep_sub", "mono_low", "colour", "space"]:
        sp = C.data() / f"climb_b6_{a}" / "state.json"
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
    kit = PK.Kit.load(ex.get("kit", C.KIT))
    steps = baseline_steps(kit.P)
    taken = {knob for knob, _ in steps}
    tree = als.load(config.rig().set_path(kit.set))
    knobs = []
    for j, (tr, dev, p) in enumerate(ex["knobs"]):
        knob = Knob(tr, dev, p)
        if knob in taken:
            raise SystemExit(f"{knob} is already set by the baseline")
        base = als.current_value(tree, *knob.spec)
        alts = [a[j] for a in ex["alternatives"]]
        steps.append((knob, [base] + alts + [base] * (kit.P - 1 - len(alts))))
        knobs.append({"knob": knob.id, "baseline": base, "alternatives": alts})
    batch = PK.write_batch(kit, f"b8_{name}", steps=steps)
    out = C.data() / "ab8" / name
    man = PK.render(LiveClient(), batch, kit, out)
    json.dump({"experiment": name, "batch_set": batch, "knobs": knobs, "patterns": {"baseline": 0, "alternatives": [1, 2, 3]},
               "render": {k: man[k] for k in ("load_s", "export_s")}}, open(out / "ab.json", "w"), indent=1)
    print(json.dumps({"experiment": name, "knobs": knobs, "seconds": round(man["load_s"] + man["export_s"], 1)}))


if __name__ == "__main__":
    main()
