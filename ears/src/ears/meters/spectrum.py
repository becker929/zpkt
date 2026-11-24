"""Tonal balance, EQ measurement and equal-loudness (subject 2: Ch. 4).

- `third_octave`: 1/3-octave band levels (IEC 61260 base-10 centres).
- `tonal_balance`: band groups and a spectral slope in dB/octave.
- `eq_diff`: the transfer function a device applied, from dry and wet files
  (H1 estimator: cross-spectrum / input spectrum, with coherence).
- `iso226`: equal-loudness contours (ISO 226:2003 parameters).
- `perceived_balance`: band levels re-weighted by the contour at a
  listening level, to test "bass vanishes when you turn down" claims.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import signal

from . import bands as B
from .arrays import FloatArray, Json
from .util import db, pdb, r

CENTRES = B.THIRD_OCTAVE_CENTRES  # the band tables live in bands.py; these names stay for callers
GROUPS = B.TONAL_GROUPS


def psd(x: FloatArray, sr: int, nperseg: int | None = None) -> tuple[FloatArray, FloatArray]:
    """Welch power spectral density of the channel-summed power (per-channel average)."""
    nperseg = nperseg or min(len(x), 2 ** int(np.log2(sr / 2)))  # 2^15 at 44.1/48 kHz: ~1.3-1.5 Hz bins
    f, p = signal.welch(x, sr, window="hann", nperseg=nperseg, axis=0, scaling="density")
    return f, p.mean(axis=1) if p.ndim == 2 else p


def band_power(f: FloatArray, p: FloatArray, lo: float, hi: float) -> float:
    m = (f >= lo) & (f < hi)
    if not m.any():
        return 0.0
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz  # type: ignore[attr-defined]  # numpy < 2
    return float(integrate(p[m], f[m]))


def third_octave(x: FloatArray, sr: int, f_p: tuple[FloatArray, FloatArray] | None = None) -> list[tuple[float, float]]:
    f, p = f_p if f_p is not None else psd(x, sr)
    out = []
    for c, lo, hi in zip(CENTRES, *B.third_octave_edges(CENTRES), strict=True):
        if hi > sr / 2:
            break
        out.append((float(c), float(pdb(band_power(f, p, lo, hi)))))
    return out


def tonal_balance(x: FloatArray, sr: int, f_p: tuple[FloatArray, FloatArray] | None = None) -> Json:
    f, p = f_p if f_p is not None else psd(x, sr)
    total = band_power(f, p, 20, min(20000, sr / 2))
    groups = {k: r(pdb(band_power(f, p, lo, min(hi, sr / 2)) / max(total, 1e-30))) for k, (lo, hi) in GROUPS.items()}
    bands = third_octave(x, sr, (f, p))
    fc = np.array([b[0] for b in bands])
    lv = np.array([b[1] for b in bands])
    # per-band level normalised by bandwidth -> slope of the power density in dB/oct
    m = (fc >= 100) & (fc <= 10000)
    dens = lv - 10 * np.log10(B.third_octave_width(fc))
    slope = float(np.polyfit(np.log2(fc[m]), dens[m], 1)[0]) if m.sum() > 3 else float("nan")
    # 10*log10 density slope: pink noise = -3.01 dB/oct, white = 0
    return {
        "groups_db_rel_total": groups,
        "slope_db_per_oct": r(slope),
        "third_octave": [(r(c, 1), r(level)) for c, level in bands],
    }


def centroid(x: FloatArray, sr: int, f_p: tuple[FloatArray, FloatArray] | None = None) -> float:
    f, p = f_p if f_p is not None else psd(x, sr)
    m = (f >= 20) & (f <= 20000)
    return float(np.sum(f[m] * p[m]) / max(np.sum(p[m]), 1e-30))


def stereo_by_band(x: FloatArray, sr: int, edges: Sequence[float] = B.STEREO_EDGES) -> list[Json]:
    """Correlation and side/mid energy per band. Low-band correlation near 1 = mono bass."""
    if x.shape[1] < 2:
        return []
    out = []
    for lo, hi in itertools.pairwise(edges):
        hi = min(hi, sr / 2 * 0.99)
        sos = signal.butter(4, [lo, hi], "bandpass", fs=sr, output="sos")
        y = signal.sosfiltfilt(sos, x, axis=0)
        left, right = y[:, 0], y[:, 1]
        den = np.sqrt(np.sum(left * left) * np.sum(right * right))
        corr = float(np.sum(left * right) / den) if den > 0 else 1.0
        m, s = (left + right) / 2, (left - right) / 2
        out.append(
            {
                "band_hz": [lo, int(hi)],
                "correlation": r(corr, 3),
                "side_minus_mid_db": r(pdb(np.mean(s * s)) - pdb(np.mean(m * m))),
            }
        )
    return out


def compare(x: FloatArray, ref: FloatArray, sr: int, sr_ref: int | None = None) -> list[tuple[Any, Any]]:
    """Tonal difference x - ref per 1/3 octave after equal-loudness normalisation
    (both brought to the same total power, so only shape differs)."""
    a = third_octave(x, sr)
    b = third_octave(ref, sr_ref or sr)
    n = min(len(a), len(b))
    la = np.array([v for _, v in a[:n]])
    lb = np.array([v for _, v in b[:n]])
    la -= pdb(np.sum(10 ** (la / 10)))
    lb -= pdb(np.sum(10 ** (lb / 10)))
    return [(r(a[i][0], 1), r(la[i] - lb[i])) for i in range(n)]


# ---------------------------------------------------------------- EQ diff
def eq_diff(dry: FloatArray, wet: FloatArray, sr: int, nperseg: int = 16384, smooth_oct: float = 1 / 6) -> Json:
    """Magnitude response wet/dry (dB) with coherence. Signals must be time-aligned
    (use align()). Returns dict with log-spaced frequency grid."""
    d, w = dry.mean(axis=1), wet.mean(axis=1)
    f, pxy = signal.csd(d, w, sr, nperseg=nperseg)
    _, pxx = signal.welch(d, sr, nperseg=nperseg)
    _, coh = signal.coherence(d, w, sr, nperseg=nperseg)
    h = pxy / np.maximum(pxx, 1e-30)
    grid = 20 * 2 ** np.arange(0, np.log2(min(20000, sr / 2 * 0.95) / 20), 1 / 12)
    mag, co = [], []
    for g in grid:
        lo, hi = g * 2 ** (-smooth_oct / 2), g * 2 ** (smooth_oct / 2)
        m = (f >= lo) & (f < hi)
        if not m.any():
            m = np.argmin(np.abs(f - g)) == np.arange(len(f))
        mag.append(float(db(np.sqrt(np.mean(np.abs(h[m]) ** 2)))))
        co.append(float(np.mean(coh[m])))
    return {"freq_hz": grid.tolist(), "gain_db": mag, "coherence": co}


def align(
    dry: FloatArray, wet: FloatArray, max_lag_s: float = 0.5, sr: int = 48000
) -> tuple[FloatArray, FloatArray, int]:
    """Shift wet to line up with dry (plugin latency). Returns (dry, wet, lag_samples)."""
    a, b = dry.mean(axis=1), wet.mean(axis=1)
    n = min(len(a), len(b), int(sr * 10))
    c = signal.correlate(b[:n], a[:n], mode="full", method="fft")
    lags = signal.correlation_lags(n, n, mode="full")
    ml = int(sr * max_lag_s)
    m = np.abs(lags) <= ml
    lag = int(lags[m][np.argmax(c[m])])
    if lag > 0:
        wet = wet[lag:]
    elif lag < 0:
        dry = dry[-lag:]
    L = min(len(dry), len(wet))
    return dry[:L], wet[:L], lag


def summarize_eq(res: Json, min_coh: float = 0.9, min_db: float = 0.5) -> Json:
    """Name the main moves: largest boost, largest cut, low/high shelf trend."""
    f = np.array(res["freq_hz"])
    g = np.array(res["gain_db"])
    c = np.array(res["coherence"])
    ok = c >= min_coh
    if not ok.any():
        return {"note": "coherence too low: dry and wet do not correspond (not aligned, or not LTI)"}
    # absolute gains (EQ devices have no makeup by default); the broadband offset is
    # reported separately so a gain change is not mistaken for a tonal move
    g0 = float(np.median(g[ok]))
    rel = g
    out = {
        "broadband_median_gain_db": r(g0),
        "at_hz": {str(int(x)): r(np.interp(x, f, g)) for x in (30, 60, 100, 200, 500, 1000, 3000, 6000, 10000, 16000)},
    }
    i_max, i_min = int(np.argmax(np.where(ok, rel, -99))), int(np.argmin(np.where(ok, rel, 99)))
    if rel[i_max] > min_db:
        out["largest_boost"] = {"hz": r(f[i_max], 0), "db": r(rel[i_max])}
    if rel[i_min] < -min_db:
        out["largest_cut"] = {"hz": r(f[i_min], 0), "db": r(rel[i_min])}
    return out


# ------------------------------------------------ equal loudness (ISO 226)
_F = np.array(
    [
        20,
        25,
        31.5,
        40,
        50,
        63,
        80,
        100,
        125,
        160,
        200,
        250,
        315,
        400,
        500,
        630,
        800,
        1000,
        1250,
        1600,
        2000,
        2500,
        3150,
        4000,
        5000,
        6300,
        8000,
        10000,
        12500,
    ]
)
_AF = np.array(
    [
        0.532,
        0.506,
        0.480,
        0.455,
        0.432,
        0.409,
        0.387,
        0.367,
        0.349,
        0.330,
        0.315,
        0.301,
        0.288,
        0.276,
        0.267,
        0.259,
        0.253,
        0.250,
        0.246,
        0.244,
        0.243,
        0.243,
        0.243,
        0.242,
        0.242,
        0.245,
        0.254,
        0.271,
        0.301,
    ]
)
_LU = np.array(
    [
        -31.6,
        -27.2,
        -23.0,
        -19.1,
        -15.9,
        -13.0,
        -10.3,
        -8.1,
        -6.2,
        -4.5,
        -3.1,
        -2.0,
        -1.1,
        -0.4,
        0.0,
        0.3,
        0.5,
        0.0,
        -2.7,
        -4.1,
        -1.0,
        1.7,
        2.5,
        1.2,
        -2.1,
        -7.1,
        -11.2,
        -10.7,
        -3.1,
    ]
)
_TF = np.array(
    [
        78.5,
        68.7,
        59.5,
        51.1,
        44.0,
        37.5,
        31.5,
        26.5,
        22.1,
        17.9,
        14.4,
        11.4,
        8.6,
        6.2,
        4.4,
        3.0,
        2.2,
        2.4,
        3.5,
        1.7,
        -1.3,
        -4.2,
        -6.0,
        -5.4,
        -1.5,
        6.0,
        12.6,
        13.9,
        12.3,
    ]
)


def iso226(phon: float, freqs: npt.ArrayLike | None = None) -> tuple[FloatArray, FloatArray]:
    """SPL (dB) needed at each frequency to sound as loud as `phon` dB at 1 kHz.
    ISO 226:2003 formula and table (valid 20 Hz-12.5 kHz, 20-90 phon;
    the 2023 revision moves values by about 1 dB at most in that range)."""
    af = 4.47e-3 * (10 ** (0.025 * phon) - 1.15) + (0.4 * 10 ** (((_TF + _LU) / 10) - 9)) ** _AF
    lp = (10 / _AF) * np.log10(af) - _LU + 94
    if freqs is None:
        return _F.copy(), lp
    return np.asarray(freqs), np.interp(np.log10(freqs), np.log10(_F), lp)


def perceived_balance(
    bands: Sequence[tuple[float, float]], listen_phon: float = 80.0, ref_phon: float | None = None
) -> list[tuple[Any, Any]]:
    """How much each band's loudness changes between two listening levels.

    Returns per-band dB: contour(ref) - contour(listen), shifted so 1 kHz = 0.
    Negative = the band sounds weaker at the quieter level than at ref."""
    ref_phon = ref_phon if ref_phon is not None else listen_phon
    fc = np.array([b[0] for b in bands if 20 <= b[0] <= 12500])
    _, c_listen = iso226(listen_phon, fc)
    _, c_ref = iso226(ref_phon, fc)
    # extra SPL a band needs at the quieter level, relative to 1 kHz
    need = (c_listen - listen_phon) - (c_ref - ref_phon)
    return [(r(f, 1), r(-n)) for f, n in zip(fc, need, strict=True)]
