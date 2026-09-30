"""Loudness and spectral band energy extraction."""
from __future__ import annotations

from typing import Optional

import numpy as np

from .models import LoudnessFeatures

BANDS = {
    "sub":  (20,    150),
    "low":  (150,   600),
    "mid":  (600,   4000),
    "high": (4000,  12000),
    "air":  (12000, 20000),
}

_CAMELOT = {
    ("B", "major"): "1B", ("Gb", "major"): "2B", ("Db", "major"): "3B",
    ("Ab", "major"): "4B", ("Eb", "major"): "5B", ("Bb", "major"): "6B",
    ("F", "major"): "7B", ("C", "major"): "8B", ("G", "major"): "9B",
    ("D", "major"): "10B", ("A", "major"): "11B", ("E", "major"): "12B",
    ("Ab", "minor"): "1A", ("Eb", "minor"): "2A", ("Bb", "minor"): "3A",
    ("F", "minor"): "4A", ("C", "minor"): "5A", ("G", "minor"): "6A",
    ("D", "minor"): "7A", ("A", "minor"): "8A", ("E", "minor"): "9A",
    ("B", "minor"): "10A", ("Gb", "minor"): "11A", ("Db", "minor"): "12A",
}
_ENHARMONIC = {"F#": "Gb", "C#": "Db", "G#": "Ab", "D#": "Eb", "A#": "Bb"}


def _band_energy(audio: np.ndarray, sr: int, lo: float, hi: float) -> float:
    n = len(audio)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    mask = (freqs >= lo) & (freqs < hi)
    return float(np.sum(spectrum[mask]))


def _to_camelot(key: str, scale: str) -> str:
    k = _ENHARMONIC.get(key, key)
    return _CAMELOT.get((k, scale), f"{key} {scale}")


def true_peak_dbtp(channels: np.ndarray, sr: int) -> Optional[float]:
    """BS.1770 true peak in dBTP: 4x oversample each channel, take the max.

    ``channels`` is (samples,) or (samples, n_channels). None for silence.
    """
    from scipy.signal import resample_poly

    x = channels.reshape(len(channels), -1)
    factor = 4 if sr < 96000 else 2
    peak = max(float(np.max(np.abs(resample_poly(x[:, c], factor, 1)))) for c in range(x.shape[1]))
    peak = max(peak, float(np.max(np.abs(x))))
    return 20.0 * np.log10(peak) if peak > 0 else None


def _windowed_max_lufs(meter, channels: np.ndarray, sr: int, window_s: float) -> Optional[float]:
    size = int(sr * window_s)
    vals = []
    for start in range(0, len(channels) - size, size // 2):
        try:
            v = meter.integrated_loudness(channels[start: start + size])
            if np.isfinite(v):
                vals.append(v)
        except Exception:
            pass
    return float(max(vals)) if vals else None


def extract(audio: np.ndarray, sr: int, channels: Optional[np.ndarray] = None) -> LoudnessFeatures:
    """Extract loudness and 5-band spectral energy.

    ``audio`` is mono float32 (used for band energy and key). ``channels`` is
    the original (samples, n_channels) signal for LUFS and true peak; mono
    ``audio`` is used when it is omitted. Measuring a stereo file on a mono
    downmix misreads loudness whenever L and R differ.
    """
    feats = LoudnessFeatures()
    chans = audio if channels is None else channels

    try:
        feats.true_peak_db = true_peak_dbtp(chans, sr)
    except Exception:
        pass

    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        val = meter.integrated_loudness(chans)
        feats.lufs_integrated = float(val) if np.isfinite(val) else None
        feats.lufs_short_term_peak = _windowed_max_lufs(meter, chans, sr, 3.0)
        feats.lufs_momentary_max = _windowed_max_lufs(meter, chans, sr, 0.4)
    except Exception:
        pass

    total = sum(_band_energy(audio, sr, lo, hi) for lo, hi in BANDS.values()) + 1e-10
    feats.band_energy = {
        name: _band_energy(audio, sr, lo, hi) / total
        for name, (lo, hi) in BANDS.items()
    }

    try:
        import essentia.standard as es
        key, scale, _ = es.KeyExtractor()(audio.astype(np.float32))
        feats.camelot_key = _to_camelot(key, scale)
    except Exception:
        pass

    return feats
