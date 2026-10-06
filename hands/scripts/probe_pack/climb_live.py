"""Hill-climb one mix aspect in Live with probe_kit: 32 candidates per batch-attempt, one render.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/climb_live.py DESIGN [MAX_ATTEMPTS_THIS_RUN]   (DESIGN: space | space_send)

Each batch-attempt writes one kit batch: pattern 0 re-renders the current best (a drift
control), patterns 1..31 are Gaussian steps around it in normalised parameter space (the first
batch-attempt samples them uniformly over the whole space instead). One load +
one Main export renders all 32; score_patterns.py (ears/mlab) scores them against the
references. A new high score must beat the best by more than the calibrated score noise of identical settings
across timeline positions (noise_d8x32.json) and by twice the control's drift.
Plateau = PATIENCE batch-attempts in a row without a new high score. Any guard trip stops the run.
State: ~/_agent_scratch/probepack/climb_<aspect>/state.json (resumable).
"""
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import time

import numpy as np

import pp
import probe_kit as PK

KIT, P, PATIENCE, EPS = "d8x32", 32, 10, 1e-3
MLAB = os.path.expanduser("~/Desktop/zpkt/ears/mlab")
DONOR = ("HW002_121_pp_v04", "S02 perc group", "Reverb")
_REV = [("DecayTime", 300.0, 6000.0, "log"), ("RoomSize", 10.0, 300.0, "log"), ("PreDelay", 0.5, 60.0, "log"),
        ("StereoSeparation", 60.0, 120.0, "lin"), ("ShelfHiFreq", 2000.0, 12000.0, "log")]
# Designs: devices to add, fixed settings, and the searched parameters (track, device, param, lo, hi, scale).
# Neutral (u = NEUTRAL) must sound like the original.
DESIGNS = {
    # E7: Reverb inserted on the perc group; Dry/Wet is a crossfade, so it also removes dry signal.
    "space": {"aspect": "space", "devices": [("S01 perc group", *DONOR)], "fixed": [],
              "params": [("S01 perc group", "Reverb", "MixDirect", 0.0, 0.6, "lin")] +
                        [("S01 perc group", "Reverb", n, lo, hi, sc) for n, lo, hi, sc in _REV],
              "neutral": [0.0, 0.5, 0.5, 0.5, 0.5, 0.5]},
    # E7b: Reverb 100 % wet on the return; the perc group's send adds it on top of a full dry signal.
    "space_send": {"aspect": "space", "devices": [("A-Return", *DONOR)],
                   "fixed": [("A-Return", "Reverb", "MixDirect", 1.0)],
                   "params": [("S01 perc group", "Mixer", "Sends/TrackSendHolder/Send", 0.0003162277571, 1.0, "log")] +
                             [("A-Return", "Reverb", n, lo, hi, sc) for n, lo, hi, sc in _REV],
                   "neutral": [0.0, 0.5, 0.5, 0.5, 0.5, 0.5]},
}


def value(u, lo, hi, scale):
    return lo + (hi - lo) * u if scale == "lin" else lo * (hi / lo) ** u


def steps_for(design, us):
    """[[u per param] per pattern] -> probe_kit steps, fixed settings included."""
    P_ = len(us)
    out = [(tr, dev, name, [round(value(u[j], lo, hi, sc), 9) for u in us])
           for j, (tr, dev, name, lo, hi, sc) in enumerate(design["params"])]
    out += [(tr, dev, name, [v] * P_) for tr, dev, name, v in design["fixed"]]
    return out


NOISE = pp.DATA + "noise_d8x32.json"   # calibrated on 16 identical neutral patterns (score_patterns calibrate)


def score(aspect, out_dir):
    r = subprocess.run(["uv", "run", "--with", "librosa", "--with", "pedalboard", "python",
                        "spikes/hw002_mixclimb/score_patterns.py", aspect, out_dir, NOISE],
                       cwd=MLAB, capture_output=True, text=True, timeout=900)
    line = [l for l in r.stdout.splitlines() if l.startswith("[")]
    if not line:
        raise RuntimeError(f"scoring failed: {r.stderr[-600:]}")
    return json.loads(line[-1])


def main():
    dname = sys.argv[1]
    design = DESIGNS[dname]
    aspect = design["aspect"]
    d = pp.DATA + f"climb_{dname}/"
    os.makedirs(d, exist_ok=True)
    sp = d + "state.json"
    st = json.load(open(sp)) if os.path.exists(sp) else {
        "aspect": aspect, "design": dname, "best_u": design["neutral"], "best": None, "sigma": 0.2, "misses": 0, "attempt": 0, "history": []}
    rng = np.random.default_rng(1000 + st["attempt"])
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 6     # max batch-attempts in this run
    while st["misses"] < PATIENCE and budget > 0:
        budget -= 1
        a = st["attempt"]
        best_u = np.array(st["best_u"])
        n_par = len(design["params"])
        if a == 0:   # first generation: sample the whole space (a local start at "off" cannot reach audible settings)
            cands = [best_u] + [rng.uniform(0, 1, n_par) for _ in range(P - 1)]
        else:
            cands = [best_u] + [np.clip(best_u + rng.normal(0, st["sigma"], n_par), 0, 1) for _ in range(P - 1)]
        t0 = time.time()
        name = PK.write_batch(KIT, f"{dname}{a:03d}", devices=design["devices"],
                              steps=steps_for(design, [c.tolist() for c in cands]))
        out = d + f"a{a:03d}/"
        if os.path.exists(out):
            shutil.rmtree(out)                     # a re-run of an interrupted attempt (our own files)
        man = PK.render(name, KIT, out)
        res = score(aspect, out)
        ctrl = res[0]["score"]
        if st["best"] is None:
            st["best"] = ctrl                      # attempt 0: pattern 0 is the neutral original
        drift = abs(ctrl - st["best"])
        top = max(res[1:], key=lambda r: r["score"])
        noise = json.load(open(NOISE))["score_spread"][aspect]
        improved = top["score"] > st["best"] + max(EPS, noise, 2 * drift)
        if improved:
            st["best"], st["best_u"] = top["score"], cands[top["pattern"]].tolist()
            st["sigma"], st["misses"] = min(st["sigma"] * 1.3, 0.35), 0
        else:
            st["sigma"], st["misses"] = max(st["sigma"] * 0.8, 0.02), st["misses"] + 1
        keep = {0, top["pattern"]}
        for f in glob.glob(out + "pattern_*.wav"):
            if int(f[-6:-4]) not in keep:
                os.remove(f)                       # our own intermediate renders: keep best + control only
        os.remove(out + "all.wav")
        st["history"].append({"attempt": a, "control": ctrl, "drift": round(drift, 5), "top": top["score"],
                              "top_pattern": top["pattern"], "improved": improved, "best": st["best"],
                              "sigma": round(st["sigma"], 4), "seconds": round(time.time() - t0, 1),
                              "render_s": man["load_s"] + man["export_s"],
                              "params": {f"{tr}/{name}": round(value(u, lo, hi, sc), 6)
                                         for u, (tr, dev, name, lo, hi, sc) in zip(st["best_u"], design["params"])}})
        st["attempt"] = a + 1
        json.dump(st, open(sp, "w"), indent=1)
        pp.log("climb_attempt", time.time() - t0, aspect=aspect, attempt=a, best=st["best"], improved=str(improved))
        print(json.dumps(st["history"][-1]), flush=True)
    print(json.dumps({"plateaued": st["misses"] >= PATIENCE, "attempts": st["attempt"], "best": st["best"],
                      "best_params": st["history"][-1]["params"] if st["history"] else None}))


if __name__ == "__main__":
    main()
