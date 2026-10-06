"""Hill-climb one HW002 mix aspect toward the four references.

  uv run --with librosa --with pedalboard python spikes/hw002_mixclimb/climb.py ASPECT [--k 8] [--patience 10]

Each batch-attempt tries K Gaussian steps around the current best (params in [0, 1]).
A new high score needs score > best + EPS. The step grows after a win and shrinks
after a miss. The aspect has plateaued after PATIENCE batch-attempts with no new
high score. Score: distance to the reference range and mean on the aspect's own
features, minus a penalty for every other feature that ends up further from the
references than the original mix was.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chains as C  # noqa: E402
import features as F  # noqa: E402

W = os.environ.get("MIXCLIMB_DIR", os.path.expanduser("~/_agent_scratch/mixclimb/"))
BAR = 1.5            # seconds per bar at 160 BPM
# Bar layout of the stems (stems/layout.json). start_bar: bar number at sample 0;
# proc: processed span with two bars of pre-roll; meas: measured span; ab: the A/B excerpt.
LAYOUT = {"source": "HW002_121 full arrangement", "start_bar": 121, "proc": [123, 144], "meas": [125, 144], "ab": [125, 132],
          "ab_label": "The drop, bars 125 to 132"}
if os.path.exists(W + "stems/layout.json"):
    LAYOUT.update(json.load(open(W + "stems/layout.json")))
STEM_START, PROC, MEAS = LAYOUT["start_bar"], tuple(LAYOUT["proc"]), tuple(LAYOUT["meas"])
EPS = 1e-4

TOL = [("third_octave_rel.", 3.0), ("corr.", 0.05), ("side_mid.20-120", 6.0), ("side_mid.", 3.0),
       ("block_crest_median_db", 1.0), ("transient_contrast_db", 1.0), ("ears.centroid_hz", 400.0),
       ("ears.rolloff_hz", 800.0), ("ears.flatness", 0.004), ("ears.harmonic_ratio", 0.08),
       ("ears.onset_strength", 0.05)]


def bands(lo, hi):
    return [f"third_octave_rel.{c}" for c in ("25.1", "31.6", "39.8", "50.1", "63.1", "79.4", "100.0", "125.9",
                                               "158.5", "199.5", "251.2", "316.2", "398.1", "501.2", "631.0",
                                               "794.3", "1000.0", "1258.9", "1584.9", "1995.3", "2511.9",
                                               "3162.3", "3981.1", "5011.9", "6309.6", "7943.3", "10000.0",
                                               "12589.3", "15848.9") if lo <= float(c) <= hi]


TARGETS = {  # aspect: {feature: weight}
    "kick_distortion": {**{b: 1.0 for b in bands(600, 3200)}, "block_crest_median_db": 2.0, "transient_contrast_db": 1.0},
    "colour": {**{b: 1.0 for b in bands(600, 3200) + bands(6000, 13000)}, **{b: 0.7 for b in bands(75, 210)},
               "ears.centroid_hz": 1.0, "ears.rolloff_hz": 0.5},
    "deep_sub": {b: 1.0 for b in bands(24, 52)},
    "mono_low": {"corr.20-120": 2.0, "side_mid.20-120": 1.0},
    "density": {"block_crest_median_db": 2.0, "transient_contrast_db": 1.5, "ears.onset_strength": 0.5},
    "space": {f"{k}.{b}": 1.0 for k in ("corr", "side_mid") for b in ("500-2000", "2000-8000", "8000-20000")},
}


# Guard features an aspect may move freely because another aspect owns them. Mid-only kick
# drive adds mono energy above 120 Hz, which narrows those bands; width belongs to "space".
GUARD_SKIP = {
    "kick_distortion": lambda k: k.startswith(("corr.", "side_mid.")) and not k.endswith("20-120"),
}


def tol(k):
    return next(t for p, t in TOL if k.startswith(p))


def dist(k, v, tg):
    if v is None:          # e.g. transient contrast finds < 3 hits once the drum bus is crushed
        return 5.0
    t = tg[k]
    out = max(0.0, t["min"] - v, v - t["max"])
    return (out + 0.3 * abs(v - t["mean"])) / tol(k)


def score(feat, aspect, tg, base_d):
    tw = TARGETS[aspect]
    main = sum(w * dist(k, feat[k], tg) for k, w in tw.items()) / sum(tw.values())
    skip = GUARD_SKIP.get(aspect, lambda k: False)
    guard = sum(max(0.0, dist(k, feat[k], tg) - base_d[k]) for k in base_d
                if k not in tw and not skip(k) and feat.get(k) is not None)
    return -(main + 0.5 * guard), main, guard


def load_stems(span):
    st = {}
    for name in ("kick", "perc", "sfx", "brk"):
        x, sr = sf.read(W + f"stems/{name}.wav", always_2d=True, dtype="float64")
        a, b = int((span[0] - STEM_START) * BAR * sr), int((span[1] - STEM_START + 1) * BAR * sr)
        st[name] = x[a:b]
    return st, sr


def measure_render(stems, sr, choices):
    y = C.render(stems, sr, choices)
    off = int((MEAS[0] - PROC[0]) * BAR * sr)
    return F.flat(F.measure(y[off:off + int((MEAS[1] - MEAS[0] + 1) * BAR * sr)], sr)), y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aspect")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--max-attempts", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    fn, n, neutral, _ = C.ASPECTS[a.aspect]
    rng = np.random.default_rng(a.seed)
    tg = json.load(open(W + "targets.json"))["targets"]
    stems, sr = load_stems(PROC)
    out = W + f"runs/{a.aspect}/"
    os.makedirs(out, exist_ok=True)
    log = open(out + "log.jsonl", "a")

    base_feat, _ = measure_render(stems, sr, {})
    base_d = {k: dist(k, v, tg) for k, v in base_feat.items() if k in tg and v is not None}
    best_u = np.array(neutral, dtype=float)
    best_feat, _ = measure_render(stems, sr, {a.aspect: best_u})
    best, bm, bg = score(best_feat, a.aspect, tg, base_d)
    sigma, misses, attempt = 0.15, 0, 0
    print(f"{a.aspect}: baseline score {best:.4f}", flush=True)

    def save(attempt):
        json.dump({"aspect": a.aspect, "attempt": attempt, "score": best, "main": bm, "guard": bg,
                   "u": best_u.tolist(), "params": C.describe(a.aspect, best_u),
                   "features": best_feat, "baseline_features": base_feat, "time": time.strftime("%FT%T")},
                  open(out + "best.json", "w"), indent=1)

    save(0)
    log.write(json.dumps({"attempt": 0, "best": best, "time": time.strftime("%FT%T")}) + "\n")
    while misses < a.patience and attempt < a.max_attempts:
        attempt += 1
        cands = np.clip(best_u + rng.normal(0, sigma, (a.k, n)), 0, 1)
        res = []
        for u in cands:
            feat, _ = measure_render(stems, sr, {a.aspect: u})
            res.append((score(feat, a.aspect, tg, base_d), u, feat))
        (s, m, g), u, feat = max(res, key=lambda t: t[0][0])
        improved = s > best + EPS
        if improved:
            best, bm, bg, best_u, best_feat = s, m, g, u, feat
            sigma, misses = min(sigma * 1.3, 0.35), 0
            save(attempt)
        else:
            sigma, misses = max(sigma * 0.8, 0.01), misses + 1
        log.write(json.dumps({"attempt": attempt, "best": best, "cand_best": s, "improved": improved,
                              "sigma": round(sigma, 4), "misses": misses, "time": time.strftime("%FT%T")}) + "\n")
        log.flush()
        print(f"{a.aspect} #{attempt}: best {best:.4f} (cand {s:.4f}) {'NEW' if improved else ''} "
              f"sigma {sigma:.3f} misses {misses}", flush=True)
    json.dump({"aspect": a.aspect, "plateaued": misses >= a.patience, "attempts": attempt, "best": best},
              open(out + "done.json", "w"))
    print(f"{a.aspect}: done after {attempt} attempts, best {best:.4f}, plateaued={misses >= a.patience}", flush=True)


if __name__ == "__main__":
    main()
