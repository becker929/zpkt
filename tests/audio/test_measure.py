"""zpkt.audio.measure: a render's peak, loudness and third-octave spectrum, on made-up audio."""

from __future__ import annotations

import math

import numpy as np
import pytest
import soundfile as sf

from zpkt.audio import measure
from zpkt.audio.levels import SILENCE_DB, band_centers

RATE = 44100


def sine(hz: float, amp: float, seconds: float = 2.0, channels: int = 2) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    x = (amp * np.sin(2 * math.pi * hz * t)).astype(np.float32)
    return np.stack([x] * channels, axis=1)


def test_a_sine_reads_its_peak_rms_and_band():
    m = measure.measure_samples(sine(1000, 0.5), RATE)
    assert m["peak_db"] == pytest.approx(-6.02, abs=0.05)
    assert m["rms_db"] == pytest.approx(-9.03, abs=0.05)
    assert m["seconds"] == 2.0 and m["rate"] == RATE
    loud = max(range(31), key=lambda k: m["bands_db"][k])
    assert band_centers()[loud] == pytest.approx(1000, rel=0.13)
    assert m["bands_db"][loud] == pytest.approx(-9.03, abs=1.0)
    quiet = [b for k, b in enumerate(m["bands_db"]) if abs(k - loud) > 2]
    assert max(quiet) < m["bands_db"][loud] - 30


def test_silence_is_the_silence_level():
    m = measure.measure_samples(np.zeros((RATE, 2), dtype=np.float32), RATE)
    assert m["peak_db"] == SILENCE_DB and m["rms_db"] == SILENCE_DB
    assert set(m["bands_db"]) == {SILENCE_DB}


def test_a_short_file_is_padded_and_has_no_loudness():
    m = measure.measure_samples(sine(200, 0.3, seconds=0.1), RATE)
    assert m["lufs"] is None
    assert len(m["bands_db"]) == 31


def test_a_wav_on_disk_is_measured_and_a_broken_one_says_what_to_do(tmp_path):
    good = tmp_path / "a.wav"
    sf.write(good, sine(440, 0.25), RATE, subtype="PCM_16")
    m = measure.measure_wav(good)
    assert m["peak_db"] == pytest.approx(-12.04, abs=0.1)
    assert m["lufs"] is not None
    bad = tmp_path / "b.wav"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(ValueError, match="could not be read as audio"):
        measure.measure_wav(bad)


def test_gap_is_a_minus_b_and_none_when_a_side_lacks_loudness():
    a = measure.measure_samples(sine(1000, 0.5), RATE)
    b = measure.measure_samples(sine(1000, 0.25), RATE)
    g = measure.gap(a, b)
    assert g["peak_db"] == pytest.approx(6.02, abs=0.05) and g["rms_db"] == pytest.approx(6.02, abs=0.05)
    assert len(g["bands_db"]) == 31
    assert measure.gap({**a, "lufs": None}, b)["lufs"] is None


def test_the_bands_are_the_meters_bands():
    from zpkt.live import meter

    assert band_centers() == pytest.approx(meter.centers())
