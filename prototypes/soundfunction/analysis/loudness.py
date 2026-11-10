"""Integrated loudness (ITU BS.1770, via pyloudnorm), true-ish peak and crest of a file or of a
sum of stems.   from analysis.loudness import measure; measure(y, sr) -> dict"""
import numpy as np, pyloudnorm as pyln

def measure(y, sr):
    y = np.asarray(y, dtype=float)
    if y.ndim > 1: y = y.mean(axis=1)
    if not np.any(y): return dict(lufs=None, peak_dbfs=None, crest_db=None)
    meter = pyln.Meter(sr)                     # K-weighting designed for the given rate
    # a mono fold stands for both channels of the master: measure it as identical L and R,
    # otherwise BS.1770 reports the one-channel figure, 3 dB under what the stereo file reads
    lufs = float(meter.integrated_loudness(np.stack([y, y], axis=1)))
    peak = float(np.abs(y).max()); rms = float(np.sqrt(np.mean(y ** 2)))
    return dict(lufs=round(lufs, 2), peak_dbfs=round(20 * np.log10(peak + 1e-12), 2), crest_db=round(20 * np.log10(peak / (rms + 1e-12)), 2))
