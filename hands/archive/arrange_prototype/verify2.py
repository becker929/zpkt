"""Trim the lead-in at a measured offset, check the timeline, bars and loudness,
encode the MP3.  uv run --with lameenc python verify2.py ID '[[a,b],...]' LEAD

Timeline check: in 250 ms windows the render must match the planned source
audio at lag 0 (+-30 ms), searched within +-150 ms so that repeating loops
(one beat = 375 ms) cannot fake a match. A restart or jump fails it.
"""
import json
import os
import sys

import lameenc
import numpy as np
import soundfile as sf
from scipy import signal

from mlab import loudness as L
from mlab import sections as SE

V = os.path.expanduser("~/_agent_scratch/renders/versions/")
FULL = os.path.expanduser("~/_agent_scratch/renders/hw002_121_full.wav")
BPM, BAR = 160.0, 1.5
vid = sys.argv[1]
segs = [tuple(s) for s in json.loads(sys.argv[2])]
lead = int(sys.argv[3])
a0 = segs[0][0]
plan = ([(a0 - lead, a0 - 1)] if lead else []) + segs

full, sr = sf.read(FULL, always_2d=True, dtype="float64")
x, _ = sf.read(V + vid + ".wav", always_2d=True, dtype="float64")
exp = np.concatenate([full[int((a - 1) * BAR * sr):int(b * BAR * sr)] for a, b in plan])
fm, xm, em = full.mean(1), x.mean(1), exp.mean(1)


def best_lag(a, b, center, span):
    """Lag (samples) of window a inside b around center, and its correlation."""
    lo = max(0, center - span)
    seg = b[lo:center + span + len(a)]
    c = signal.fftconvolve(seg, a[::-1], "valid")
    na = np.sqrt(np.sum(a * a))
    nb = np.sqrt(np.convolve(seg * seg, np.ones(len(a)), "valid"))
    r = c / (na * nb + 1e-12)
    k = int(np.argmax(r))
    return lo + k - center, float(r[k])


# offset of the render against the plan, measured inside the lead-in after the junk head
w = int(1.5 * sr)
probe_at = int((lead * BAR - 1.6) * sr) if lead else int(1.2 * sr)
d, dc = best_lag(xm[probe_at:probe_at + w], em, probe_at, int(0.2 * sr))  # render t = plan t - d... (k is plan index)
offset = -d  # samples: render index = plan index + offset
start = max(0, int(lead * BAR * sr) + offset)
n = int(round(sum(b - a + 1 for a, b in segs) * BAR * sr))
y = x[start:start + n].copy()
f = int(0.01 * sr)
y[:f] *= np.linspace(0, 1, f)[:, None]
f = int(0.03 * sr)
y[-f:] *= np.linspace(1, 0, f)[:, None]
sf.write(V + vid + "-trim.wav", y, sr, subtype="PCM_24")

# timeline check on the kept part
ek = em[int(lead * BAR * sr): int(lead * BAR * sr) + n]
ym = y.mean(1)
win = int(0.25 * sr)
lags, corrs = [], []
for s in range(0, n - 2 * win, win):
    lg, c = best_lag(ym[s:s + win], ek, s, int(0.15 * sr))
    lags.append(lg / sr)
    corrs.append(c)
lags, corrs = np.array(lags), np.array(corrs)
good = corrs > 0.0
med = float(np.median(lags[good])) if good.any() else 0.0
jumps = [round(i * 0.25, 2) for i in np.where(np.abs(lags - med) > 0.035)[0]]  # stutter: 49-112 ms off; clean renders stay within ~20 ms

src_bars = [b for a, e in segs for b in range(a, e + 1)]
fl, fh = SE.bars(full, sr, BPM)
vl, vh = SE.bars(y, sr, BPM)
junction = {a for a, _ in segs}
bad = []
for i, b in enumerate(src_bars[:len(vl)]):
    dl, dh = vl[i] - fl[b - 1], vh[i] - fh[b - 1]
    if b in junction:
        continue
    if abs(dl) > 3 or abs(dh) > (4.5 if 81 <= b <= 96 else 3):
        bad.append([b, round(float(dl), 1), round(float(dh), 1)])

e = lameenc.Encoder()
e.set_bit_rate(320); e.set_in_sample_rate(sr); e.set_channels(2); e.set_quality(2)
mp3 = V + f"2026-10-01-hw002-{vid}.mp3"
open(mp3, "wb").write(e.encode((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()) + e.flush())
brk = []  # render-time ranges whose source bars are in the breakdown (81-96), which varies render to render
t = 0.0
for a, b2 in segs:
    for bb in range(a, b2 + 1):
        if 81 <= bb <= 96:
            brk.append((t, t + BAR))
        t += BAR
in_break = lambda ts: any(lo - 0.25 <= ts < hi for lo, hi in brk)
cuts, t = [], 0.0  # render times of the cuts between segments; windows touching a cut compare tails the splice lacks
for a, b2 in segs:
    cuts.append(t)
    t += (b2 - a + 1) * BAR
near_cut = lambda ts: any(c - 0.25 <= ts < c + 1.0 for c in cuts[1:])  # tails from the bar before a cut ring ~0.75 s
jumps = [j for j in jumps if not in_break(j) and not near_cut(j)]
unmatched_hard = []
ok = not jumps and not bad and not unmatched_hard and abs(med) <= 0.005
print(json.dumps({"id": vid, "ok": bool(ok), "offset_ms": round(offset / sr * 1000, 1), "offset_corr": round(dc, 2),
                  "duration_s": round(n / sr, 2), "lufs": round(L.integrated(y, sr), 1),
                  "true_peak_dbtp": round(L.true_peak(y, sr), 1), "timeline_windows": int(len(lags)),
                  "timeline_matched": round(float(good.mean()), 2), "timeline_median_lag_ms": round(med * 1000, 1), "timeline_jumps_at_s": jumps, "unmatched_outside_break_s": unmatched_hard, "min_corr_first_3s": round(float(corrs[:11].min()), 2),
                  "bars_off": bad, "mp3": mp3}))
