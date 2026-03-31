"""Loudness and spectral band energy extraction."""
from __future__ import annotations

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


def extract(audio: np.ndarray, sr: int) -> LoudnessFeatures:
    """Extract LUFS loudness and 5-band spectral energy from mono float32 audio."""
    feats = LoudnessFeatures()

    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        stereo = np.stack([audio, audio], axis=-1) if audio.ndim == 1 else audio
        val = meter.integrated_loudness(stereo)
        feats.lufs_integrated = float(val) if np.isfinite(val) else None
        feats.true_peak_db = float(np.max(np.abs(audio)))

        block_size = int(sr * 3.0)
        st_vals = []
        for start in range(0, len(audio) - block_size, block_size // 2):
            b = audio[start: start + block_size]
            try:
                v = meter.integrated_loudness(np.stack([b, b], axis=-1))
                if np.isfinite(v):
                    st_vals.append(v)
            except Exception:
                pass
        if st_vals:
            feats.lufs_short_term_peak = float(max(st_vals))

        mom_size = int(sr * 0.4)
        mom_vals = []
        for start in range(0, len(audio) - mom_size, mom_size // 2):
            b = audio[start: start + mom_size]
            try:
                v = meter.integrated_loudness(np.stack([b, b], axis=-1))
                if np.isfinite(v):
                    mom_vals.append(v)
            except Exception:
                pass
        if mom_vals:
            feats.lufs_momentary_max = float(max(mom_vals))
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
