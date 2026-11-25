"""Property tests of the measuring code: gain shifts levels by the same dB everywhere, and results stay in range."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from zpkt.audio import measure
from zpkt.audio.levels import SILENCE_DB, rms_to_db
from zpkt.audio.meters import loudness

RATE = 22050


def noise(seed: int, seconds: float = 0.6, channels: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (0.1 * rng.standard_normal((int(RATE * seconds), channels))).astype(np.float32)


@given(seed=st.integers(0, 10_000), gain_db=st.floats(-20.0, 10.0))
def test_gain_moves_peak_rms_and_every_audible_band_by_the_same_db(seed, gain_db):
    x = noise(seed)
    g = 10 ** (gain_db / 20)
    a, b = measure.measure_samples(x, RATE), measure.measure_samples((x * g).astype(np.float32), RATE)
    assert b["peak_db"] - a["peak_db"] == pytest.approx(gain_db, abs=0.05)
    assert b["rms_db"] - a["rms_db"] == pytest.approx(gain_db, abs=0.05)
    for lo, hi in zip(a["bands_db"], b["bands_db"], strict=True):
        if lo > SILENCE_DB + 1 and hi > SILENCE_DB + 1:
            assert hi - lo == pytest.approx(gain_db, abs=0.1)


@given(seed=st.integers(0, 10_000))
def test_a_measure_has_one_level_per_band_and_a_peak_above_the_rms(seed):
    m = measure.measure_samples(noise(seed), RATE)
    assert len(m["bands_db"]) == 31
    assert m["peak_db"] >= m["rms_db"]
    assert m["peak_db"] <= 0.0 and all(SILENCE_DB <= b <= 3.0 for b in m["bands_db"])


@given(seed=st.integers(0, 10_000))
def test_a_measure_against_itself_has_no_gap(seed):
    m = measure.measure_samples(noise(seed), RATE)
    g = measure.gap(m, m)
    assert g["peak_db"] == 0.0 and g["rms_db"] == 0.0 and set(g["bands_db"]) == {0.0}


@given(levels=st.lists(st.floats(0.0, 2.0), max_size=40))
def test_rms_to_db_is_monotonic_and_floors_at_silence(levels):
    out = rms_to_db(sorted(levels))
    assert out == sorted(out) and all(v >= SILENCE_DB for v in out)


@given(seed=st.integers(0, 10_000), gain_db=st.floats(-12.0, 6.0))
def test_gain_shifts_momentary_loudness_by_the_same_db(seed, gain_db):
    x = noise(seed, seconds=1.0, channels=1).astype(np.float64)
    a = loudness.momentary(x, RATE)
    b = loudness.momentary(x * 10 ** (gain_db / 20), RATE)
    assert len(a) == len(b) > 0
    assert np.allclose(b - a, gain_db, atol=1e-6)
