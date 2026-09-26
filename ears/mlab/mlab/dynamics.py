"""Dynamics measures (subject 3: Ch. 5-7).

Macrodynamics = loudness change between sections (seconds to minutes):
  LRA, short-term spread, section loudness.
Microdynamics = level change inside a beat (milliseconds):
  crest factor per 400 ms block, transient-to-body contrast at onsets.

`comp_probe` reverse-engineers a compressor from a render of the probe
signal (`siggen.comp_probe`) through it: static curve, ratio, threshold,
knee, attack and release. Calibrated against `dsp.compressor`.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .util import db, pdb, r, rms
from . import loudness as L


def crest_db(x):
    """Sample peak over RMS, both channels pooled. Sine = 3.01 dB."""
    return float(db(np.max(np.abs(x))) - db(rms(x))) if x.size else float("nan")


def micro(x, sr, block_s=0.4):
    """Per-block crest (peak/RMS) over loud blocks. Median = typical punch inside a beat."""
    n = int(block_s * sr)
    vals, levels = [], []
    for i in range(0, len(x) - n + 1, n):
        b = x[i:i + n]
        lv = db(rms(b))
        levels.append(lv)
        vals.append(crest_db(b))
    vals, levels = np.array(vals), np.array(levels)
    if vals.size == 0:
        return {}
    loud = levels > (np.max(levels) - 20)
    v = vals[loud]
    return {"block_crest_median_db": r(np.median(v)), "block_crest_p10_db": r(np.percentile(v, 10)),
            "block_crest_p90_db": r(np.percentile(v, 90))}


def envelope_db(x, sr, attack_ms, release_ms):
    """Peak envelope follower (dB) on the channel max."""
    rect = np.max(np.abs(x), axis=1)
    aa = np.exp(-1.0 / (sr * attack_ms / 1000))
    ar = np.exp(-1.0 / (sr * release_ms / 1000))
    out = np.empty_like(rect)
    s = 0.0
    for i, v in enumerate(rect.tolist()):
        c = aa if v > s else ar
        s = c * s + (1 - c) * v
        out[i] = s
    return db(out)


def transient_contrast(x, sr, hit_ms=10.0, body=(20.0, 120.0)):
    """'Punch' at each onset: peak in the first `hit_ms` minus RMS of the body window
    (20-120 ms after the onset), in dB. Median over onsets.

    Designed for kick-driven music. A compressor with slow attack lets the hit through
    and turns the body down -> contrast rises most. Very fast attack clamps the hit too,
    so it rises less (it can still beat dry). Limiting the hits -> contrast falls. Calibrated on a synthetic kick loop (calibration/checks.py)."""
    m = np.max(np.abs(x), axis=1)
    hop = max(1, int(0.002 * sr))
    w = max(1, int(0.005 * sr))
    e = np.sqrt(signal.lfilter(np.ones(w) / w, [1], m ** 2))[::hop]
    ed = db(e)
    flux = np.diff(ed, prepend=ed[0])
    peaks, _ = signal.find_peaks(flux, height=4, distance=int(0.1 * sr / hop))
    if len(peaks) < 3:
        return {"onsets": int(len(peaks))}
    h, b0, b1 = int(hit_ms / 1000 * sr), int(body[0] / 1000 * sr), int(body[1] / 1000 * sr)
    hits, bods = [], []
    for p in peaks:
        on = max(0, p * hop - w)                     # envelope lags the true onset by ~one window
        if on + b1 > len(m):
            break
        hits.append(float(db(np.max(m[on:on + h + w]))))
        bods.append(float(db(np.sqrt(np.mean(m[on + b0:on + b1] ** 2)))))
    hits, bods = np.array(hits), np.array(bods)
    keep = hits >= hits.max() - 10 if hits.size else hits.astype(bool)   # main hits only (kicks)
    if keep.sum() < 3:
        return {"onsets": int(keep.sum())}
    return {"onsets": int(keep.sum()), "transient_contrast_median_db": r(np.median(hits[keep] - bods[keep]))}


def macro(lres: L.LoudnessResult):
    st = lres.short_term
    st = st[st > -70]
    if st.size == 0:
        return {}
    return {"lra_lu": r(lres.lra), "short_term_p95_minus_p10": r(np.percentile(st, 95) - np.percentile(st, 10)),
            "short_term_max_minus_integrated": r(lres.short_term_max - lres.integrated)}


def analyze(x, sr, lres: L.LoudnessResult | None = None):
    lres = lres or L.analyze(x, sr)
    rm = rms(x)
    out = {"crest_db": r(crest_db(x)), "plr_db": r(lres.plr), "psr_min_db": r(lres.psr_min),
           "k20_rms_db": r(db(rm) + 3.0103 + 20), "k14_rms_db": r(db(rm) + 3.0103 + 14)}
    out.update(macro(lres))
    out.update(micro(x, sr))
    out.update(transient_contrast(x, sr))
    return out


# --------------------------------------------------------- compressor probe
def probe_align(dry, wet, thresh_dbfs=-80.0):
    """Align a probe render by the silence-to-tone onset, not by cross-correlation.
    The probe is a steady 1 kHz tone, so correlation is ambiguous by whole cycles
    (a plugin with lookahead would shift attack/release by milliseconds)."""
    th = 10 ** (thresh_dbfs / 20)
    def onset(x):
        idx = np.flatnonzero(np.max(np.abs(x), axis=1) > th)
        return int(idx[0]) if idx.size else 0
    lag = onset(wet) - onset(dry)
    if lag > 0:
        wet = wet[lag:]
    elif lag < 0:
        dry = dry[-lag:]
    n = min(len(dry), len(wet))
    return dry[:n], wet[:n], lag


def gain_curve_db(dry, wet, sr, win_ms=2.0):
    """Frame-wise gain wet/dry in dB (RMS over win_ms). Needs aligned signals."""
    n = max(1, int(sr * win_ms / 1000))
    k = len(dry) // n
    d = np.sqrt(np.mean(dry[:k * n].reshape(k, n, -1) ** 2, axis=(1, 2)))
    w = np.sqrt(np.mean(wet[:k * n].reshape(k, n, -1) ** 2, axis=(1, 2)))
    ok = d > 1e-6
    g = np.full(k, np.nan)
    g[ok] = db(w[ok]) - db(d[ok])
    t = (np.arange(k) + 0.5) * n / sr
    return t, g, db(d)


def comp_probe(dry, wet, sr, layout=None):
    """Estimate compressor parameters from a render of siggen.comp_probe().

    layout: dict from the probe's sidecar JSON (segment times). Returns a dict."""
    from .siggen import COMP_PROBE_LAYOUT
    lay = layout or COMP_PROBE_LAYOUT
    t, g, lvl = gain_curve_db(dry, wet, sr)
    out = {}
    # static curve from the slow ramp: input level (sine-referenced) vs output level
    a, b = lay["ramp"]
    m = (t > a + 0.05) & (t < b - 0.05) & np.isfinite(g)
    lin_in = lvl[m] + 3.0103                    # dBFS of the sine's peak
    gg = g[m]
    makeup = float(np.median(gg[lin_in < lin_in.min() + 6]))   # gain well below threshold
    gr = makeup - gg
    out["makeup_db"] = r(makeup)
    best = None
    for th in np.arange(-60, 0.01, 0.25):
        for kn in (0, 2, 4, 6, 8, 10, 12):
            over = lin_in - th
            # fit slope s = 1-1/ratio by least squares on the soft-knee shape
            basis = np.where(over <= -kn / 2, 0, np.where(over >= kn / 2, over,
                             (over + kn / 2) ** 2 / (2 * kn) if kn else over))
            den = float(np.dot(basis, basis))
            if den <= 0:
                continue
            s = float(np.clip(np.dot(basis, gr) / den, 0, 1))
            err = float(np.mean((gr - s * basis) ** 2))
            if best is None or err < best[0]:
                best = (err, th, kn, s)
    if best:
        err, th, kn, s = best
        out.update({"threshold_db": r(th), "knee_db": r(kn), "ratio": r(1 / (1 - s)) if s < 0.999 else 999.0,
                    "static_fit_rms_err_db": r(np.sqrt(err), 3)})
    # time constants from the level steps: 63 % of each GR change (fine 0.5 ms frames)
    t, g, _ = gain_curve_db(dry, wet, sr, win_ms=0.5)
    atk, rel = [], []
    for (t0, t1, kind) in lay["steps"]:
        seg = (t >= t0) & (t < t1) & np.isfinite(g)
        if seg.sum() < 5:
            continue
        ts, gs = t[seg] - t0, makeup - g[seg]
        start, end = gs[0], np.median(gs[-max(3, len(gs) // 10):])
        if abs(end - start) < 1.0:
            continue
        frac = (gs - start) / (end - start)
        idx = np.argmax(frac >= 1 - np.exp(-1))
        # ts are frame centres; the frame straddling the step lags by half a frame
        (atk if kind == "up" else rel).append(max(0.0, (ts[idx] - 0.25e-3)) * 1000)
    if atk:
        out["attack_ms"] = r(np.median(atk), 1)
    if rel:
        out["release_ms"] = r(np.median(rel), 1)
    out["note"] = ("attack/release = time to 63 % of the gain change after a 30 dB step; "
                   "compare devices with the same probe, not with their knob labels")
    return out
