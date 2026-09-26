"""Reference processors for experiments.

These are deliberately plain, documented processors. They let a hypothesis
be tested in Python when an Ableton render is not needed or not possible.
They are NOT emulations of Live devices. When a claim is about a specific
device (Glue Compressor, EQ Eight, Limiter), render it in Live and measure
the render with `comp-probe` / `eq-diff` instead.

Every processor takes and returns float64 (n, ch).
"""
from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d

from .util import db, lin
from . import loudness as L


# ---------------------------------------------------------------- EQ (Ch. 4)
def biquad(kind: str, f0: float, sr: int, gain_db: float = 0.0, q: float = 0.707):
    """RBJ Audio-EQ-Cookbook biquads. kind: peak, lowshelf, highshelf, highpass, lowpass.

    Shelves use q as the cookbook's Q (0.707 = no overshoot)."""
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sa = 2 * np.sqrt(A) * alpha
        s = 1 if kind == "lowshelf" else -1
        b = [A * ((A + 1) - s * (A - 1) * cw + sa),
             s * 2 * A * ((A - 1) - s * (A + 1) * cw),
             A * ((A + 1) - s * (A - 1) * cw - sa)]
        a = [(A + 1) + s * (A - 1) * cw + sa,
             -s * 2 * ((A - 1) + s * (A + 1) * cw),
             (A + 1) + s * (A - 1) * cw - sa]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)
    b, a = np.array(b), np.array(a)
    return b / a[0], a / a[0]


def eq(x, sr, bands):
    """bands: list of dicts {type, f, gain_db, q}. Applied in series."""
    y = x
    for bd in bands:
        b, a = biquad(bd["type"], bd["f"], sr, bd.get("gain_db", 0.0), bd.get("q", 0.707))
        y = signal.lfilter(b, a, y, axis=0)
    return y


def biquad_response_db(kind, f0, sr, gain_db, q, freqs):
    b, a = biquad(kind, f0, sr, gain_db, q)
    _, h = signal.freqz(b, a, worN=np.asarray(freqs), fs=sr)
    return db(h)


# ----------------------------------------------------- dynamics (Ch. 5-7)
def gain_computer(level_db, threshold, ratio, knee):
    """Static curve: dB of gain reduction (>= 0) for a detector level in dB.

    Soft knee per Giannoulis, Massberg & Reiss (JAES 2012)."""
    over = level_db - threshold
    slope = 1 - 1 / ratio
    gr = np.where(over <= -knee / 2, 0.0, over * slope)
    if knee > 0:
        inknee = np.abs(over) < knee / 2
        gr = np.where(inknee, slope * (over + knee / 2) ** 2 / (2 * knee), gr)
    return np.maximum(gr, 0.0)


def compressor(x, sr, threshold=-20.0, ratio=4.0, attack_ms=10.0, release_ms=100.0,
               knee=6.0, makeup_db=0.0, detector="peak", rms_ms=10.0, hold_ms=5.0, return_gr=False):
    """Feed-forward, stereo-linked compressor with a smoothed-gain (log-domain) ballistic.

    detector: 'peak' (instant rectified max of channels) or 'rms' (rms_ms window).
    Attack/release are one-pole time constants (time to 63 % of a step)."""
    if detector == "rms":
        w = max(1, int(sr * rms_ms / 1000))
        pw = signal.lfilter(np.ones(w) / w, [1.0], np.mean(x ** 2, axis=1))
        lvl = 10 * np.log10(np.maximum(pw, 1e-20)) + 3.0103  # sine-referenced (AES-17)
    else:
        # peak detector with a short hold: without it, a sine's zero crossings make the
        # gain computer chatter and the effective attack becomes much slower than the knob.
        lvl = db(_causal_max(np.max(np.abs(x), axis=1), max(1, int(sr * hold_ms / 1000))))
    target = gain_computer(lvl, threshold, ratio, knee)
    aa = np.exp(-1.0 / (sr * attack_ms / 1000))
    ar = np.exp(-1.0 / (sr * release_ms / 1000))
    gr = _ballistics(target, aa, ar)
    y = x * lin(makeup_db - gr)[:, None]
    return (y, gr) if return_gr else y


def _causal_max(v, h):
    """max(v[i-h+1 .. i]) for every i."""
    if h <= 1:
        return v
    from scipy.ndimage import maximum_filter1d
    c = maximum_filter1d(v, size=h, mode="nearest")      # centred window
    k = (h - 1) // 2
    return np.concatenate([np.full(k, c[0]), c[:len(c) - k]]) if k else c


