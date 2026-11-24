"""Compare note-start detectors on hummed notes.

    python3 -m humtrans.onsetbench /path/to/HumTrans/midis

Truth is the label's note starts moved by the recording's own delay (from
the pYIN pitch track, out/humtrans/perform_rows.json). Recordings where the
delay fit is poor (agreement under 0.5) are left out. Same 150 TEST
recordings as pitchbench.

HumTrans is closed-mouth humming: many notes change pitch with no break in
the sound. So these are floors for what a plosive "dum" would give, not
estimates of it.

Detectors:
  flux        librosa spectral flux, default peak picking
  superflux   spectral flux with a maximum filter across frequency (Boeck and Widmer 2013)
  cnn         madmom's CNN onset detector, trained on instrument music
  rnn         madmom's RNN onset detector
  pitch       note starts from pYIN pitch segmentation (transcribe.py)
  flux+pitch  union of flux and pitch starts, merged within 50 ms
  mir-st500   note starts from the MIR-ST500 singing model's published output
"""
import json
import sys
from pathlib import Path

import mir_eval
import numpy as np

from .common import CACHE, OUT, WAV, load_notes, ref_notes
from .official import notes
from .pitchbench import sample


def merge(times, within=0.05):
    times = np.sort(np.asarray(times))
    out = []
    for t in times:
        if not out or t - out[-1] > within:
            out.append(t)
    return np.array(out)


def detect(name, key, root):
    import librosa
    if name in ("flux", "superflux"):
        y, sr = librosa.load(WAV / f"{key}.wav", sr=22050)
        if name == "flux":
            return librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
        S = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=2048, hop_length=256, fmin=27.5, fmax=11000, n_mels=138)
        env = librosa.onset.onset_strength(S=librosa.power_to_db(S), sr=sr, hop_length=256, lag=2, max_size=3)
        return librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=256, units="time")
    if name in ("cnn", "rnn"):
        from madmom.features.onsets import CNNOnsetProcessor, RNNOnsetProcessor, OnsetPeakPickingProcessor
        proc = CNNOnsetProcessor() if name == "cnn" else RNNOnsetProcessor()
        act = proc(str(WAV / f"{key}.wav"))
        return OnsetPeakPickingProcessor(fps=100, threshold=0.5 if name == "cnn" else 0.35, combine=0.03)(act)
    if name == "pitch":
        return load_notes(CACHE / "pyin" / f"{key}.json")[0][:, 0]
    if name == "flux+pitch":
        return merge(np.r_[detect("flux", key, root), detect("pitch", key, root)])
    if name == "mir-st500":
        return notes(root / "MIR-ST500" / "test" / f"{key}.mid")[0][:, 0]
    raise ValueError(name)


def main():
    root = Path(sys.argv[1])
    rows = {r["key"]: r for r in json.loads((OUT / "perform_rows.json").read_text())}
    keys = [k for k in sample() if rows[k]["agree"] > 0.5]
    names = ["flux", "superflux", "cnn", "rnn", "pitch", "flux+pitch", "mir-st500"]
    res = {"recordings": len(keys)}
    for name in names:
        scores = {0.05: [], 0.1: []}
        counts = []
        for k in keys:
            iv, _ = ref_notes(k)
            ref = iv[:, 0] + rows[k]["lag"]
            est = np.asarray(detect(name, k, root), float)
            counts.append(len(est) / len(ref))
            for tol in scores:
                scores[tol].append(mir_eval.onset.f_measure(ref, est, window=tol) if len(est) else (0, 0, 0))
        res[name] = {f"F1@{int(t * 1000)}ms": round(float(np.mean([s[0] for s in v])), 4) for t, v in scores.items()}
        res[name].update({f"P@50ms": round(float(np.mean([s[1] for s in scores[0.05]])), 4),
                          f"R@50ms": round(float(np.mean([s[2] for s in scores[0.05]])), 4),
                          "found_per_true": round(float(np.median(counts)), 3)})
        print(name, res[name], flush=True)
    (OUT / "onsetbench.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
