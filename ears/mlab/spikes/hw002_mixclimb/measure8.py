"""Measure a batch 8 sweep: the target's loudness and how far it sits under the rest of the mix.

  uv run --with pyloudnorm python spikes/hw002_mixclimb/measure8.py chord

Reads ~/_agent_scratch/probepack/sweep8/<sweep>/{mix,solo,rest}/pattern_XX.wav (zpkt
hands/scripts/probe_pack/sweep8.py). Per pattern: mix LUFS, target LUFS, target under rest (LU),
and per octave band the target's level against the rest's (dB, the masking picture), plus the
target's side/mid ratio (width). Each value is also given against pattern 0 (the baseline).
The spread over the trailing baseline repeats is the noise floor. Writes measure.json next to the renders.
"""
import json
import os
import sys

import numpy as np
import pyloudnorm as pl
import soundfile as sf

BANDS = [(63, 125), (125, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)]


def read(path):
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    return x, sr


def band_db(x, sr):
    S = np.abs(np.fft.rfft(x.mean(1))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return [10 * np.log10(S[(f >= lo) & (f < hi)].sum() + 1e-12) for lo, hi in BANDS]


def side_mid(x):
    m, s = x[:, 0] + x[:, 1], x[:, 0] - x[:, 1]
    return 10 * np.log10((s ** 2).mean() + 1e-15) - 10 * np.log10((m ** 2).mean() + 1e-15)


def main():
    root = os.path.expanduser(f"~/_agent_scratch/probepack/sweep8/{sys.argv[1]}/")
    sw = json.load(open(root + "sweep.json"))
    meter = None
    rows = []
    for k, label in enumerate(sw["labels"]):
        mix, sr = read(root + f"mix/pattern_{k:02d}.wav")
        solo, _ = read(root + f"solo/pattern_{k:02d}.wav")
        has_rest = os.path.isdir(root + "rest")
        rest = read(root + f"rest/pattern_{k:02d}.wav")[0] if has_rest else mix   # no rest view: against the mix
        meter = meter or pl.Meter(sr)
        L = {v: meter.integrated_loudness(x) for v, x in (("mix", mix), ("solo", solo), ("rest", rest))}
        rows.append({"k": k, "label": label, "mix_lufs": L["mix"], "target_lufs": L["solo"],
                     "under_rest_lu": L["rest"] - L["solo"],
                     "bands_vs_rest": [a - b for a, b in zip(band_db(solo, sr), band_db(rest, sr))],
                     "target_bands": band_db(solo, sr), "side_mid_db": side_mid(solo)})
    b = rows[0]
    reps = [r for r in rows if r["label"].startswith("baseline")] or rows[:1]
    noise = {key: float(np.ptp([r[key] for r in reps])) for key in ("mix_lufs", "target_lufs", "under_rest_lu")}
    print(f"noise over {len(reps)} baselines (range): " + ", ".join(f"{k} {v:.2f}" for k, v in noise.items()))
    print(f"{'pattern':34}{'mix':>7}{'target':>8}{'d':>6}{'under':>7}  bands vs rest, d from baseline (63 Hz .. 8 kHz){'side/mid':>12}")
    for r in rows:
        d = [x - y for x, y in zip(r["target_bands"], b["target_bands"])]
        print(f"{r['label'][:33]:34}{r['mix_lufs']:7.2f}{r['target_lufs']:8.1f}{r['target_lufs'] - b['target_lufs']:+6.1f}"
              f"{r['under_rest_lu']:7.1f}  " + " ".join(f"{v:+5.1f}" for v in d) + f"{r['side_mid_db']:+8.1f}")
    print("baseline target vs rest per band (dB):", " ".join(f"{v:+.0f}" for v in b["bands_vs_rest"]))
    json.dump({"rows": rows, "noise": noise, "bands": BANDS}, open(root + "measure.json", "w"), indent=1)


if __name__ == "__main__":
    main()
