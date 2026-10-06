"""Render a 32-step sweep of one batch 6 aspect in Live (for /skrng batches 7.1-7.6).

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/sweep_live.py b6_kick_distortion

If the aspect's climb (climb_live.py) beat the original, the sweep runs along the line from the
original settings through the best and on to 2.5x that change (clipped to each knob's range).
Otherwise it sweeps the aspect's main knob(s) over their whole range, other knobs at the set's
values. Pattern 0 is always the original. One kit batch, one load, one Main export.
Writes ~/_agent_scratch/probepack/sweep7/<aspect>/pattern_XX.wav + sweep.json (params per pattern).
"""
import json
import os
import sys
import time

import numpy as np

import climb_live as C
import pp
import probe_kit as PK

# Knobs swept together when the climb found nothing: (index into the design's params, +1 = up with t, -1 = down).
# Each moves the aspect's title feature across the references' range (publish7.py).
PRIMARY = {
    "kick_distortion": [(0, 1), (4, 1)],                     # Decapitator drive (rumble) + COLDFIRE drive (kick group)
    "density": [(0, -1), (1, 1)],                            # kick-group Compressor: threshold down, ratio up
    "deep_sub": [(1, 1), (2, 1), (3, 1)],                    # the three low-band gains
    "mono_low": [(3, -1)],                                   # rumble Utility width, wide to mono
    "colour": [(1, 1), (3, 1), (2, -1), (4, -1), (5, -1)],   # tilt: mid bands up, high bands down
    "space": [(0, 1)],                                       # Supermassive mix on perc 2
}
FORCE = {}


def main():
    dname = sys.argv[1]
    design = C.DESIGNS[dname]
    aspect = design["aspect"]
    u0 = np.array(C.neutral_of(design))
    sp = pp.DATA + f"climb_{dname}/state.json"
    st = json.load(open(sp)) if os.path.exists(sp) else None
    improved = bool(st and any(h["improved"] for h in st["history"]))
    P = 32
    if improved:
        ub = np.array(st["best_u"])
        ts = np.linspace(0.0, 2.5, P)
        us = [np.clip(u0 + t * (ub - u0), 0, 1) for t in ts]
        mode = "path"
    else:
        ts = np.linspace(0.0, 1.0, P - 1)
        us = [u0.copy()]
        for t in ts:
            u = u0.copy()
            for j, sign in PRIMARY[aspect]:
                u[j] = t if sign > 0 else 1.0 - t
            for j, v in FORCE.get(aspect, {}).items():
                u[j] = v
            us.append(u)
        mode = "primary"
    us[0] = u0                                          # pattern 0 = the original mix
    name = PK.write_batch(C.KIT, f"s7_{aspect}", devices=design["devices"], steps=C.steps_for(design, [u.tolist() for u in us]))
    out = pp.DATA + f"sweep7/{aspect}/"
    man = PK.render(name, C.KIT, out)
    keys = [f"{tr}/{dev[1] if isinstance(dev, tuple) else dev}/{p}" for tr, dev, p, lo, hi, sc in design["params"]]
    params = [{k: (C.value(u[j], lo, hi, sc) if sc == "bool" else round(C.value(u[j], lo, hi, sc), 6))
               for j, (k, (tr, dev, p, lo, hi, sc)) in enumerate(zip(keys, design["params"]))} for u in us]
    json.dump({"design": dname, "aspect": aspect, "mode": mode, "t": [float(t) for t in ([0.0] + list(ts) if mode == "primary" else ts)],
               "primary": [keys[j] for j, _ in PRIMARY[aspect]] if mode == "primary" else keys, "params": params,
               "made": time.strftime("%H%M"), "render": {k: man[k] for k in ("load_s", "export_s")}},
              open(out + "sweep.json", "w"), indent=1)
    print(json.dumps({"aspect": aspect, "mode": mode, "patterns": len(us), "seconds_per_probe": man["seconds_per_probe"]}))


if __name__ == "__main__":
    main()
