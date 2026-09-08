"""Features of a single isolated sound (one hit / short stem).

See analysis/README.md for a plain-language description of every field.
"""
from __future__ import annotations

import numpy as np
import librosa
import scipy.signal as ss

EPS = 1e-12

# Shared band definitions (Hz), reused by context_features.py
BANDS = {
    "sub": (20, 60),
    "low": (60, 150),
    "lowmid": (150, 400),
    "mid": (400, 2000),
    "high": (2000, 6000),
    "air": (6000, 16000),
}


def _db(x):
    return 20.0 * np.log10(max(float(x), EPS))


def _a_weight_ba(sr):
    """Digital A-weighting filter (IEC 61672 analog prototype, bilinear-transformed).

    Standard Couvreur/`adweight.m` design, used here as a loudness *proxy*
    (not a certified LKFS/LUFS meter).
    """
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    a1000 = 1.9997
    nums = [(2 * np.pi * f4) ** 2 * (10 ** (a1000 / 20)), 0, 0, 0, 0]
    dens = np.polymul([1, 4 * np.pi * f4, (2 * np.pi * f4) ** 2],
                       [1, 4 * np.pi * f1, (2 * np.pi * f1) ** 2])
    dens = np.polymul(np.polymul(dens, [1, 2 * np.pi * f3]), [1, 2 * np.pi * f2])
    return ss.bilinear(nums, dens, sr)


