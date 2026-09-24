"""Re-score the HumTrans paper's own baseline outputs, with timing corrected.

The authors published each model's predicted MIDI for the VALID and TEST
splits, and their scoring script, at github.com/shansongliu/HumTrans. Clone
it and unzip midis/*.zip, then:

    python3 -m humtrans.official /path/to/HumTrans/midis

score() below is their calc_transcription_eval_metric.py re-typed with one
addition, a lag: every predicted note is moved that many seconds earlier
before scoring. At lag 0 it reproduces their Table 2 to every printed digit
(checked by this script). Their metric: onsets within 50 ms, exact semitone,
offsets ignored, best of +-16 octave shifts per recording, predicted notes
kept only if they start inside the reference's first-to-last-note span,
mean over recordings.

For each model the lag is chosen on VALID and then applied to TEST, so the
TEST figure is a held-out one.
"""
import json
import sys
from pathlib import Path

import mir_eval
import numpy as np
import pretty_midi

from .common import OUT

MODELS = ["VOCANO", "SheetSage", "MIR-ST500", "JDC-STP"]
PAPER = {  # Table 2, P/R/F1 in percent
    "VOCANO": {"valid": (3.270, 3.134, 3.194), "test": (3.384, 3.329, 3.352)},
    "SheetSage": {"valid": (2.757, 2.656, 2.702), "test": (3.039, 2.982, 3.005)},
    "MIR-ST500": {"valid": (6.258, 6.448, 6.341), "test": (5.686, 5.853, 5.755)},
    "JDC-STP": {"valid": (6.777, 6.785, 6.741), "test": (5.844, 5.620, 5.667)}}
LAGS = np.round(np.arange(-0.1, 0.51, 0.02), 2)


def notes(path):
    ns = sorted((n.start, n.end, n.pitch) for i in pretty_midi.PrettyMIDI(str(path)).instruments
                if not i.is_drum for n in i.notes)
    return np.array([n[:2] for n in ns], float).reshape(-1, 2), np.array([n[2] for n in ns], float)


def score(ref, est, lag):
    (riv, rp), (eiv, ep) = ref, est
    eiv = eiv - lag
    keep = (eiv[:, 0] >= riv[0, 0]) & (eiv[:, 0] <= riv[-1, 1])
    eiv, ep = eiv[keep], ep[keep]
    hz = lambda m: 440.0 * np.power(2, (m.astype(np.float32) - 69) / 12)
    best = (0.0, 0.0, -1.0)
    # Their search is every octave in +-16. An octave can only score if some
    # predicted note is within 50 ms of a reference onset and exactly that many
    # octaves away, so only those are tried; the result is the same.
    near = np.abs(eiv[:, None, 0] - riv[None, :, 0]) <= 0.06  # loose: mir_eval rounds distances first
    d = (ep[:, None] - rp[None, :])[near]
    cands = sorted({int(x) // 12 for x in d if x % 12 == 0 and abs(x) // 12 <= 16}) or [0]
    for o in cands:
        p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(
            riv, hz(rp + 12 * o), eiv, hz(ep), onset_tolerance=0.05,
            pitch_tolerance=1.0, offset_ratio=None)
        if f > best[2]:
            best = (p, r, f)
    return best


def main():
    root = Path(sys.argv[1])
    models = sys.argv[2:] or MODELS
    res = {}
    for m in models:
        res[m] = {}
        for s in ("valid", "test"):
            keys = sorted(p.stem for p in (root / "GroundTruth" / s).glob("*.mid"))
            pairs = [(notes(root / "GroundTruth" / s / f"{k}.mid"), notes(root / m / s / f"{k}.mid"))
                     for k in keys]
            per_lag = np.array([[score(r, e, lag) for r, e in pairs] for lag in LAGS])  # lag, file, prf
            res[m][s] = {"curve_F1": dict(zip(LAGS.tolist(), per_lag[:, :, 2].mean(1).round(4).tolist())),
                         "at_0": per_lag[LAGS == 0][0].mean(0).round(5).tolist(),
                         "oracle_per_file": per_lag[per_lag[:, :, 2].argmax(0), np.arange(len(keys))].mean(0).round(4).tolist(),
                         "oracle_lag_per_file": dict(zip(keys, LAGS[per_lag[:, :, 2].argmax(0)].tolist())),
                         "per_lag": per_lag}
            print(m, s, "lag 0:", res[m][s]["at_0"], flush=True)
        for s in ("valid", "test"):
            assert np.allclose(np.array(res[m][s]["at_0"]) * 100, PAPER[m][s], atol=0.001), (m, s)
        v = res[m]["valid"]["per_lag"][:, :, 2].mean(1)
        lag = float(LAGS[v.argmax()])
        res[m]["lag_from_valid"] = lag
        res[m]["test_at_valid_lag"] = res[m]["test"]["per_lag"][LAGS == lag][0].mean(0).round(4).tolist()
        print(m, "lag chosen on valid", lag, "-> test P/R/F1", res[m]["test_at_valid_lag"], flush=True)
    for m in models:
        for s in ("valid", "test"):
            del res[m][s]["per_lag"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"official_rescored_{'_'.join(models)}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
