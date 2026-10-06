"""Target features from the four Bandcamp references' peak windows, plus HW002's baseline.

  uv run --with librosa python spikes/hw002_mixclimb/targets.py   (inside ears/mlab)

Reads the 30 s peak excerpts that `mlab refs --peaks --excerpts` wrote on 1 Oct
(~/_agent_scratch/refs/HW002/matched/*peak30*.wav). The audio is purchased and
private; only the numbers are written, to ~/_agent_scratch/mixclimb/targets.json.
"""
import json
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402

M = os.path.expanduser("~/_agent_scratch/refs/HW002/matched/")
OUT = os.path.expanduser("~/_agent_scratch/mixclimb/")
REFS = ["BSLS", "Hedon", "KSMS", "Patriotic"]

os.makedirs(OUT, exist_ok=True)
rows = {}
for name in REFS + ["HW002"]:
    t = time.time()
    x, sr = sf.read(M + f"{name} - peak30 - -14LUFS.wav", always_2d=True, dtype="float64")
    rows[name] = F.flat(F.measure(x, sr))
    print(f"{name}: {time.time() - t:.1f} s", flush=True)

keys = [k for k in rows["HW002"] if all(k in rows[r] and rows[r][k] is not None for r in REFS)]
tgt = {}
for k in keys:
    v = np.array([rows[r][k] for r in REFS], dtype=float)
    tgt[k] = {"mean": round(float(v.mean()), 3), "min": round(float(v.min()), 3), "max": round(float(v.max()), 3),
              "hw002": rows["HW002"][k]}
json.dump({"refs": REFS, "targets": tgt, "rows": rows}, open(OUT + "targets.json", "w"), indent=1)

show = ["third_octave_rel.31.5", "third_octave_rel.40.0", "third_octave_rel.100.0", "third_octave_rel.1000.0",
        "third_octave_rel.2000.0", "third_octave_rel.3150.0", "third_octave_rel.10000.0", "corr.20-120",
        "side_mid.20-120", "corr.2000-8000", "side_mid.2000-8000", "side_mid.8000-19800", "block_crest_median_db",
        "transient_contrast_db", "ears.centroid_hz", "ears.flatness", "ears.harmonic_ratio", "ears.onset_strength"]
print(f"{'feature':32s} {'HW002':>9s} {'ref mean':>9s} {'ref min':>9s} {'ref max':>9s}")
for k in show:
    if k in tgt:
        t = tgt[k]
        print(f"{k:32s} {t['hw002']:9.3f} {t['mean']:9.3f} {t['min']:9.3f} {t['max']:9.3f}")