def _stft_mag(y, sr, n_fft=2048):
    n = len(y)
    if n < n_fft:
        n_fft = max(64, 2 ** int(np.floor(np.log2(max(n, 2)))))
    hop = max(1, n_fft // 4)
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    return S, freqs, hop, n_fft


def _band_shares(S, freqs):
    power = S ** 2
    energies = {}
    for name, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        energies[name] = float(power[mask, :].sum()) if mask.any() else 0.0
    total = sum(energies.values()) + EPS
    return {f"band_{name}_share": e / total for name, e in energies.items()}


def describe_hit(y: np.ndarray, sr: int) -> dict:
    y = np.asarray(y, dtype=np.float64)
    n = len(y)
    if n == 0 or not np.any(y):
        raise ValueError("empty or silent audio")

    abs_y = np.abs(y)
    peak_amp = float(abs_y.max())
    peak_idx = int(abs_y.argmax())
    onset_thresh = max(peak_amp * 0.02, EPS)
    cand = np.flatnonzero(abs_y[: peak_idx + 1] >= onset_thresh)
    onset_idx = int(cand[0]) if cand.size else 0

    # --- duration to -60 dB, attack, decay ---------------------------------
    thr60 = peak_amp * 10 ** (-60 / 20)
    after = abs_y[peak_idx:]
    below = np.flatnonzero(after < thr60)
    end_idx = peak_idx + int(below[0]) if below.size else n - 1
    duration_s = (end_idx - onset_idx) / sr

    attack_ms = (peak_idx - onset_idx) / sr * 1000.0
    seg = abs_y[onset_idx: peak_idx + 1]
    i10 = np.flatnonzero(seg >= peak_amp * 0.1)
    i90 = np.flatnonzero(seg >= peak_amp * 0.9)
    if i10.size and i90.size and i90[0] >= i10[0]:
        rise_10_90_ms = (i90[0] - i10[0]) / sr * 1000.0
    else:
        rise_10_90_ms = float("nan")

    thr20 = peak_amp * 10 ** (-20 / 20)
    after_decay = abs_y[peak_idx:]
    idec = np.flatnonzero(after_decay <= thr20)
    decay_ms = (idec[0] / sr * 1000.0) if idec.size else (n - 1 - peak_idx) / sr * 1000.0

    # --- t60 estimate: linear fit of the dB envelope's decay slope ---------
    env = librosa.feature.rms(y=y, frame_length=256, hop_length=64)[0]
    env_db = 20 * np.log10(env + EPS)
    times = librosa.times_like(env, sr=sr, hop_length=64)
    pk_f = int(np.argmax(env))
    rel_db = env_db[pk_f:] - env_db[pk_f]
    t_rel = times[pk_f:] - times[pk_f]
    mask = (rel_db <= -5) & (rel_db >= -35)
    if mask.sum() < 3:
        mask = rel_db <= -1
    if mask.sum() >= 2:
        slope = np.polyfit(t_rel[mask], rel_db[mask], 1)[0]
        t60_estimate_ms = (-60.0 / slope) * 1000.0 if slope < -1e-6 else float("nan")
    else:
        t60_estimate_ms = float("nan")

    # --- level / loudness ----------------------------------------------------
    rms = float(np.sqrt(np.mean(y ** 2)))
    rms_db = _db(rms)
    peak_db = _db(peak_amp)
    crest_factor_db = peak_db - rms_db
    b, a = _a_weight_ba(sr)
    y_a = ss.lfilter(b, a, y)
    loudness_a_db = _db(np.sqrt(np.mean(y_a ** 2)))

    # --- spectral shape ------------------------------------------------------
    S, freqs, hop, n_fft = _stft_mag(y, sr)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr, freq=freqs)[0]
    spectral_centroid_hz = float(np.mean(centroid))

    seg_len = min(n, int(0.1 * sr))
    S100, freqs100, _, _ = _stft_mag(y[:seg_len] if seg_len > 0 else y, sr)
    centroid100 = librosa.feature.spectral_centroid(S=S100, sr=sr, freq=freqs100)[0]
    spectral_centroid_hz_100ms = float(np.mean(centroid100))

    spectral_bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(S=S, sr=sr, freq=freqs)))
    spectral_rolloff_85 = float(np.mean(librosa.feature.spectral_rolloff(S=S, sr=sr, freq=freqs, roll_percent=0.85)))
    spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(S=S)))
    zero_crossing_rate = float(np.mean(librosa.feature.zero_crossing_rate(y)))
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    spectral_flux_mean = float(np.mean(onset_env))

    band_shares = _band_shares(S, freqs)

    # --- pitch / harmonicity ---------------------------------------------
    try:
        f0, voiced_flag, voiced_prob = librosa.pyin(y, fmin=32.0, fmax=2000.0, sr=sr)
        f0_times = librosa.times_like(f0, sr=sr, hop_length=512)
        valid = f0[~np.isnan(f0)]
        f0_hz = float(np.nanmedian(f0)) if valid.size else float("nan")
        voiced_confidence = float(np.nanmean(voiced_prob)) if voiced_prob.size else 0.0
    except Exception:
        f0, f0_times = None, None
        f0_hz, voiced_confidence = float("nan"), 0.0

    def pitch_at(ms):
        if f0 is None or f0_times is None or len(f0_times) == 0:
            return float("nan")
        target = onset_idx / sr + ms / 1000.0
        idx = int(np.argmin(np.abs(f0_times - target)))
        val = f0[idx]
        return float(val) if not np.isnan(val) else float("nan")

    y_h, y_p = librosa.effects.hpss(y)
    h_energy = float(np.sum(y_h ** 2))
    p_energy = float(np.sum(y_p ** 2))
    harmonic_percussive_ratio = h_energy / (p_energy + EPS)

    times_c = librosa.times_like(centroid, sr=sr, hop_length=hop) * 1000.0
    if len(times_c) >= 2:
        centroid_slope_hz_per_ms = float(np.polyfit(times_c, centroid, 1)[0])
    else:
        centroid_slope_hz_per_ms = float("nan")

    out = {
        "duration_s": duration_s,
        "attack_ms": attack_ms,
        "rise_10_90_ms": rise_10_90_ms,
        "decay_ms": decay_ms,
        "t60_estimate_ms": t60_estimate_ms,
        "rms_db": rms_db,
        "peak_db": peak_db,
        "crest_factor_db": crest_factor_db,
        "loudness_a_db": loudness_a_db,  # A-weighted RMS proxy, not certified LUFS
        "spectral_centroid_hz": spectral_centroid_hz,
        "spectral_centroid_hz_100ms": spectral_centroid_hz_100ms,
        "spectral_bandwidth": spectral_bandwidth,
        "spectral_rolloff_85": spectral_rolloff_85,
        "spectral_flatness": spectral_flatness,
        "spectral_flux_mean": spectral_flux_mean,
        "zero_crossing_rate": zero_crossing_rate,
        "f0_hz": f0_hz,
        "f0_voiced_confidence": voiced_confidence,
        "f0_hz_at_5ms": pitch_at(5),
        "f0_hz_at_30ms": pitch_at(30),
        "f0_hz_at_100ms": pitch_at(100),
        "harmonic_percussive_ratio": harmonic_percussive_ratio,
        "centroid_slope_hz_per_ms": centroid_slope_hz_per_ms,
    }
    out.update(band_shares)
    return {k: float(v) for k, v in out.items()}


def describe_file(path: str) -> dict:
    y, sr = librosa.load(path, sr=None, mono=True)
    return describe_hit(y, sr)
