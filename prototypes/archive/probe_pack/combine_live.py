"""Render every improved batch 6 aspect at once, in Live (the batch 6 "all changes" track).

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/combine_live.py

Takes the best settings of each b6_* climb that beat the original (climb_live.py) and writes them
all into one kit batch: pattern 0 = the set as mixed, patterns 1-31 = all the bests together.
One load, one Main export. Writes ~/_agent_scratch/probepack/climb_b6_all/pattern_XX.wav + combined.json.
"""
import json
import os

import climb_live as C
import pp
import probe_kit as PK

ORDER = ["kick_distortion", "density", "deep_sub", "mono_low", "colour", "space"]


def main():
    steps, used = [], {}
    for a in ORDER:
        sp = pp.DATA + f"climb_b6_{a}/state.json"
        if not os.path.exists(sp):
            continue
        st = json.load(open(sp))
        if not any(h["improved"] for h in st["history"]):
            continue
        design = C.DESIGNS[f"b6_{a}"]
        us = [C.neutral_of(design)] + [st["best_u"]] * (C.P - 1)
        steps += C.steps_for(design, us)
        used[a] = [h for h in st["history"] if h["improved"]][-1]["params"]     # the final best's settings
    keys = [(tr, str(dev), p) for tr, dev, p, _ in steps]
    if len(keys) != len(set(keys)):
        raise pp.Guard("two aspects set the same parameter")
    name = PK.write_batch(C.KIT, "b6_all", devices=[], steps=steps)
    out = pp.DATA + "climb_b6_all/"
    man = PK.render(name, C.KIT, out)
    json.dump({"aspects": list(used), "params": used, "render": {k: man[k] for k in ("load_s", "export_s")}},
              open(out + "combined.json", "w"), indent=1)
    print(json.dumps({"aspects": list(used), "seconds": round(man["load_s"] + man["export_s"], 1)}))


if __name__ == "__main__":
    main()
