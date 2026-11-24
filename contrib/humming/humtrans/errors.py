"""What goes wrong once timing is fixed: break each model's TEST errors down.

    python3 -m humtrans.errors /path/to/HumTrans/midis VOCANO SheetSage MIR-ST500 JDC-STP pyin

Each model's TEST estimate is moved by its per-singer lag chosen on VALID
(from official_rescored_<model>.json) and by its best octave. Then:

  onset F1      notes found at the right time, pitch ignored
  note F1       the paper's metric, right time and right semitone
  pitch errors  among onset matches, how far the pitch is off, in semitones
  recall by kind  reference notes that repeat the previous pitch, or change it;
                  and short (< 0.3 s) against longer notes
"""
import json
import sys
from collections import Counter
from pathlib import Path

import mir_eval
import numpy as np

from .common import OUT
from .official import LAGS, estimate, notes, score

HZ = lambda m: 440.0 * np.power(2, (np.asarray(m, np.float32) - 69) / 12)


def analyse(ref, est, lag):
    (riv, rp), (eiv, ep) = ref, est
    eiv = eiv - lag
    keep = (eiv[:, 0] >= riv[0, 0]) & (eiv[:, 0] <= riv[-1, 1])
    eiv, ep = eiv[keep], ep[keep]
    out = {"n_ref": len(riv), "n_est": len(eiv)}
    if len(eiv) == 0:
        return {**out, "onset_hits": 0, "note_hits": 0, "pitch_off": [], "hit_mask": np.zeros(len(riv), bool)}
    om = mir_eval.transcription.match_note_onsets(riv, eiv, onset_tolerance=0.05)
    # Octave: the one the paper's metric picks.
    best, bo = -1, 0
    for o in range(-16, 17):
        m = mir_eval.transcription.match_notes(riv, HZ(rp + 12 * o), eiv, HZ(ep), onset_tolerance=0.05,
                                               pitch_tolerance=1.0, offset_ratio=None)
        if len(m) > best:
            best, bo = len(m), o
    nm = mir_eval.transcription.match_notes(riv, HZ(rp + 12 * bo), eiv, HZ(ep), onset_tolerance=0.05,
                                            pitch_tolerance=1.0, offset_ratio=None)
    hit = np.zeros(len(riv), bool)
    hit[[i for i, _ in nm]] = True
    off = [int(ep[j] - (rp[i] + 12 * bo)) for i, j in om]
    return {**out, "onset_hits": len(om), "note_hits": len(nm), "pitch_off": off, "hit_mask": hit}


def f1(hits, n_ref, n_est):
    p = hits / n_est if n_est else 0
    r = hits / n_ref if n_ref else 0
    return 2 * p * r / (p + r) if p + r else 0


def main():
    root = Path(sys.argv[1])
    res = {}
    for m in sys.argv[2:]:
        fitted = json.loads((OUT / f"official_rescored_{m}.json").read_text())[m]["singer_lag_from_valid"]
        keys = sorted(p.stem for p in (root / "GroundTruth" / "test").glob("*.mid"))
        rows, rep_hit, rep_n, short_hit, short_n = [], Counter(), Counter(), Counter(), Counter()
        pitch_off = Counter()
        for k in keys:
            ref = notes(root / "GroundTruth" / "test" / f"{k}.mid")
            a = analyse(ref, estimate(root, m, "test", k), fitted[k[:3]])
            rows.append(a)
            pitch_off.update(max(-3, min(3, (d + 6) % 12 - 6)) for d in a["pitch_off"])
            riv, rp = ref
            repeat = np.r_[False, np.diff(rp) == 0]
            short = (riv[:, 1] - riv[:, 0]) < 0.3
            for kind, mask in (("repeat", repeat), ("change", ~repeat)):
                rep_hit[kind] += int(a["hit_mask"][mask].sum())
                rep_n[kind] += int(mask.sum())
            for kind, mask in (("short", short), ("long", ~short)):
                short_hit[kind] += int(a["hit_mask"][mask].sum())
                short_n[kind] += int(mask.sum())
        mean = lambda f: float(np.mean([f(r) for r in rows]))
        tot_on = sum(pitch_off.values())
        res[m] = {
            "onset_F1": round(mean(lambda r: f1(r["onset_hits"], r["n_ref"], r["n_est"])), 4),
            "note_F1": round(mean(lambda r: f1(r["note_hits"], r["n_ref"], r["n_est"])), 4),
            "est_per_ref_note": round(sum(r["n_est"] for r in rows) / sum(r["n_ref"] for r in rows), 3),
            "pitch_off_semitones_among_onset_matches": {int(d): round(c / tot_on, 4) for d, c in sorted(pitch_off.items())},
            "recall_repeat_vs_change": {k: round(rep_hit[k] / rep_n[k], 4) for k in rep_n},
            "recall_short_vs_long": {k: round(short_hit[k] / short_n[k], 4) for k in short_n},
        }
        print(m, json.dumps(res[m]), flush=True)
    (OUT / "errors.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
