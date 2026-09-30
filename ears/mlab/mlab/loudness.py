"""Loudness and peak metering (subject 5: Ch. 17-19).

Implements ITU-R BS.1770-4/-5 loudness and EBU Tech 3342 loudness range.

- K-weighting: the two BS.1770 biquads, derived for any sample rate from
  their analog parameters (at 48 kHz they reproduce the spec's
  coefficient table; calibration checks this).
- Momentary (400 ms), short-term (3 s), integrated (gated), LRA.
- True peak: 8x oversampling below 96 kHz (BS.1770 asks for >= 4x;
  8x halves the worst-case under-read for little cost).

Channel weights: 1.0 for every channel. Surround weights are not
supported; a mono file counts as one channel, exactly as BS.1770 says.
Note that some meters treat mono as dual-mono (+3 dB). This one does not.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from .util import db, pdb, r

ABS_GATE = -70.0
REL_GATE_I = -10.0     # integrated loudness relative gate (BS.1770)
REL_GATE_LRA = -20.0   # loudness range relative gate (EBU Tech 3342)
OFFSET = -0.691


def k_weighting(sr: int):
    """Return [(b, a), (b, a)] for the pre-filter shelf and the RLB high-pass."""
    # Stage 1: high shelf (head acoustics)
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = np.tan(np.pi * f0 / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b1 = [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a1 = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    # Stage 2: RLB high-pass
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = np.tan(np.pi * f0 / sr)
    a0 = 1 + K / Q + K * K
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    return [(np.array(b1), np.array(a1)), (np.array(b2), np.array(a2))]


def k_filter(x: np.ndarray, sr: int) -> np.ndarray:
    y = x
    for b, a in k_weighting(sr):
        y = signal.lfilter(b, a, y, axis=0)
    return y


def _block_power(y: np.ndarray, sr: int, win_s: float, hop_s: float) -> np.ndarray:
    """Mean-square per channel for sliding rectangular windows -> summed over channels."""
    win, hop = int(round(win_s * sr)), int(round(hop_s * sr))
    if y.shape[0] < win:
        return np.array([])
    c = np.cumsum(np.vstack([np.zeros((1, y.shape[1])), y ** 2]), axis=0)
    starts = np.arange(0, y.shape[0] - win + 1, hop)
    ms = (c[starts + win] - c[starts]) / win
    return ms.sum(axis=1)          # channel weights all 1.0


def _lk(p):
    return OFFSET + pdb(p)


@dataclass
class LoudnessResult:
    integrated: float
    momentary_max: float
    short_term_max: float
    lra: float
    lra_low: float
    lra_high: float
    sample_peak: float
    true_peak: float
    plr: float                 # peak-to-loudness ratio: true peak - integrated
    psr_min: float             # min over time of true-peak(3 s) - short-term; low = squashed
    momentary: np.ndarray
    short_term: np.ndarray

    def summary(self) -> dict:
        return {k: r(getattr(self, k)) for k in
                ("integrated", "momentary_max", "short_term_max", "lra", "lra_low",
                 "lra_high", "sample_peak", "true_peak", "plr", "psr_min")}


def momentary(x, sr, hop_s=0.1):
    return _lk(_block_power(k_filter(x, sr), sr, 0.4, hop_s))


def short_term(x, sr, hop_s=0.1):
    return _lk(_block_power(k_filter(x, sr), sr, 3.0, hop_s))


def integrated(x: np.ndarray, sr: int) -> float:
    p = _block_power(k_filter(x, sr), sr, 0.4, 0.1)   # 75 % overlap
    return _gate_integrated(p)


def _gate_integrated(p: np.ndarray) -> float:
    if p.size == 0:
        return float("nan")
    l = _lk(p)
    p1 = p[l > ABS_GATE]
    if p1.size == 0:
        return float("nan")          # silent (below the -70 LUFS gate): loudness undefined
    rel = _lk(p1.mean()) + REL_GATE_I
    p2 = p1[_lk(p1) > rel]
    return float(_lk(p2.mean()))


def loudness_range(st: np.ndarray):
    """EBU Tech 3342 LRA from short-term values (LUFS). Returns (lra, p10, p95)."""
    st = st[st > ABS_GATE]
    if st.size < 2:
        return float("nan"), float("nan"), float("nan")
    p = 10 ** ((st - OFFSET) / 10)
    rel = _lk(p.mean()) + REL_GATE_LRA
    g = np.sort(st[st > rel])
    if g.size < 2:
        return float("nan"), float("nan"), float("nan")
    lo, hi = np.percentile(g, 10), np.percentile(g, 95)
    return float(hi - lo), float(lo), float(hi)


def oversample_factor(sr: int) -> int:
    return 8 if sr < 96000 else (4 if sr < 192000 else 2)


def true_peak_signal(x: np.ndarray, sr: int, factor: int | None = None) -> np.ndarray:
    """Oversampled absolute signal (per channel). Used for TP and TP-aware limiting."""
    f = factor or oversample_factor(sr)
    # Long Kaiser-windowed FIR: flat passband to ~0.45 fs keeps the estimate honest
    # for content near Nyquist, where inter-sample overs actually live.
    up = signal.resample_poly(x, f, 1, axis=0, window=("kaiser", 10.0))
    return np.abs(up)


def true_peak_envelope(x: np.ndarray, sr: int, factor: int | None = None, chunk: int = 1 << 18) -> np.ndarray:
    """Per original sample: max over channels and the `factor` interpolated points after it.
    Chunked with 512-sample overlap so an 84 s file needs ~50 MB, not ~1 GB."""
    f = factor or oversample_factor(sr)
    n = len(x)
    out = np.empty(n)
    pad = 512
    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        lo, hi = max(0, a - pad), min(n, b + pad)
        up = np.abs(signal.resample_poly(x[lo:hi], f, 1, axis=0, window=("kaiser", 10.0)))
        up = up[(a - lo) * f:(a - lo) * f + (b - a) * f]
        out[a:b] = up.reshape(b - a, f, -1).max(axis=(1, 2))
    return out


def true_peak(x: np.ndarray, sr: int, factor: int | None = None) -> float:
    return float(db(np.max(true_peak_envelope(x, sr, factor)))) if x.size else float("-inf")


def true_peak_per_channel(x, sr):
    return [true_peak(x[:, [c]], sr) for c in range(x.shape[1])]


def sample_peak(x: np.ndarray) -> float:
    return float(db(np.max(np.abs(x)))) if x.size else float("-inf")


def analyze(x: np.ndarray, sr: int) -> LoudnessResult:
    y = k_filter(x, sr)
    pm = _block_power(y, sr, 0.4, 0.1)
    ps = _block_power(y, sr, 3.0, 0.1)
    m, s = _lk(pm), _lk(ps)
    I = _gate_integrated(pm)
    lra, lo, hi = loudness_range(s)
    tp_sig = true_peak_envelope(x, sr)
    tp = float(db(tp_sig.max()))
    psr_min = _psr_min(tp_sig, s, sr)
    return LoudnessResult(
        integrated=I,
        momentary_max=float(m.max()) if m.size and m.max() > ABS_GATE else float("nan"),
        short_term_max=float(s.max()) if s.size and s.max() > ABS_GATE else float("nan"),
        lra=lra, lra_low=lo, lra_high=hi,
        sample_peak=sample_peak(x), true_peak=tp, plr=tp - I, psr_min=psr_min,
        momentary=m, short_term=s)


def _psr_min(tp_sig, st, sr):
    """Peak-to-short-term-loudness ratio, minimum over gated 3 s windows."""
    if st.size == 0:
        return float("nan")
    win, hop = int(3 * sr), int(0.1 * sr)
    vals = []
    for i, s in enumerate(st):
        if s <= ABS_GATE:
            continue
        seg = tp_sig[i * hop: i * hop + win]
        if seg.size:
            vals.append(float(db(seg.max())) - s)
    return min(vals) if vals else float("nan")


def gain_to(x: np.ndarray, sr: int, target_lufs: float) -> float:
    """dB of gain that moves integrated loudness to target."""
    return target_lufs - integrated(x, sr)
