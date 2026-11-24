"""The kick-shape measures kickfuzz.py compares against: third-octave energy, and a reference's kick-alone bars.

Carried over unchanged from the industrial short's listen.py (hands/scripts/industrial, 15 Oct 2026), which
kickfuzz loaded by path until hands/scripts was archived (zpkt-archive, 24 Nov 2026).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

REFS = Path("~/_agent_scratch/refs/HW002").expanduser()
THIRDS = [25 * 2 ** (k / 3) for k in range(28)]  # 25 Hz .. ~16 kHz


def mono(path):
    x, sr = sf.read(path, always_2d=True)
    return x.mean(1), sr


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12)


def third_octaves(x, sr) -> np.ndarray:
    n = 1 << 15
    S = np.zeros(n // 2 + 1)
    for k in range(0, len(x) - n, n // 2):
        S += np.abs(np.fft.rfft(x[k : k + n] * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    e = np.array([S[(f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))].sum() for c in THIRDS])
    return 10 * np.log10(e / e.sum() + 1e-12)


def kick_alone(r, sr, bpm: float = 150.0, bars: int = 2) -> np.ndarray:
    """The reference's loudest-kick stretch where little else plays: windows of `bars` bars, scored by low-band
    level minus how much sits above 2 kHz (hats, synths)."""
    win = int(bars * 4 * 60 / bpm * sr)
    best, score = 0, -1e9
    for k in range(0, len(r) - win, win // 4):
        seg = r[k : k + win]
        S = np.abs(np.fft.rfft(seg[::4])) ** 2
        f = np.fft.rfftfreq(len(seg[::4]), 4 / sr)
        low, high, tot = S[(f > 40) & (f < 150)].sum(), S[f > 2000].sum(), S.sum() + 1e-20
        sc = 10 * np.log10(low / tot) - 10 * np.log10(high / tot) + 0.3 * rms_db(seg)
        if sc > score:
            best, score = k, sc
    return r[best : best + win], best / sr
