"""Synthetic audio fixtures used for development and tests (no real corpus needed)."""
from __future__ import annotations

import numpy as np


def sine_burst(freq=50.0, sr=44100, dur=0.3, decay=25.0):
    t = np.arange(int(dur * sr)) / sr
    env = np.exp(-decay * t)
    return (np.sin(2 * np.pi * freq * t) * env).astype(np.float64), sr


def noise_burst(sr=44100, dur=0.2, decay=20.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(dur * sr)) / sr
    env = np.exp(-decay * t)
    n = rng.standard_normal(len(t))
    return (n * env).astype(np.float64), sr


def clicked_sine_sweep(sr=44100, f_start=800.0, f_end=90.0, dur=0.35, decay=12.0):
    """A kick-like transient: broadband click + a descending pitched sweep."""
    t = np.arange(int(dur * sr)) / sr
    k = np.log(f_end / f_start) / dur
    freq_t = f_start * np.exp(k * t)
    phase = 2 * np.pi * f_start * (np.exp(k * t) - 1) / k
    tone = np.sin(phase) * np.exp(-decay * t)
    click_len = int(0.002 * sr)
    click = np.zeros_like(t)
    click[:click_len] = np.random.default_rng(1).standard_normal(click_len) * np.hanning(click_len)
    y = tone + 0.5 * click
    return y.astype(np.float64), sr


def click_track(bpm=150.0, sr=22050, n_bars=16, thump_freq=60.0):
    """16-bar 4/4 click track.

    - a low "thump" (sub/low band) on every quarter-note beat, EXCEPT bars 9-12
      (the synthetic breakdown)
    - a noise "tick" (high/air band) on the offbeat 8th notes (16-step bins
      2, 6, 10, 14), on every bar
    """
    beat_s = 60.0 / bpm
    step_s = beat_s / 4.0
    total_s = n_bars * 4 * beat_s + 0.5
    n = int(total_s * sr)
    y = np.zeros(n)

    def add(y, start_idx, burst):
        end = min(len(y), start_idx + len(burst))
        y[start_idx:end] += burst[: end - start_idx]

    rng = np.random.default_rng(2)
    # kick-like thump: sub tone with a sharp (cosine-phase) attack, so it reads
    # as a clean onset in the sub/low bands (a sine-phase start ramps too slowly).
    thump_t = np.arange(int(0.05 * sr)) / sr
    thump = np.cos(2 * np.pi * thump_freq * thump_t) * np.exp(-thump_t * 35)
    ramp_len = max(1, int(0.001 * sr))  # 1 ms fade-in: sharp, but not a true
    thump[:ramp_len] *= np.linspace(0, 1, ramp_len)  # sample-domain discontinuity

    tick_t = np.arange(int(0.03 * sr)) / sr
    tick = rng.standard_normal(len(tick_t)) * np.exp(-tick_t * 60) * 0.6

    breakdown_bars = set(range(8, 12))  # bars 9-12 (0-indexed 8..11)
    for bar in range(n_bars):
        for beat in range(4):
            idx = int(round((bar * 4 + beat) * beat_s * sr))
            if bar not in breakdown_bars:
                add(y, idx, thump)
        for step in (2, 6, 10, 14):
            beat_in = step // 4
            sub = step % 4
            t_step = (bar * 4 + beat_in) * beat_s + sub * step_s
            idx = int(round(t_step * sr))
            add(y, idx, tick)

    return y.astype(np.float64), sr, bpm, n_bars
