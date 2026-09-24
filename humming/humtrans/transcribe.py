"""Transcribe HumTrans recordings to notes with off-the-shelf methods.

    python3 -m humtrans.transcribe pyin TEST VALID
    python3 -m humtrans.transcribe basicpitch TEST
    python3 -m humtrans.transcribe pyin TRAIN --limit 400   # sample for the lag estimate

Writes one JSON of notes per recording to datasets/humtrans_out/<method>/.
The pyin method also stores its frame-level f0, which the lag estimate reuses.

Neither method sees the reference MIDI. The pyin segmentation parameters
below were picked by ear before any scoring and never tuned, so pyin is a
floor for what simple pitch tracking can do, not a tuned system.
"""
import argparse
import os
import random
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .common import CACHE, WAV, save_notes, split

SR = 16000
HOP = 160  # 10 ms frames

# pYIN note segmentation
MIN_NOTE = 0.08       # s; shorter runs are dropped
MEDIAN = 5            # frames of median smoothing on the pitch track
ONSET_SPLIT_DB = 6.0  # a rise this big inside a same-pitch run starts a new note


def pyin_notes(key):
    import librosa
    y, _ = librosa.load(WAV / f"{key}.wav", sr=SR)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=1000, sr=SR, frame_length=1024, hop_length=HOP)
    midi = librosa.hz_to_midi(np.where(voiced, f0, np.nan))
    ok = ~np.isnan(midi)
    # Hummers are rarely tuned to A440; take the recording's own tuning
    # (median deviation from the semitone grid) out before rounding.
    tuning = 0.0
    if ok.sum() > 10:
        dev = midi[ok] - np.round(midi[ok])
        tuning = float(np.angle(np.mean(np.exp(2j * np.pi * dev))) / (2 * np.pi))
    smooth = midi.copy()
    if ok.sum() > MEDIAN:
        from scipy.ndimage import median_filter
        smooth[ok] = median_filter(midi[ok], MEDIAN, mode="nearest")
    q = np.where(ok, np.round(smooth - tuning), np.nan)

    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=HOP)[0][: len(q)]
    db = 20 * np.log10(rms + 1e-6)
    rise = np.r_[0, np.diff(db, 1)]
    rise = np.maximum(rise, np.r_[0, 0, db[2:] - db[:-2]])

    iv, pitch = [], []
    start = None
    for i in range(len(q) + 1):
        cur = q[i] if i < len(q) else np.nan
        new_note = (start is not None and (np.isnan(cur) or cur != q[start]
                                           or (i - start > 5 and rise[i] > ONSET_SPLIT_DB)))
        if new_note:
            if (i - start) * HOP / SR >= MIN_NOTE:
                iv.append([start * HOP / SR, i * HOP / SR])
                pitch.append(float(np.median(smooth[start:i] - tuning)))
            start = None
        if start is None and not np.isnan(cur):
            start = i
    save_notes(CACHE / "pyin" / f"{key}.json", iv, np.round(pitch), tuning=tuning,
               f0_midi=[None if np.isnan(m) else round(float(m), 3) for m in midi])
    return key


def basicpitch_notes(keys):
    from basic_pitch.inference import predict, Model
    from basic_pitch import ICASSP_2022_MODEL_PATH
    model = Model(ICASSP_2022_MODEL_PATH)
    for n, key in enumerate(keys):
        _, _, events = predict(str(WAV / f"{key}.wav"), model)
        events = sorted(events, key=lambda e: e[0])
        iv = [[e[0], e[1]] for e in events]
        save_notes(CACHE / "basicpitch" / f"{key}.json", iv, [e[2] for e in events],
                   amplitude=[float(e[3]) for e in events])
        if n % 50 == 0:
            print(n, key, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("method", choices=["pyin", "basicpitch"])
    ap.add_argument("splits", nargs="+")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    keys = []
    for s in a.splits:
        k = split(s)
        if a.limit:
            k = random.Random(0).sample(k, a.limit)
        keys += k
    keys = [k for k in keys if not (CACHE / a.method / f"{k}.json").exists()]
    print(len(keys), "to do", flush=True)
    if a.method == "basicpitch":
        basicpitch_notes(keys)
        return
    with ProcessPoolExecutor(a.jobs) as ex:
        for n, k in enumerate(ex.map(pyin_notes, keys, chunksize=4)):
            if n % 100 == 0:
                print(n, k, flush=True)


if __name__ == "__main__":
    main()