def _ballistics(target, aa, ar):
    out = np.empty_like(target)
    s = 0.0
    t = target.tolist()
    for i, v in enumerate(t):
        c = aa if v > s else ar
        s = c * s + (1 - c) * v
        out[i] = s
    return out


def limiter(x, sr, ceiling_db=-1.0, lookahead_ms=5.0, release_ms=80.0, true_peak=True):
    """Lookahead brickwall limiter. true_peak=True detects on the 8x oversampled signal,
    so the output's TRUE peak stays at or under the ceiling (verified in calibration)."""
    la = max(1, int(sr * lookahead_ms / 1000))
    c = lin(ceiling_db)
    if true_peak:
        f = L.oversample_factor(sr)
        up = L.true_peak_signal(x, sr, f)[: f * len(x)]
        pk = up.reshape(len(x), f, -1).max(axis=(1, 2))
    else:
        pk = np.max(np.abs(x), axis=1)
    g = np.minimum(1.0, c / np.maximum(pk, 1e-12))
    g = minimum_filter1d(g, size=2 * la + 1, mode="nearest")
    # smooth the gain: instant-ish attack across the lookahead, one-pole release
    ar = np.exp(-1.0 / (sr * release_ms / 1000))
    gs = _ballistics(-db(g), 0.0, ar)
    y = x * lin(-gs)[:, None]
    # safety: a final true-peak trim for residual interpolation overs
    tp = L.true_peak(y, sr) if true_peak else float(db(np.max(np.abs(y))))
    if tp > ceiling_db:
        y = y * lin(ceiling_db - tp)
    return y


def master_to(x, sr, target_lufs, ceiling_db=-1.0, **kw):
    """Drive the limiter until integrated loudness hits target. Returns (y, drive_db)."""
    lo, hi = -24.0, 48.0
    y = x
    for _ in range(20):
        g = (lo + hi) / 2
        y = limiter(x * lin(g), sr, ceiling_db, **kw)
        if L.integrated(y, sr) < target_lufs:
            lo = g
        else:
            hi = g
    got = L.integrated(y, sr)
    if abs(got - target_lufs) > 0.3:
        import warnings
        warnings.warn(f"master_to: reached {got:.2f} LUFS, not {target_lufs} (limiter saturated)")
    return y, (lo + hi) / 2


def clip(x, ceiling_db=0.0, mode="hard"):
    c = lin(ceiling_db)
    if mode == "hard":
        return np.clip(x, -c, c)
    return c * np.tanh(x / c)


# ------------------------------------------------- word length (Ch. 15)
def quantize(x, bits=16, dither="tpdf", shaping=False, seed=0):
    """Reduce to `bits` (full scale +/-1). dither: none | rpdf | tpdf.
    'none' ROUNDS (no bias); use truncate() for true truncation.
    shaping=True adds first-order error-feedback noise shaping (pushes noise up)."""
    q = 2.0 ** (1 - bits)
    rng = np.random.default_rng(seed)
    if dither == "tpdf":
        d = (rng.random(x.shape) - rng.random(x.shape)) * q
    elif dither == "rpdf":
        d = (rng.random(x.shape) - 0.5) * q
    else:
        d = np.zeros_like(x)
    if not shaping:
        y = np.round((x + d) / q) * q
    else:
        y = np.empty_like(x)
        e = np.zeros(x.shape[1])
        for i in range(x.shape[0]):
            v = x[i] - e
            y[i] = np.round((v + d[i]) / q) * q
            e = y[i] - v
    return np.clip(y, -1.0, 1.0 - q)


def truncate(x, bits=16):
    q = 2.0 ** (1 - bits)
    return np.floor(x / q) * q


# ------------------------------------------------- misc experiment ops
def gain(x, gain_db):
    return x * lin(gain_db)


def normalize_lufs(x, sr, target):
    return x * lin(L.gain_to(x, sr, target))


def to_mono(x):
    m = x.mean(axis=1, keepdims=True)
    return np.repeat(m, x.shape[1], axis=1)


def ms_width(x, side_gain_db=0.0):
    m = (x[:, 0] + x[:, 1]) / 2
    s = (x[:, 0] - x[:, 1]) / 2 * lin(side_gain_db)
    return np.stack([m + s, m - s], 1)


def excerpt(x, sr, start_s, dur_s, fade_ms=10.0):
    a, b = int(start_s * sr), int((start_s + dur_s) * sr)
    y = x[a:b].copy()
    nf = int(sr * fade_ms / 1000)
    if nf and len(y) > 2 * nf:
        ramp = np.sin(np.linspace(0, np.pi / 2, nf)) ** 2
        y[:nf] *= ramp[:, None]
        y[-nf:] *= ramp[::-1, None]
    return y
