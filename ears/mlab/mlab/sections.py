"""Song structure on the bar grid: tempo, kickless runs (breaks), peak window.

Whole tracks compare badly: intros, breaks and outros dilute every average.
These instruments find each track's peak (the densest stretch while the kick
plays) so a mix can be compared with references section to section.

- tempo: onset autocorrelation scored at 1-32 beats, 0.01 BPM steps.
- bars: per-bar low (< 100 Hz) and high (2-16 kHz) energy in dB.
- kickless runs: bars whose low band is >= 8 dB under the track median.
- peak window: ~30 s on the bar grid, kick in >= 90 % of bars, most high-band energy.

Known answers live in calibration/checks.py (check_sections).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from . import loudness as L
from . import spectrum as S

LOW_HZ = 100.0
HIGH_HZ = (2000.0, 16000.0)
KICK_DROP_DB = 8.0
PEAK_S = 30.0
PEAK_KICK_FRACTION = 0.9


def onset_envelope(x, sr, hop=256, n_fft=1024):
    """Half-wave rectified spectral flux of the log-magnitude STFT (mono)."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    _, _, z = signal.stft(m, sr, nperseg=n_fft, noverlap=n_fft - hop, boundary=None, padded=False)
    mag = np.log1p(1000 * np.abs(z))
    flux = np.maximum(np.diff(mag, axis=1), 0).sum(axis=0)
    return flux - flux.mean(), sr / hop


def tempo(x, sr, lo=120.0, hi=190.0, step=0.01):
    env, fps = onset_envelope(x, sr)
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    lag = np.arange(len(ac))
    cands = np.arange(lo, hi, step)
    score = sum(np.interp(k * 60 * fps / cands, lag, ac) for k in (1, 2, 4, 8, 16, 32))
    return float(cands[int(np.argmax(score))])


def bars(x, sr, bpm):
    """Per-bar (low_db, high_db) arrays on a grid starting at sample 0."""
    bar = 4 * 60 / bpm
    nb = int(len(x) / sr / bar)
    lo = signal.sosfilt(signal.butter(4, LOW_HZ, "low", fs=sr, output="sos"), x.mean(axis=1))
    hi = signal.sosfilt(signal.butter(4, HIGH_HZ, "bandpass", fs=sr, output="sos"), x.mean(axis=1))
    low_db, high_db = np.empty(nb), np.empty(nb)
    for b in range(nb):
        a, e = int(b * bar * sr), int((b + 1) * bar * sr)
        low_db[b] = 10 * np.log10(np.mean(lo[a:e] ** 2) + 1e-12)
        high_db[b] = 10 * np.log10(np.mean(hi[a:e] ** 2) + 1e-12)
    return low_db, high_db


def kick_mask(low_db):
    return low_db > np.median(low_db) - KICK_DROP_DB


def kickless_runs(kick, min_bars=2):
    """1-based inclusive [first, last] bar ranges without kick."""
    runs, start = [], None
    for b, k in enumerate(list(kick) + [True]):
        if not k and start is None:
            start = b
        if k and start is not None:
            if b - start >= min_bars:
                runs.append([start + 1, b])
            start = None
    return runs


def peak_window(high_db, kick, bpm, seconds=PEAK_S):
    """1-based inclusive bar range of the densest kick section, or None."""
    wb = max(1, int(round(seconds / (4 * 60 / bpm))))
    best, at = -np.inf, None
    for b in range(0, len(high_db) - wb + 1):
        if kick[b:b + wb].mean() < PEAK_KICK_FRACTION:
            continue
        v = high_db[b:b + wb].mean()
        if v > best:
            best, at = v, b
    return None if at is None else [at + 1, at + wb]


def excerpt(x, sr, bpm, bar_range):
    bar = 4 * 60 / bpm
    return x[int((bar_range[0] - 1) * bar * sr): int(bar_range[1] * bar * sr)]


def analyze(x, sr, bpm=None):
    bpm = bpm or tempo(x, sr)
    low_db, high_db = bars(x, sr, bpm)
    kick = kick_mask(low_db)
    runs = kickless_runs(kick)
    pk = peak_window(high_db, kick, bpm)
    inner = [r for r in runs if r[0] > 1 and r[1] < len(kick)]
    main = max(inner, key=lambda r: r[1] - r[0]) if inner else None
    drop = None
    if main and pk:
        drop = float(high_db[main[1]:main[1] + 8].mean() - high_db[pk[0] - 1:pk[1]].mean())
    return {"bpm": round(bpm, 2), "bars": len(kick), "kickless_runs": runs, "main_break": main,
            "peak_bars": pk, "drop_vs_peak_high_db": None if drop is None else round(drop, 2),
            "peak_after_main_break": bool(main and pk and pk[0] > main[1])}


def peak_profile(x, sr, bpm, bar_range):
    """Measures of a peak excerpt that do not depend on its level."""
    seg = excerpt(x, sr, bpm, bar_range)
    from . import dynamics as D
    st = S.stereo_by_band(seg, sr)
    return {"lufs": round(L.integrated(seg, sr), 2), "third_octave_rel": _rel_third_octave(seg, sr),
            "low_corr": st[0]["correlation"] if st else None,
            "low_side_minus_mid_db": st[0]["side_minus_mid_db"] if st else None,
            "crest_median_db": D.micro(seg, sr)["block_crest_median_db"]}


def _rel_third_octave(x, sr):
    bands = S.third_octave(x, sr)
    lv = np.array([v for _, v in bands])
    lv -= 10 * np.log10(np.sum(10 ** (lv / 10)))
    return [(round(c, 1), round(float(v), 2)) for (c, _), v in zip(bands, lv)]
