"""Note models side by side on the 150-recording sample, one delay per recording.

    python3 -m humtrans.notebench /path/to/HumTrans/midis

Every model is scored with the paper's metric (official.score: 50 ms onsets,
exact semitone, offsets ignored, best octave), after moving its notes earlier
by the recording's own delay as measured from the pYIN pitch track
(out/humtrans/perform_rows.json). The delay comes from the audio, not from
any model's output, so no model is favoured by it. Recordings whose delay fit
is poor (agreement under 0.5) are left out.

Models: the paper's four (published MIDI), our pYIN segmentation, and ROSVOT
(Li et al., ACL 2024; datasets/humtrans_out/rosvot_raw/midi/, produced with
the released checkpoint patched to run on CPU).
"""
import json
import sys
from pathlib import Path

import numpy as np

from .common import CACHE, OUT
from .official import MODELS, estimate, notes, score
from .pitchbench import sample


def main():
    root = Path(sys.argv[1])
    rows = {r["key"]: r for r in json.loads((OUT / "perform_rows.json").read_text())}
    keys = [k for k in sample() if rows[k]["agree"] > 0.5]
    ros = CACHE / "rosvot_raw" / "midi"
    res = {"recordings": len(keys)}
    for m in MODELS + ["pyin", "rosvot"]:
        prf = []
        for k in keys:
            ref = notes(root / "GroundTruth" / "test" / f"{k}.mid")
            if m == "rosvot":
                p = ros / f"{k}.mid"
                if not p.exists():
                    continue
                est = notes(p)
            else:
                est = estimate(root, m, "test", k)
            prf.append(score(ref, est, rows[k]["lag"]))
        a = np.array(prf)
        res[m] = {"n": len(a), "P": round(float(a[:, 0].mean()), 4), "R": round(float(a[:, 1].mean()), 4),
                  "F1": round(float(a[:, 2].mean()), 4)}
        print(m, res[m], flush=True)
    (OUT / "notebench.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
