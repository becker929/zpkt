"""Measuring a rendered file: its length, peak, loudness and spectrum, as one plain record.

The app hands this the path of a WAV that Live exported. The spectrum is on the meter's own 31 third-octave bands
(zpkt.audio.levels), so a render and what Live plays now are drawn on the same bars. Reading the file is the only
effect; everything else is arithmetic on the samples. `gap` says how far one measure is from another.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import numpy as np
import soundfile as sf

from zpkt.audio.levels import FLOOR, RATIO, SILENCE_DB, band_centers, rms_to_db

FRAME = 8192  # samples in one spectrum frame
NOT_A_NUMBER = float("nan")


class Measure(TypedDict):
    """What a render measures as. `lufs` is None when the loudness meter (the `audio` extra) is not installed."""

    seconds: float
    rate: int
    peak_db: float  # sample peak, dB below full scale
    rms_db: float
    lufs: float | None
    bands_db: list[float]  # RMS level in each third-octave band, dB (the meter's bands)


class Gap(TypedDict):
    """`a` minus `b`, by measure. A part that either side lacks is None."""

    lufs: float | None
    peak_db: float
    rms_db: float
    bands_db: list[float]


def _db(x: float) -> float:
    return round(20 * math.log10(x), 2) if x > FLOOR else SILENCE_DB


def band_levels(samples: np.ndarray, rate: int) -> list[float]:
    """RMS level of each third-octave band, in dB, averaged over the channels and over the file.
    `samples` is (frames, channels). A full-scale sine in a band reads about -3 dB there."""
    window = np.hanning(FRAME)
    norm = 2.0 / (FRAME * float(np.sum(window**2)))  # makes the sum of bins the mean square of the signal
    freqs = np.fft.rfftfreq(FRAME, 1.0 / rate)
    power = np.zeros(len(freqs))
    frames = 0
    hop = FRAME // 2
    for ch in range(samples.shape[1]):
        x = samples[:, ch].astype(np.float64)
        if len(x) < FRAME:
            x = np.pad(x, (0, FRAME - len(x)))
        for start in range(0, len(x) - FRAME + 1, hop):
            spec = np.fft.rfft(x[start : start + FRAME] * window)
            power += norm * (np.abs(spec) ** 2)
            frames += 1
    power /= max(frames, 1)
    half = RATIO**0.5
    levels = []
    for fc in band_centers():
        inside = (freqs >= fc / half) & (freqs < fc * half)
        levels.append(math.sqrt(float(power[inside].sum())) if inside.any() else 0.0)
    return rms_to_db(levels)


def _lufs(samples: np.ndarray, rate: int) -> float | None:
    try:
        import pyloudnorm as pl
    except ImportError:
        return None
    if samples.shape[0] < int(0.4 * rate):  # shorter than one gating block
        return None
    value = float(pl.Meter(rate).integrated_loudness(samples))
    return round(value, 2) if math.isfinite(value) else None


def measure_samples(samples: np.ndarray, rate: int) -> Measure:
    """Measure `samples`, shaped (frames, channels), recorded at `rate`."""
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0
    return {
        "seconds": round(samples.shape[0] / rate, 3),
        "rate": rate,
        "peak_db": _db(peak),
        "rms_db": _db(rms),
        "lufs": _lufs(samples, rate),
        "bands_db": band_levels(samples, rate),
    }


def measure_wav(path: Path) -> Measure:
    """Measure the audio file at `path` (WAV, FLAC and the like). A file that cannot be read raises ValueError."""
    try:
        samples, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (RuntimeError, OSError) as exc:
        raise ValueError(f"{path.name} could not be read as audio ({exc}). Render it again.") from None
    return measure_samples(samples, int(rate))


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 2)


def gap(a: Measure, b: Measure) -> Gap:
    """How far `a` is from `b`: positive means `a` is louder (in that measure)."""
    bands: Sequence[float] = [round(x - y, 2) for x, y in zip(a["bands_db"], b["bands_db"], strict=True)]
    return {
        "lufs": _sub(a["lufs"], b["lufs"]),
        "peak_db": round(a["peak_db"] - b["peak_db"], 2),
        "rms_db": round(a["rms_db"] - b["rms_db"], 2),
        "bands_db": list(bands),
    }
