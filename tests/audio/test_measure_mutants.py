"""Numbers that a mutation run showed nothing pinned: the spectrum's scale, the dB rounding, the loudness windows
and the spectrum helpers' edge cases."""

from __future__ import annotations

import math

import numpy as np
import pytest

from zpkt.audio import measure
from zpkt.audio.meters import loudness, spectrum

RATE = 44100


def sine(hz: float, amp: float, seconds: float = 2.0, rate: int = RATE) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    x = (amp * np.sin(2 * math.pi * hz * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def test_the_band_level_of_a_sine_is_its_rms_to_a_tenth_of_a_db():
    m = measure.measure_samples(sine(1000, 0.5), RATE)
    assert max(m["bands_db"]) == pytest.approx(-9.03, abs=0.1)  # a wrong window norm is off by 0.8 dB


def test_levels_are_rounded_to_hundredths_of_a_db():
    m = measure.measure_samples(sine(1000, 0.3), RATE)
    assert m["peak_db"] == -10.46  # -10.4576, not -10 and not unrounded


def test_a_mono_sine_through_momentary_and_short_term_reads_its_level():
    n = 48000
    x = (0.5 * np.sin(2 * math.pi * 1000 * np.arange(n * 5) / n))[:, None]
    mom, st = loudness.momentary(x, n), loudness.short_term(x, n)
    assert len(mom) == 47 and len(st) == 21  # 0.4 s and 3 s windows, a hop of 0.1 s
    assert float(mom[0]) == pytest.approx(-9.02, abs=0.05)
    assert float(st[0]) == pytest.approx(-9.02, abs=0.05)


def test_the_hop_sets_how_often_loudness_is_read():
    n = 48000
    x = (0.5 * np.sin(2 * math.pi * 1000 * np.arange(n * 5) / n))[:, None]
    assert len(loudness.momentary(x, n, hop_s=0.5)) == 10
    assert len(loudness.short_term(x, n, hop_s=0.5)) == 5


def test_audio_shorter_than_the_window_has_no_loudness_blocks():
    x = np.zeros((4000, 1))
    assert len(loudness.momentary(x, 48000)) == 0 and len(loudness.short_term(x, 48000)) == 0


def test_a_band_with_no_bins_has_no_power():
    f = np.array([0.0, 10.0, 20.0])
    assert spectrum.band_power(f, np.ones(3), 100.0, 200.0) == 0.0
    assert spectrum.band_power(f, np.ones(3), 0.0, 25.0) == pytest.approx(20.0)


def test_psd_of_a_mono_signal_is_one_dimensional_and_of_stereo_is_averaged():
    mono = (np.sin(2 * math.pi * 1000 * np.arange(RATE) / RATE)).astype(np.float64)
    f, p = spectrum.psd(mono, RATE, nperseg=4096)
    assert p.ndim == 1 and len(p) == len(f)
    f2, p2 = spectrum.psd(np.stack([mono, mono], axis=1), RATE, nperseg=4096)
    assert p2.ndim == 1 and np.allclose(p, p2)


def test_a_given_spectrum_is_used_instead_of_computing_one():
    mono = np.sin(2 * math.pi * 1000 * np.arange(RATE) / RATE)
    f = np.linspace(0, RATE / 2, 1000)
    silent = (f, np.zeros(1000))
    bands = spectrum.third_octave(mono, RATE, f_p=silent)
    assert bands and all(level < -100 for _, level in bands)  # the sine is ignored: the spectrum passed in is silent
    assert spectrum.centroid(mono, RATE, f_p=(f, np.ones(1000))) > 5000  # a flat spectrum, not the sine's 1 kHz
