"""Spectral and timbral feature extraction via librosa and essentia."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class SpectralFeatures:
    spectral_centroid_mean: float = 0.0
    spectral_centroid_std: float = 0.0
    spectral_rolloff_mean: float = 0.0
    spectral_bandwidth_mean: float = 0.0
    spectral_flatness_mean: float = 0.0
    zero_crossing_rate_mean: float = 0.0
    harmonic_ratio_mean: float = 0.0
    onset_strength_mean: float = 0.0
    onset_strength_std: float = 0.0
    mfcc_means: list[float] = field(default_factory=list)       # 13 coefficients
    mfcc_stds: list[float] = field(default_factory=list)
    chroma_means: list[float] = field(default_factory=list)     # 12 pitch classes
    key: Optional[str] = None                                   # e.g. "A minor"
    key_strength: float = 0.0
    danceability: Optional[float] = None


def extract(audio: np.ndarray, sr: int) -> SpectralFeatures:
    """Extract spectral + timbral features. Audio should be mono float32."""
    import librosa

    feats = SpectralFeatures()

    # Spectral shape
    cent = librosa.feature.spectral_centroid(y=audio, sr=sr)
    feats.spectral_centroid_mean = float(np.mean(cent))
    feats.spectral_centroid_std = float(np.std(cent))

    rolloff = librosa.feature.spectral_rolloff(y=audio, sr=sr)
    feats.spectral_rolloff_mean = float(np.mean(rolloff))

    bandwidth = librosa.feature.spectral_bandwidth(y=audio, sr=sr)
    feats.spectral_bandwidth_mean = float(np.mean(bandwidth))

    flatness = librosa.feature.spectral_flatness(y=audio)
    feats.spectral_flatness_mean = float(np.mean(flatness))

    # Zero-crossing rate (noise / brightness indicator)
    zcr = librosa.feature.zero_crossing_rate(y=audio)
    feats.zero_crossing_rate_mean = float(np.mean(zcr))

    # Harmonic-to-noise ratio proxy via harmonic separation
    harmonic, percussive = librosa.effects.hpss(audio)
    harmonic_power = float(np.mean(harmonic ** 2))
    total_power = float(np.mean(audio ** 2)) + 1e-10
    feats.harmonic_ratio_mean = harmonic_power / total_power

    # Onset strength
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
    feats.onset_strength_mean = float(np.mean(onset_env))
    feats.onset_strength_std = float(np.std(onset_env))

    # MFCCs (13 coefficients)
    mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)
    feats.mfcc_means = [float(v) for v in np.mean(mfcc, axis=1)]
    feats.mfcc_stds = [float(v) for v in np.std(mfcc, axis=1)]

    # Chromagram
    chroma = librosa.feature.chroma_stft(y=audio, sr=sr)
    feats.chroma_means = [float(v) for v in np.mean(chroma, axis=1)]

    # Key detection + danceability via essentia (optional - degrade gracefully)
    try:
        import essentia.standard as es
        key_extractor = es.KeyExtractor()
        # Essentia expects float32
        key, scale, strength = key_extractor(audio.astype(np.float32))
        feats.key = f"{key} {scale}"
        feats.key_strength = float(strength)

        rhythm_extractor = es.RhythmDescriptors()
        desc = rhythm_extractor(audio.astype(np.float32))
        # RhythmDescriptors returns (bpm, beats, bpm_estimates, bpm_intervals,
        #   beat_loudness, beat_loudness_band_ratio, danceability, dfa_exponent)
        feats.danceability = float(desc[6])
    except Exception:
        pass

    return feats
