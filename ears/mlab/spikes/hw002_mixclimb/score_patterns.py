"""Score rendered probe patterns (one WAV per pattern) against the reference targets.

  uv run --with librosa python spikes/hw002_mixclimb/score_patterns.py calibrate DIR NOISE_JSON [STEP]
  uv run --with librosa python spikes/hw002_mixclimb/score_patterns.py ASPECT DIR NOISE_JSON

Each pattern is measured without its first bar (the previous pattern's tail rings into it).
Scoring is climb.py's: distance to the references on the aspect's features, plus a guard
penalty for every other feature that ends up further from the references than the baseline.
NOISE_JSON (from `calibrate` on identical-setting patterns) holds the baseline features and
each feature's spread across timeline positions; the guard ignores worsening within that spread.
Prints one JSON line: [{"pattern": k, "score": s, "main": m, "guard": g, "features": {...}}, ...]
"""
import glob
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import climb as K  # noqa: E402
import features as F  # noqa: E402

BAR = 1.5


def measure(path):
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    return F.flat(F.measure(x[int(BAR * sr):], sr))


def score(f, aspect, tg, noise):
    """climb.score with a noise dead band: a guard feature counts as worse only beyond the spread
    that identical settings show across timeline positions (noise["delta"], in distance units)."""
    tw = K.TARGETS[aspect]
    main = sum(w * K.dist(k, f[k], tg) for k, w in tw.items()) / sum(tw.values())
    guard = sum(max(0.0, K.dist(k, f[k], tg) - noise["base_d"][k] - noise["delta"].get(k, 0.0))
                for k in noise["base_d"] if k not in tw and f.get(k) is not None)
    return -(main + 0.5 * guard), main, guard


def calibrate(d, out, step=1):
    """Noise model from identical-setting patterns (every `step`-th file in d): mean baseline
    features, per-feature distance spread, and the score spread it leaves."""
    files = sorted(glob.glob(os.path.join(d, "pattern_*.wav")))[::step]
    with ProcessPoolExecutor(max_workers=4) as ex:
        feats = list(ex.map(measure, files))
    tg = json.load(open(K.W + "targets.json"))["targets"]
    keys = [k for k in feats[0] if k in tg and all(f.get(k) is not None for f in feats)]
    base = {k: sum(f[k] for f in feats) / len(feats) for k in keys}
    dists = {k: [K.dist(k, f[k], tg) for f in feats] for k in keys}
    noise = {"n": len(feats), "base": base, "base_d": {k: K.dist(k, base[k], tg) for k in keys},
             "delta": {k: 1.5 * (max(v) - min(v)) for k, v in dists.items()}}
    scores = {a: [score(f, a, tg, noise)[0] for f in feats] for a in K.TARGETS}
    noise["score_spread"] = {a: max(v) - min(v) for a, v in scores.items()}
    json.dump(noise, open(out, "w"), indent=1)
    print(json.dumps({"n": len(feats), "score_spread": noise["score_spread"]}))


def main():
    if sys.argv[1] == "calibrate":
        return calibrate(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    aspect, d, noise_path = sys.argv[1], sys.argv[2], sys.argv[3]
    files = sorted(glob.glob(os.path.join(d, "pattern_*.wav")))
    with ProcessPoolExecutor(max_workers=4) as ex:
        feats = list(ex.map(measure, files))
    tg = json.load(open(K.W + "targets.json"))["targets"]
    noise = json.load(open(noise_path))
    out = []
    for k, f in enumerate(feats):
        s, m, g = score(f, aspect, tg, noise)
        out.append({"pattern": k, "score": round(s, 5), "main": round(m, 5), "guard": round(g, 5), "features": f})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
