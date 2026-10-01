"""Test and calibration signals.

Probe signals are meant to be dragged into Ableton, run through a device,
exported, and measured against the dry file with `eq-diff` or `comp-probe`.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .util import lin


def sine(freq, dbfs, dur, sr, ch=2, phase=0.0, fade_ms=0.0):
    """Sine with PEAK at dbfs (dBFS sample-peak convention)."""
    t = np.arange(int(round(dur * sr))) / sr
    s = lin(dbfs) * np.sin(2 * np.pi * freq * t + phase)
    if fade_ms:
        s *= _fade(len(s), sr, fade_ms)
    return np.repeat(s[:, None], ch, axis=1)


def _fade(n, sr, ms):
    k = np.arange(n)
    nf = max(1, int(sr * ms / 1000))
    return np.minimum(1.0, np.minimum(k, n - 1 - k) / nf)


def pink(dur, sr, ch=2, seed=0, rms_dbfs=None, band=None):
    """Pink noise by 1/f spectral shaping; optional band-limit and RMS level.
    rms_dbfs uses the plain (not sine-referenced) RMS."""
    rng = np.random.default_rng(seed)
    n = int(round(dur * sr))
    X = np.fft.rfft(rng.standard_normal((n, ch)), axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    shape = np.zeros_like(f)
    shape[1:] = 1 / np.sqrt(f[1:])
    if band:
        lo, hi = band
        shape[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(X * shape[:, None], n=n, axis=0)
    y /= np.sqrt(np.mean(y ** 2))
    return y * (lin(rms_dbfs) if rms_dbfs is not None else lin(-20))


def white(dur, sr, ch=2, seed=0, rms_dbfs=-20):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((int(dur * sr), ch)) * lin(rms_dbfs)


def bandlimited_click(sr, peak=0.9, offset_frac=0.37, cutoff=0.4, dur=1.0, ch=2):
    """One isolated band-limited pulse whose true peak (= `peak`) falls BETWEEN samples.
    Worst case for a true-peak meter; the answer is known exactly."""
    n = int(dur * sr)
    t = np.arange(n) - (n // 2 + offset_frac)
    h = np.sinc(2 * cutoff * t) * np.kaiser(n, 12)
    h = h / (2 * cutoff) * (2 * cutoff)       # sinc(0) = 1 at the fractional centre
    return np.repeat((peak * h)[:, None], ch, axis=1)


# --------------------------------------------------- compressor probe
COMP_PROBE_LAYOUT = {
    "freq_hz": 1000.0,
    "ramp": [0.5, 20.5],           # seconds: -60 -> 0 dBFS linear-in-dB ramp
    "steps": [                      # (start, end, direction) of each hold after a step
        [21.0, 23.0, "up"], [23.0, 25.0, "down"],
        [25.0, 27.0, "up"], [27.0, 29.0, "down"],
        [29.0, 31.0, "up"], [31.0, 33.0, "down"]],
    "step_levels_dbfs": [-40.0, -10.0],
    "total_s": 33.5,
}


def comp_probe(sr=44100, ch=2):
    """1 kHz tone: silence, a 20 s level ramp (-60..0 dBFS), then three 30 dB up/down steps.
    Render it through a compressor with makeup OFF (or note the makeup), export, then
    `mlab comp-probe probe.wav render.wav`."""
    lay = COMP_PROBE_LAYOUT
    n = int(lay["total_s"] * sr)
    t = np.arange(n) / sr
    level = np.full(n, -120.0)
    a, b = lay["ramp"]
    m = (t >= a) & (t < b)
    level[m] = -60 + 60 * (t[m] - a) / (b - a)
    lo, hi = lay["step_levels_dbfs"]
    level[(t >= b) & (t < lay["steps"][0][0])] = lo
    for s0, s1, kind in lay["steps"]:
        level[(t >= s0) & (t < s1)] = hi if kind == "up" else lo
    level[t >= lay["steps"][-1][1]] = -120.0
    s = lin(level) * np.sin(2 * np.pi * lay["freq_hz"] * t)
    return np.repeat(s[:, None], ch, axis=1), lay


def eq_probe(sr=44100, dur=20.0, ch=2, seed=1):
    """Pink noise at -20 dBFS RMS: run it through an EQ, export, then `mlab eq-diff`."""
    return pink(dur, sr, ch, seed=seed, rms_dbfs=-20)


def kcal_files(sr=44100, dur=60.0):
    """K-System calibration: pink noise at -20/-14/-12 dBFS RMS (sine-referenced, AES-17),
    full band and 500 Hz-2 kHz band, left-only and right-only.
    Play each; set monitor gain so one speaker reads 83 dB SPL C-weighted slow at K-20."""
    out = {}
    for k in (20, 14, 12):
        for band, name in ((None, "fullband"), ((500, 2000), "500-2k")):
            # AES-17 RMS reads +3.01 dB vs plain RMS for noise; so plain RMS = -K - 3.01
            y = pink(dur, sr, 1, seed=k, rms_dbfs=-k - 3.0103, band=band)
            z = np.zeros_like(y)
            out[f"K-{k}_{name}_L.wav"] = np.hstack([y, z])
            out[f"K-{k}_{name}_R.wav"] = np.hstack([z, y])
    return out


def kick_loop(sr=44100, bpm=160, bars=4, ch=2, seed=0):
    """Four-on-the-floor synthetic kick with a sharp click and a 200 ms body, plus a
    quiet sustained rumble. Known structure for calibrating punch measures."""
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    n = int(bars * 4 * beat * sr)
    y = np.zeros(n)
    k = int(0.3 * sr)
    t = np.arange(k) / sr
    f = 50 + 150 * np.exp(-t / 0.02)
    body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / 0.12)
    click = rng.standard_normal(k) * np.exp(-t / 0.002) * 0.8
    kick = 0.5 * body + click * 0.5
    for i in range(bars * 4):
        a = int(i * beat * sr)
        y[a:a + k] += kick[: n - a]
    y += 0.03 * np.sin(2 * np.pi * 45 * np.arange(n) / sr)
    y *= 0.5 / np.max(np.abs(y))
    return np.repeat(y[:, None], ch, axis=1)


def song_sections(sr=44100, bpm=160.0, ch=2, seed=0, dropout_bar=None):
    """A techno-shaped song with a known layout, for calibrating sections.py.

    intro 8 bars (kick + hats) | break bars 9-16 (no kick, quiet pad) |
    drop 8 bars (kick + hats) | peak (kick + hats 6.02 dB louder, as many bars
    as sections.peak_window spans) | outro 8 bars (kick + hats).
    The kick is a clickless 50-200 Hz sweep, so the 2-16 kHz band is all hats.
    `dropout_bar` (1-based) silences the kick for one bar.
    Returns (x, truth) with 1-based inclusive bar ranges."""
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = 4 * beat
    wb = max(1, int(round(30.0 / bar)))
    layout = [("intro", 8, True, 1.0), ("break", 8, False, 0.0), ("drop", 8, True, 1.0),
              ("peak", wb, True, 2.0), ("outro", 8, True, 1.0)]
    nbars = sum(n for _, n, _, _ in layout)
    n = int(nbars * bar * sr) + sr
    y = np.zeros(n)
    k = int(0.25 * sr)
    t = np.arange(k) / sr
    kick = np.sin(2 * np.pi * np.cumsum(50 + 150 * np.exp(-t / 0.03)) / sr) * np.exp(-t / 0.1)
    h = int(0.04 * sr)
    sos = signal.butter(4, 6000, "high", fs=sr, output="sos")
    hat = signal.sosfilt(sos, rng.standard_normal(h)) * np.exp(-np.arange(h) / sr / 0.01)
    b0 = 0
    truth = {}
    for name, nb, has_kick, hat_amp in layout:
        truth[name] = [b0 + 1, b0 + nb]
        for b in range(b0, b0 + nb):
            for q in range(4):
                a = int((b * bar + q * beat) * sr)
                if has_kick and b + 1 != dropout_bar:
                    y[a:a + k] += 0.6 * kick
                if hat_amp:
                    o = int((b * bar + (q + 0.5) * beat) * sr)
                    y[o:o + h] += 0.05 * hat_amp * hat
        b0 += nb
    a, e = int((truth["break"][0] - 1) * bar * sr), int(truth["break"][1] * bar * sr)
    pad = signal.sosfilt(signal.butter(2, [300, 3000], "bandpass", fs=sr, output="sos"), rng.standard_normal(e - a))
    y[a:e] += 0.01 * pad
    y *= 0.5 / np.max(np.abs(y))
    return np.repeat(y[:, None], ch, axis=1), truth
