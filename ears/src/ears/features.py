"""Spectral and timbral feature extraction."""
from __future__ import annotations

import numpy as np

from .models import SpectralFeatures


def extract(audio: np.ndarray, sr: int) -> SpectralFeatures:
    """Extract spectral + timbral features from mono float32 audio."""
    import librosa

    feats = SpectralFeatures()

    cent = librosa.feature.spectral_centroid(y=audio, sr=sr)
    feats.spectral_centroid_mean = float(np.mean(cent))
    feats.spectral_centroid_std = float(np.std(cent))

    rolloff = librosa.feature.spectral_rolloff(y=audio, sr=sr)
    feats.spectral_rolloff_mean = float(np.mean(rolloff))

    bandwidth = librosa.feature.spectral_bandwidth(y=audio, sr=sr)
    feats.spectral_bandwidth_mean = float(np.mean(bandwidth))

    flatness = librosa.feature.spectral_flatness(y=audio)
    feats.spectral_flatness_mean = float(np.mean(flatness))

    zcr = librosa.feature.zero_crossing_rate(y=audio)
    feats.zero_crossing_rate_mean = float(np.mean(zcr))

    harmonic, _ = librosa.effects.hpss(audio)
    harmonic_power = float(np.mean(harmonic ** 2))
    total_power = float(np.mean(audio ** 2)) + 1e-10
    feats.harmonic_ratio_mean = harmonic_power / total_power

    onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
    feats.onset_strength_mean = float(np.mean(onset_env))
    feats.onset_strength_std = float(np.std(onset_env))

    mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)
    feats.mfcc_means = [float(v) for v in np.mean(mfcc, axis=1)]
    feats.mfcc_stds = [float(v) for v in np.std(mfcc, axis=1)]

    chroma = librosa.feature.chroma_stft(y=audio, sr=sr)
    feats.chroma_means = [float(v) for v in np.mean(chroma, axis=1)]

    # Key detection via essentia (optional)
    try:
        import essentia.standard as es
        key_extractor = es.KeyExtractor()
        key, scale, strength = key_extractor(audio.astype(np.float32))
        feats.key = f"{key} {scale}"
        feats.key_strength = float(strength)
        rhythm_extractor = es.RhythmDescriptors()
        desc = rhythm_extractor(audio.astype(np.float32))
        feats.danceability = float(desc[6])
    except Exception:
        pass

    return feats
