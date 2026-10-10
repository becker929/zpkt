"""Re-trim batch 2/3 takes onto the grid and re-check against the aligned reference.

verify2 measured each take against the old full render, whose song beat 0 sat
0.917 s into its file, so every trim started 0.917 s early. The take's own
beat 0 is therefore offset_ms/1000 + 0.917 s; trim from there plus the lead-in.
"""
import json
import os

import lameenc
import numpy as np
import soundfile as sf
from scipy import signal

from mlab import loudness as L
from mlab import sections as SE

S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"
V = os.path.expanduser("~/_agent_scratch/renders/versions/")
REF = os.path.expanduser("~/_agent_scratch/renders/hw002_121_full_aligned.wav")
OLD_ZERO = 0.9172
BAR, LEAD, BPM = 1.5, 2, 160.0

last = {}
for l in open(S + "batch3_results.jsonl"):
    d = json.loads(l)
    last[d["id"]] = d
ref, sr = sf.read(REF, always_2d=True, dtype="float64")
rm = ref.mean(1)
out = {}
for vid, d in last.items():
    if not d["ok"]:
        continue
    segs = [tuple(s) for s in d["segments"]]
    x, _ = sf.read(V + vid + ".wav", always_2d=True, dtype="float64")
    zero = d["offset_ms"] / 1000 + OLD_ZERO
    start = int(round((zero + LEAD * BAR) * sr))
    n = int(round(sum(b - a + 1 for a, b in segs) * BAR * sr))
    y = x[start:start + n].copy()
    if len(y) < n:
        print(vid, "take too short for the corrected trim"); continue
    y[:int(0.01 * sr)] *= np.linspace(0, 1, int(0.01 * sr))[:, None]
    y[-int(0.03 * sr):] *= np.linspace(1, 0, int(0.03 * sr))[:, None]
    exp = np.concatenate([rm[int((a - 1) * BAR * sr):int(b * BAR * sr)] for a, b in segs])
    ym = y.mean(1)
    # lag check (full band, original hats): 250 ms windows within +-150 ms
    win, lags, cs = int(0.25 * sr), [], []
    for s in range(0, n - 2 * win, win):
        a = ym[s:s + win]
        lo = max(0, s - int(0.15 * sr)); b = exp[lo:s + int(0.15 * sr) + win]
        c = signal.fftconvolve(b, a[::-1], "valid")
        r = c / (np.sqrt(np.sum(a * a)) * np.sqrt(np.convolve(b * b, np.ones(win), "valid")) + 1e-12)
        k = int(np.argmax(r)); lags.append((lo + k - s) / sr); cs.append(r[k])
    lags = np.array(lags); med = float(np.median(lags))
    first2 = [round(float(v) * 1000, 1) for v in lags[:4]]
    # first bar vs its source bar (the grid check that failed before)
    fl, fh = SE.bars(ref, sr, BPM); vl, vh = SE.bars(y, sr, BPM)
    a0 = segs[0][0]
    d_first = [round(float(vl[0] - fl[a0 - 1]), 1), round(float(vh[0] - fh[a0 - 1]), 1)]
    e = lameenc.Encoder(); e.set_bit_rate(320); e.set_in_sample_rate(sr); e.set_channels(2); e.set_quality(2)
    mp3 = V + f"2026-10-01-hw002-{vid}-r3.mp3"
    open(mp3, "wb").write(e.encode((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()) + e.flush())
    ok = abs(med) < 0.01 and all(abs(v) < 35 for v in first2) and abs(d_first[0]) < 3
    out[vid] = {"id": vid, "ok": ok, "take_zero_ms": round(zero * 1000, 1), "median_lag_ms": round(med * 1000, 1),
                "first_windows_lag_ms": first2, "first_bar_low_high_diff_db": d_first,
                "lufs": round(L.integrated(y, sr), 1), "true_peak_dbtp": round(L.true_peak(y, sr), 1), "mp3": mp3}
    print(vid, out[vid]["ok"], out[vid]["take_zero_ms"], out[vid]["median_lag_ms"], first2, d_first, flush=True)
json.dump(out, open(S + "retrim_results.json", "w"), indent=1)
