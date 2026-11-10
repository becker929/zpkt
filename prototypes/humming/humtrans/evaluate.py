"""Score transcriptions against the HumTrans reference MIDI, with and without lag correction.

    python3 -m humtrans.evaluate lag                 # per-recording lag from pYIN f0, TRAIN sample + TEST
    python3 -m humtrans.evaluate score TEST VALID    # note metrics for every cached method

Metrics are mir_eval's transcription.precision_recall_f1_overlap, 50 ms onset
tolerance, 50 cent pitch tolerance, averaged over recordings. "COnP" ignores
offsets; "COnPOff" also needs the offset within 20% of the note length (or
50 ms). Every score is octave-invariant, as in the HumTrans paper: each
recording's estimate is moved by whichever whole-octave shift scores best.

Protocols:
  raw      estimate as produced, the paper's setting
  global   every estimate moved earlier by one lag, the median measured on the
           TRAIN sample, so nothing is fitted to the split being scored
  oracle   each recording moved by the lag that maximises its own COnP F1,
           searched over 0-1.5 s; an upper bound, not a result
"""
import argparse
import json
from collections import defaultdict

import numpy as np
import mir_eval

from .common import CACHE, OUT, load_notes, ref_notes, split

HOP_S = 0.01
LAG_GRID = np.arange(-0.1, 1.61, 0.01)


def f0_lag(key, part=None):
    """Lag (s) at which the pYIN pitch track best matches the reference, octave-folded.

    part: None for the whole recording, or 0/1 for its first/second half.
    Returns (lag, fraction of frames agreeing within half a semitone).
    """
    _, _, d = load_notes(CACHE / "pyin" / f"{key}.json")
    f0 = np.array([np.nan if v is None else v for v in d["f0_midi"]]) - d["tuning"]
    iv, p = ref_notes(key)
    t = np.arange(len(f0)) * HOP_S
    ref = np.full(len(t), np.nan)
    for (s, e), m in zip(iv, p):
        ref[(t >= s) & (t < e)] = m
    if part is not None:
        mid = len(t) // 2
        keep = np.zeros(len(t), bool)
        keep[slice(0, mid) if part == 0 else slice(mid, None)] = True
        ref = np.where(keep, ref, np.nan)
    best = (-1.0, 0.0)
    for lag in LAG_GRID:
        n = int(round(lag / HOP_S))
        e = np.full_like(f0, np.nan)
        if n >= 0:
            e[: len(f0) - n] = f0[n:]
        else:
            e[-n:] = f0[:n]
        ok = ~np.isnan(e) & ~np.isnan(ref)
        if ok.sum() < 30:
            continue
        diff = (e[ok] - ref[ok] + 6) % 12 - 6
        agree = float(np.mean(np.abs(diff) < 0.5))
        if agree > best[0]:
            best = (agree, float(lag))
    return best[1], best[0]


def prf(ref_iv, ref_p, est_iv, est_p, offsets):
    if len(est_iv) == 0 or len(ref_iv) == 0:
        return 0.0, 0.0, 0.0
    p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_iv, mir_eval.util.midi_to_hz(ref_p), est_iv, mir_eval.util.midi_to_hz(est_p),
        onset_tolerance=0.05, pitch_tolerance=50.0, offset_ratio=0.2 if offsets else None)
    return p, r, f


def octave_best(ref_iv, ref_p, est_iv, est_p, offsets):
    """Best score over whole-octave shifts of the estimate."""
    return max((prf(ref_iv, ref_p, est_iv, est_p + 12 * k, offsets) for k in range(-3, 4)),
               key=lambda x: x[2])


def score_one(ref_iv, ref_p, est_iv, est_p, lag):
    est_iv = np.clip(est_iv - lag, 0, None)
    keep = est_iv[:, 1] > est_iv[:, 0]
    est_iv, est_p = est_iv[keep], est_p[keep]
    return {"COnP": octave_best(ref_iv, ref_p, est_iv, est_p, False),
            "COnPOff": octave_best(ref_iv, ref_p, est_iv, est_p, True)}


def cmd_lag(_):
    rows = {}
    for name in ("TRAIN", "TEST"):
        for key in split(name):
            if not (CACHE / "pyin" / f"{key}.json").exists():
                continue
            lag, agree = f0_lag(key)
            lag0, _ = f0_lag(key, 0)
            lag1, _ = f0_lag(key, 1)
            rows[key] = {"split": name, "lag": lag, "agree": agree, "lag_first_half": lag0,
                         "lag_second_half": lag1}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lag.json").write_text(json.dumps(rows, indent=1))
    train = [r["lag"] for r in rows.values() if r["split"] == "TRAIN"]
    print(len(train), "TRAIN recordings, median lag", np.median(train))


def cmd_score(a):
    lags = json.loads((OUT / "lag.json").read_text())
    global_lag = float(np.median([r["lag"] for r in lags.values() if r["split"] == "TRAIN"]))
    methods = sorted(p.name for p in CACHE.iterdir() if p.is_dir())
    results = {"global_lag": global_lag, "splits": {}}
    for name in a.splits:
        keys = split(name)
        table = {}
        # A perfect transcription, delayed by the global lag: what timing alone costs.
        rows = defaultdict(list)
        for key in keys:
            iv, p = ref_notes(key)
            rows["raw"].append(score_one(iv, p, iv, p, -global_lag))
        table["reference, delayed"] = rows
        for m in methods:
            rows = defaultdict(list)
            for key in keys:
                path = CACHE / m / f"{key}.json"
                if not path.exists():
                    continue
                iv, p = ref_notes(key)
                eiv, ep, _ = load_notes(path)
                rows["raw"].append(score_one(iv, p, eiv, ep, 0.0))
                rows["global"].append(score_one(iv, p, eiv, ep, global_lag))
                best = max((score_one(iv, p, eiv, ep, lag) for lag in np.arange(0, 1.51, 0.01)),
                           key=lambda s: s["COnP"][2])
                rows["oracle"].append(best)
            table[m] = rows
        summary = {}
        for m, rows in table.items():
            summary[m] = {proto: {"n": len(rs), **{metric: dict(zip("PRF", np.mean([r[metric] for r in rs], 0).round(4)))
                                                  for metric in ("COnP", "COnPOff")}}
                          for proto, rs in rows.items()}
        results["splits"][name] = summary
    (OUT / "scores.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lag").set_defaults(fn=cmd_lag)
    s = sub.add_parser("score")
    s.add_argument("splits", nargs="+")
    s.set_defaults(fn=cmd_score)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
