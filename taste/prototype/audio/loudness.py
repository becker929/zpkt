"""Loudness and spectral energy distribution extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


BANDS = {
    "sub": (20, 150),
    "low": (150, 600),
    "mid": (600, 4000),
    "high": (4000, 12000),
    "air": (12000, 20000),
}


@dataclass
class LoudnessFeatures:
    lufs_integrated: Optional[float] = None
    lufs_short_term_peak: Optional[float] = None
    lufs_momentary_max: Optional[float] = None
    true_peak_db: Optional[float] = None
    # 5-band energy distribution (normalized to sum to 1)
    band_energy: dict[str, float] = field(default_factory=dict)
    # Key detection with Camelot notation
    camelot_key: Optional[str] = None
    key_bpm: Optional[float] = None


def _band_energy(audio: np.ndarray, sr: int, low_hz: float, high_hz: float) -> float:
    """RMS energy in a frequency band via FFT."""
    n = len(audio)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    mask = (freqs >= low_hz) & (freqs < high_hz)
    return float(np.sum(spectrum[mask]))


def extract(audio: np.ndarray, sr: int) -> LoudnessFeatures:
    """Extract loudness (LUFS) and spectral band distribution. Audio mono float32."""
    feats = LoudnessFeatures()

    # LUFS via pyloudnorm
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        # pyloudnorm expects (samples,) or (samples, channels)
        stereo = np.stack([audio, audio], axis=-1) if audio.ndim == 1 else audio
        feats.lufs_integrated = float(meter.integrated_loudness(stereo))
        feats.true_peak_db = float(pyln.normalize.peak(audio, 0.0).max())

        # Short-term loudness (3s blocks)
        block_size = int(sr * 3.0)
        short_term_vals = []
        for start in range(0, len(audio) - block_size, block_size // 2):
            block = audio[start : start + block_size]
            block_stereo = np.stack([block, block], axis=-1)
            try:
                val = meter.integrated_loudness(block_stereo)
                if np.isfinite(val):
                    short_term_vals.append(val)
            except Exception:
                pass
        if short_term_vals:
            feats.lufs_short_term_peak = float(max(short_term_vals))

        # Momentary loudness (400ms blocks)
        mom_size = int(sr * 0.4)
        mom_vals = []
        for start in range(0, len(audio) - mom_size, mom_size // 2):
            block = audio[start : start + mom_size]
            block_stereo = np.stack([block, block], axis=-1)
            try:
                val = meter.integrated_loudness(block_stereo)
                if np.isfinite(val):
                    mom_vals.append(val)
            except Exception:
                pass
        if mom_vals:
            feats.lufs_momentary_max = float(max(mom_vals))
    except Exception:
        pass

    # 5-band spectral energy
    total_energy = sum(
        _band_energy(audio, sr, lo, hi) for lo, hi in BANDS.values()
    ) + 1e-10
    feats.band_energy = {
        name: _band_energy(audio, sr, lo, hi) / total_energy
        for name, (lo, hi) in BANDS.items()
    }

    # Key detection via essentia (Camelot)
    try:
        import essentia.standard as es
        key_extractor = es.KeyExtractor()
        key, scale, _ = key_extractor(audio.astype(np.float32))
        feats.camelot_key = _to_camelot(key, scale)
    except Exception:
        pass

    return feats


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


def _to_camelot(key: str, scale: str) -> str:
    k = _ENHARMONIC.get(key, key)
    return _CAMELOT.get((k, scale), f"{key} {scale}")
