"""Level-free features of a peak excerpt, for hill-climbing HW002 mix alternates.

mlab's calibrated meters (tonal balance, stereo by band, block crest, transient
contrast) plus the librosa features that ears/src/ears/features.py extracts
(centroid, rolloff, flatness, harmonic ratio, onset strength), computed the same way.
Everything is measured at -14 LUFS, so loudness cancels out.
"""
import numpy as np

from mlab import dynamics as D
from mlab import loudness as L
from mlab import sections as SEC
from mlab import spectrum as S


def normalize(x, sr, target=-14.0):
    return x * 10 ** ((target - L.integrated(x, sr)) / 20)


def ears_features(x, sr):
    """The level-free subset of ears.features.extract (same librosa calls), on mono."""
    import librosa

    y = x.mean(axis=1).astype(np.float32)
    harmonic, _ = librosa.effects.hpss(y)
    return {
        "centroid_hz": float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))),
        "rolloff_hz": float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))),
        "flatness": float(np.mean(librosa.feature.spectral_flatness(y=y))),
        "harmonic_ratio": float(np.mean(harmonic ** 2) / (np.mean(y ** 2) + 1e-10)),
        "onset_strength": float(np.mean(librosa.onset.onset_strength(y=y, sr=sr))),
    }


def measure(x, sr, with_ears=True):
    x = normalize(np.asarray(x, dtype="float64"), sr)
    st = S.stereo_by_band(x, sr)
    f = {
        "third_octave_rel": {str(c): v for c, v in SEC._rel_third_octave(x, sr)},
        "corr": {f"{d['band_hz'][0]}-{d['band_hz'][1]}": d["correlation"] for d in st},
        "side_mid": {f"{d['band_hz'][0]}-{d['band_hz'][1]}": d["side_minus_mid_db"] for d in st},
        "block_crest_median_db": D.micro(x, sr)["block_crest_median_db"],
        "transient_contrast_db": D.transient_contrast(x, sr).get("transient_contrast_median_db"),
    }
    if with_ears:
        f["ears"] = ears_features(x, sr)
    return f


def flat(f):
    """{'third_octave_rel.1000.0': -12.3, 'corr.20-120': 0.99, ...}"""
    out = {}
    for k, v in f.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out
