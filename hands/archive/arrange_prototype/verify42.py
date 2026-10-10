"""Verify a batch-4 version. uv run --with lameenc python verify4.py ID 'PLAN_JSON'

Hats are rewritten, so structure is checked on the low band (< 150 Hz):
measured trim offset in the lead-in, lag-based timeline check (glitch =
>35 ms off the median, windows near cuts/gaps and in breakdowns skipped),
per-bar low energy vs source, drop-out gaps silent. Then the hat steps:
2-16 kHz energy per hat section, which should rise step by step.
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
FULL = os.path.expanduser("~/_agent_scratch/renders/hw002_121_full_aligned.wav")  # song beat 0 at sample 0
BPM, BAR, LEAD = 160.0, 1.5, 2
vid = sys.argv[1]
plan = json.loads(sys.argv[2])
segs = [tuple(s) for s in plan["segs"]]
gaps = {j: g for j, g in plan.get("gaps", [])}

full, sr = sf.read(FULL, always_2d=True, dtype="float64")
x, _ = sf.read(V + vid + ".wav", always_2d=True, dtype="float64")
lp = signal.butter(4, 150, "low", fs=sr, output="sos")
low = lambda a: signal.sosfiltfilt(lp, a.mean(1))

a0 = segs[0][0]
plan_full = [(a0 - LEAD, a0 - 1)] + segs
parts, cuts, t = [], [], 0.0
for k, (a, b) in enumerate(plan_full):
    seg = full[int((a - 1) * BAR * sr):int(b * BAR * sr)].copy()
    # timeline element k precedes segs[k] (element 0 is the lead-in), so a gap
    # before segs[k] silences the end of element k
    if k in gaps:
        seg[-int(gaps[k] * 60 / BPM * sr):] = 0
    parts.append(seg)
    cuts.append(t)
    t += (b - a + 1) * BAR
exp = np.concatenate(parts)
el, xl = low(exp), low(x)


def best_lag(a, b, center, span):
    lo = max(0, center - span)
    seg = b[lo:center + span + len(a)]
    c = signal.fftconvolve(seg, a[::-1], "valid")
    na = np.sqrt(np.sum(a * a))
    nb = np.sqrt(np.convolve(seg * seg, np.ones(len(a)), "valid"))
    r = c / (na * nb + 1e-12)
    k = int(np.argmax(r))
    return lo + k - center, float(r[k])


# Where song beat 0 is in the take, from Live's own clip markers (record_arrangement
# writes <take>.timing.json). It varies per take (0 s or ~0.9 s seen), and the low
# band is too periodic for a correlation to find it reliably.
timing = json.load(open(V + vid + ".wav.timing.json"))
offset = int(round(timing["song_zero_seconds"] * sr))
probe = int((LEAD * BAR - 1.6) * sr)
d, dc = best_lag(xl[offset + probe:offset + probe + int(1.5 * sr)], el, probe, int(0.2 * sr))  # diagnostic only
start = offset + int(LEAD * BAR * sr)
n = int(round(sum(b - a + 1 for a, b in segs) * BAR * sr))
y = x[start:start + n].copy()
y[:int(0.01 * sr)] *= np.linspace(0, 1, int(0.01 * sr))[:, None]
y[-int(0.03 * sr):] *= np.linspace(1, 0, int(0.03 * sr))[:, None]
sf.write(V + vid + "-trim.wav", y, sr, subtype="PCM_24")

# timeline on the low band
yl = low(y)
ek = el[int(LEAD * BAR * sr): int(LEAD * BAR * sr) + n]
win = int(0.25 * sr)
lags, cors = [], []
for s in range(0, n - 2 * win, win):
    lg, c = best_lag(yl[s:s + win], ek, s, int(0.15 * sr))
    lags.append(lg / sr)
    cors.append(c)
lags, cors = np.array(lags), np.array(cors)
med = float(np.median(lags))
vcuts = [c - LEAD * BAR for c in cuts[2:]]  # cut times inside the kept part
brk = []
tt = 0.0
for a, b in segs:
    for bb in range(a, b + 1):
        if 81 <= bb <= 96:
            brk.append((tt, tt + BAR))
        tt += BAR
skip = lambda ts: any(c - 0.75 <= ts < c + 1.0 for c in vcuts) or any(lo - 0.25 <= ts < hi for lo, hi in brk)
# A slip or stutter moves consecutive windows; an isolated off-lag window with a weak
# match (corr < 0.6, e.g. between kick hits) is ambiguity, not a jump.
off = [i for i in np.where(np.abs(lags - med) > 0.035)[0] if not skip(i * 0.25)]
offs = set(off)
jumps = [round(i * 0.25, 2) for i in off if (i - 1) in offs or (i + 1) in offs or cors[i] >= 0.6]

# per-bar low energy vs source
src_bars = [b for a, e in segs for b in range(a, e + 1)]
fl, _ = SE.bars(full, sr, BPM)
vl, vh = SE.bars(y, sr, BPM)
seg_starts = set()
i = 0
for a, b in segs:
    seg_starts.add(i)
    i += b - a + 1
bad = []
for i, b in enumerate(src_bars[:len(vl)]):
    if i in seg_starts or (i + 1) in seg_starts:  # bars touching a cut or a drop-out
        continue
    if plan.get("wuh") and b in range(segs[plan["wuh"]["segment"]][0], segs[plan["wuh"]["segment"]][1] + 1):
        continue  # the re-placed beatbox phrase changes these bars on purpose
    if plan.get("break_db") is not None and 81 <= b <= 96:
        continue  # the breakdown fader was lowered on purpose
    dl = vl[i] - fl[b - 1]
    if abs(dl) > 3:
        bad.append([i + 1, b, round(float(dl), 1)])

# drop-out gaps must be (near) silent
gap_db = []
for j, g in sorted(gaps.items()):
    tj = sum((b - a + 1) for a, b in segs[:j]) * BAR
    gs = y[int((tj - g * 60 / BPM + 0.05) * sr):int((tj - 0.02) * sr)]
    gap_db.append(round(float(10 * np.log10(np.mean(gs ** 2) + 1e-12)), 1))

# hat steps
steps = []
for bar, nb, layers in plan["hats"]:
    steps.append([layers, round(float(vh[bar - 1:bar - 1 + nb].mean()), 1)])

# batch 4.2 fx checks
fxr = {}
SPB = 60 / BPM
hb = signal.butter(4, [4000, 16000], "bandpass", fs=sr, output="sos")
vb = signal.butter(4, [150, 2000], "bandpass", fs=sr, output="sos")
def band_db(a, t0, t1, sos=hb):
    seg = a[int(t0 * sr):int(t1 * sr)]
    return float(10 * np.log10(np.mean(signal.sosfilt(sos, seg.mean(1)) ** 2) + 1e-12))
seg_t = lambda j: sum((b - a + 1) for a, b in segs[:j]) * BAR   # version seconds where segment j starts
sp = plan.get("splash")
if sp:
    tj = seg_t(sp["drop_segment"])
    drop_bar = int(round(tj / BAR)) + 1
    SL = sp["drop_beats"]
    sec = next(((bar, nb) for bar, nb, _ in plan["hats"] if bar <= drop_bar < bar + nb), None)
    step = 2 if SL > 4 else 1
    if sec and drop_bar + step + (SL - 1) // 4 < sec[0] + sec[1]:
        fxr["drop_splash_tail_gain_db"] = round(band_db(y, tj + 2 * SPB, tj + SL * SPB) - band_db(y, tj + step * BAR + 2 * SPB, tj + step * BAR + SL * SPB), 1)
    else:
        fxr["drop_splash_tail_gain_db"] = "no clean comparison bar"
    # drop power: first 2 bars of the drop vs the last 2 bars before it, and vs the loudest breakdown bar
    fxr["drop_vs_prekick_lufs"] = round(L.integrated(y[int(tj * sr):int((tj + 2 * BAR) * sr)], sr) - L.integrated(y[int((tj - 2 * BAR) * sr):int(tj * sr)], sr), 1)
    brk_bars = [i for i, bb in enumerate(src_bars) if 81 <= bb <= 96]
    if brk_bars:
        loud = max(L.integrated(y[int(i * BAR * sr):int((i + 1) * BAR * sr)], sr) for i in brk_bars)
        fxr["drop_vs_loudest_break_bar_lufs"] = round(L.integrated(y[int(tj * sr):int((tj + BAR) * sr)], sr) - loud, 1)
w = plan.get("wuh")
if w:
    t0 = seg_t(w["segment"]) + w["start"] * SPB
    seg = signal.sosfilt(vb, y[int(t0 * sr):int((t0 + w["beats"] * SPB) * sr)].mean(1))
    h = int(0.05 * sr)
    lv = 10 * np.log10((seg[:len(seg) // h * h].reshape(-1, h) ** 2).mean(1) + 1e-12)
    fxr["wuh_seconds"] = round(w["beats"] * SPB, 2)
    fxr["wuh_dropouts"] = int(np.sum(lv < np.median(lv) - 20))
    # onsets on the grid: energy rise in the voice band within 30 ms of each planned start
    full_v = signal.sosfilt(vb, y.mean(1)) ** 2
    hop = int(0.005 * sr)
    env = 10 * np.log10(full_v[:len(full_v) // hop * hop].reshape(-1, hop).mean(1) + 1e-12)
    def onset_err(t):
        k = int(t / 0.005)
        win = env[max(0, k - 12):k + 12]
        d = np.diff(win)
        return round((int(np.argmax(d)) - (k - max(0, k - 12))) * 5.0, 1)
    planned = [t0]
    if w.get("slices"):
        sl = w["slices"]
        planned += [seg_t(w["segment"]) + (sl["start"] + k * sl["every"]) * SPB for k in range(sl["count"])]
    fxr["grid_onset_errors_ms"] = [onset_err(t) for t in planned]

e = lameenc.Encoder()
e.set_bit_rate(320); e.set_in_sample_rate(sr); e.set_channels(2); e.set_quality(2)
mp3 = V + f"2026-10-01-hw002-{vid}.mp3"
open(mp3, "wb").write(e.encode((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()) + e.flush())
# a gap after the breakdown is muted to digital silence by the Break group's Utility;
# after a kick section the kick group's own tails ring on, so only require a deep dip
gap_limits = [-50 if 81 <= segs[j - 1][1] <= 96 else -25 for j in sorted(gaps)]
ok = (not jumps and not bad and abs(med) <= 0.005 and all(gd < lim for gd, lim in zip(gap_db, gap_limits))
      and (not isinstance(fxr.get("drop_splash_tail_gain_db"), (int, float)) or fxr["drop_splash_tail_gain_db"] > 3)
      and fxr.get("wuh_dropouts", 0) == 0 and all(abs(e) <= 40 for e in fxr.get("grid_onset_errors_ms", [])))  # soft "w" attack reads ~25-35 ms late
print(json.dumps({"id": vid, "ok": bool(ok), "song_zero_ms": round(offset / sr * 1000, 1), "residual_lag_ms": round(-d / sr * 1000, 1), "residual_corr": round(dc, 2),
                  "duration_s": round(n / sr, 2), "lufs": round(L.integrated(y, sr), 1), "true_peak_dbtp": round(L.true_peak(y, sr), 1),
                  "timeline_median_lag_ms": round(med * 1000, 1), "timeline_jumps_at_s": jumps, "low_bars_off": bad,
                  "gap_level_db": gap_db, "hat_steps_high_db": steps, "fx": fxr, "mp3": mp3}))
