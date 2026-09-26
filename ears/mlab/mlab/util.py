"""Small shared helpers: dB conversions and level-safe math."""
from __future__ import annotations

import numpy as np

EPS = 1e-20


def db(x) -> np.ndarray | float:
    """Amplitude ratio -> dB. Silence maps to a large negative number, never -inf."""
    return 20.0 * np.log10(np.maximum(np.abs(x), EPS))


def pdb(p) -> np.ndarray | float:
    """Power ratio -> dB."""
    return 10.0 * np.log10(np.maximum(p, EPS))


def lin(d) -> np.ndarray | float:
    return 10.0 ** (np.asarray(d, dtype=float) / 20.0)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def r(v, nd=2):
    """Round for reports; keep None and non-finite values readable."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if not np.isfinite(f):
        return None if np.isnan(f) else (-999.0 if f < 0 else 999.0)
    return round(f, nd)


def mono(x: np.ndarray) -> np.ndarray:
    """Mid signal (L+R)/2 for stereo; passthrough for mono."""
    return x.mean(axis=1) if x.ndim == 2 else x


def dc_offset_db(x, sr, block_s=1.0):
    """Per-channel DC estimate (dBFS) = overall mean. See dc_is_real() before acting on it."""
    return [float(db(np.mean(x[:, c]))) for c in range(x.shape[1])]


def dc_is_real(x, sr, block_s=1.0, z=4.0):
    """True if some channel's mean is a steady offset, not low-frequency music.
    A true offset shows in every 1 s block; bass wander changes sign, so its
    block means scatter widely around a small overall mean."""
    b = max(1, int(block_s * sr))
    k = len(x) // b
    if k < 3:
        return True
    m = x[:k * b].reshape(k, b, x.shape[1]).mean(axis=1)
    se = m.std(axis=0, ddof=1) / np.sqrt(k) + 1e-12
    return bool(np.any(np.abs(m.mean(axis=0)) / se > z))
