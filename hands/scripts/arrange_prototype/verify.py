"""Trim a version render, check each bar against its source bar in the full
render, measure it, and encode the MP3.  uv run --with lameenc python verify.py ID "125-132"
"""
import json
import os
import sys

import lameenc
import numpy as np
import soundfile as sf

from mlab import loudness as L
from mlab import sections as SE

V = os.path.expanduser("~/_agent_scratch/renders/versions/")
FULL = os.path.expanduser("~/_agent_scratch/renders/hw002_121_full.wav")
BPM = 160.0
vid = sys.argv[1]
segs = [tuple(int(v) for v in s.split("-")) for s in sys.argv[2].split(",")]
src_bars = [b for a, e in segs for b in range(a, e + 1)]

x, sr = sf.read(V + vid + ".wav", always_2d=True, dtype="float64")
n = int(round(len(src_bars) * 4 * 60 / BPM * sr))
y = x[:n].copy()
f = int(0.03 * sr)
y[-f:] *= np.linspace(1, 0, f)[:, None]
sf.write(V + vid + "-trim.wav", y, sr, subtype="PCM_24")

full, _ = sf.read(FULL, always_2d=True, dtype="float64")
fl, fh = SE.bars(full, sr, BPM)
vl, vh = SE.bars(y, sr, BPM)
el, eh = fl[[b - 1 for b in src_bars]], fh[[b - 1 for b in src_bars]]
dl, dh = vl - el[: len(vl)], vh - eh[: len(vh)]
bad = [src_bars[i] for i in range(len(dl)) if abs(dl[i]) > 3 or abs(dh[i]) > 3]
corr = float(np.corrcoef(vh, eh[: len(vh)])[0, 1]) if len(vh) > 2 else float("nan")

e = lameenc.Encoder()
e.set_bit_rate(320); e.set_in_sample_rate(sr); e.set_channels(2); e.set_quality(2)
mp3 = V + f"2026-10-01-hw002-{vid}.mp3"
open(mp3, "wb").write(e.encode((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()) + e.flush())

res = {"id": vid, "duration_s": round(n / sr, 2), "bars": len(src_bars), "lufs": round(L.integrated(y, sr), 1),
       "true_peak_dbtp": round(L.true_peak(y, sr), 1), "bar_low_median_abs_diff_db": round(float(np.median(np.abs(dl))), 2),
       "bar_high_median_abs_diff_db": round(float(np.median(np.abs(dh))), 2), "high_profile_corr": round(corr, 3),
       "bars_off_by_3db": bad, "mp3": mp3}
print(json.dumps(res))
