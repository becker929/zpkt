#!/usr/bin/env python3
"""Robust envelope timings for single hits, added to hits.csv.

The generic decay_ms in signal_features proved unreliable on very short noise
bursts (it read a 30 ms hat as 0.07 ms). This measures the envelope directly:
a 2 ms RMS envelope, then the time from the peak to -20 dB and to -40 dB, and
the "sustain share" (fraction of total energy after the first 50 ms), which
separates a thing that rings from a thing that stops.

    python3 analysis/hits_extra.py out/hits.csv
"""
import csv, sys
import numpy as np, soundfile as sf


def env_timings(y, sr, win_ms=2.0):
    w = max(1, int(sr * win_ms / 1000))
    n = len(y) // w
    if n < 2:
        return dict(decay20_ms=float("nan"), decay40_ms=float("nan"), sustain_share=float("nan"))
    e = np.sqrt((y[: n * w].reshape(n, w) ** 2).mean(axis=1)) + 1e-12
    db = 20 * np.log10(e / e.max())
    p = int(db.argmax())
    def t_to(th):
        idx = np.where(db[p:] <= th)[0]
        return float(idx[0] * win_ms) if len(idx) else float(n * win_ms)
    tot = float((y ** 2).sum()) + 1e-12
    k = int(sr * 0.05)
    return dict(decay20_ms=t_to(-20), decay40_ms=t_to(-40), sustain_share=float((y[k:] ** 2).sum() / tot))


def main(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        y, sr = sf.read(r["file"], dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        r.update({k: f"{v:.4g}" for k, v in env_timings(y, sr).items()})
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"added decay20_ms, decay40_ms, sustain_share to {len(rows)} rows", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/hits.csv")
