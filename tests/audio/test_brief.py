"""The short sheet of an audio file (zpkt.audio.brief): a few numbers that are right, on tones whose answer is known."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from zpkt.audio import brief

SR = 44100


def tone(hz: float, amp: float, seconds: float) -> np.ndarray:
    """A sine that fades in and out over 20 ms: an abrupt start is a click, which is in every band."""
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * hz * t) * np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)


def write(path, left, right=None):
    sf.write(str(path), left if right is None else np.column_stack([left, right]), SR, subtype="PCM_24")
    return path


def power_sum(levels) -> float:
    return 10 * np.log10(sum(10 ** (v / 10) for v in levels))


def test_a_tone_lands_in_its_band_and_the_bands_add_up_to_the_rms(tmp_path):
    f = write(tmp_path / "a.wav", tone(100, 0.5, 4.0), tone(100, 0.5, 4.0))
    got = brief.brief(f)
    assert got["seconds"] == 4.0
    assert got["peak_db"] == pytest.approx(-6.0, abs=0.1) and got["rms_db"] == pytest.approx(-9.0, abs=0.2)
    assert got["crest_db"] == pytest.approx(3.0, abs=0.2) and got["true_peak_db"] == pytest.approx(-6.0, abs=0.2)
    bands = got["bands_db"]
    assert list(bands) == ["sub", "low", "mid", "high", "air"]
    assert bands["low"] == pytest.approx(got["rms_db"], abs=0.1)  # 100 Hz: all of it is in 60 to 250
    assert all(bands[b] < -60 for b in ("sub", "mid", "high", "air"))
    assert power_sum(bands.values()) == pytest.approx(got["rms_db"], abs=0.1)
    assert got["stereo"] == {"correlation": 1.0, "side_vs_mid_db": -120.0}  # both sides the same: no side at all
    assert isinstance(got["lufs"], float) and "silent" not in got


def test_two_tones_split_between_two_bands(tmp_path):
    f = write(tmp_path / "a.wav", tone(40, 0.25, 3.0) + tone(8000, 0.25, 3.0))
    got = brief.brief(f)
    assert got["bands_db"]["sub"] == pytest.approx(got["bands_db"]["air"], abs=0.2)
    assert got["bands_db"]["sub"] == pytest.approx(got["rms_db"] - 3.0, abs=0.2)  # half the power each
    assert got["channels"] == 1 and "stereo" not in got


def test_opposite_sides_have_correlation_minus_one_and_a_silent_file_says_so(tmp_path):
    left = tone(440, 0.3, 2.0)
    got = brief.brief(write(tmp_path / "a.wav", left, -left))
    assert got["stereo"]["correlation"] == -1.0
    quiet = brief.brief(write(tmp_path / "q.wav", np.zeros(SR), np.zeros(SR)))
    assert quiet["silent"] is True and quiet["rms_db"] == -120.0 and quiet["lufs"] is None


def test_a_window_measures_only_its_seconds(tmp_path):
    f = write(tmp_path / "a.wav", np.concatenate([tone(100, 0.5, 2.0), tone(100, 0.05, 2.0)]))
    loud, soft = brief.brief(f, 0, 2), brief.brief(f, 2, 4)
    assert loud["seconds"] == soft["seconds"] == 2.0
    assert loud["rms_db"] - soft["rms_db"] == pytest.approx(20.0, abs=0.2)
    assert brief.seconds(f) == pytest.approx(4.0)
    with pytest.raises(brief.BriefError, match="holds nothing"):
        brief.brief(f, 5, 6)
    with pytest.raises(brief.BriefError, match="not an audio file"):
        brief.brief(tmp_path / "missing.wav")
    (tmp_path / "text.wav").write_text("not audio")
    with pytest.raises(brief.BriefError, match="not an audio file"):
        brief.brief(tmp_path / "text.wav")


def test_the_spectrum_peaks_at_the_tones_third_octave(tmp_path):
    f = write(tmp_path / "a.wav", tone(1000, 0.5, 3.0))
    got = brief.spectrum(f)
    assert next(iter(got)) == "25" and list(got)[-1] == "16000" and len(got) == 29
    assert max(got, key=lambda k: got[k]) == "1000" and got["1000"] == pytest.approx(-9.0, abs=0.2)
    assert got["250"] < -60


def test_over_time_shows_where_the_level_changes(tmp_path):
    f = write(tmp_path / "a.wav", np.concatenate([tone(100, 0.5, 2.0), np.zeros(SR), tone(100, 0.05, 1.0)]))
    got = brief.over_time(f, 1.0)
    assert got["rms_db"] == pytest.approx([-9.0, -9.0, -120.0, -29.0], abs=0.2)
    assert got["peak_db"][0] == pytest.approx(-6.0, abs=0.1) and len(got["peak_db"]) == 4
    assert len(brief.over_time(f, 1.0, 1.0, 3.0)["rms_db"]) == 2
    with pytest.raises(brief.BriefError, match="at most 64"):
        brief.over_time(f, 0.01)
    with pytest.raises(brief.BriefError):
        brief.over_time(f, 0)


def test_the_difference_is_number_by_number_and_leaves_out_what_is_not_a_level():
    a = {"seconds": 4.0, "lufs": -10.0, "bands_db": {"sub": -20.0, "low": -12.0}, "silent": True, "rms_db": [-9, -10]}
    b = {"seconds": 8.0, "lufs": -14.0, "bands_db": {"sub": -23.5, "low": -12.0}, "lufs_x": 1, "rms_db": [-12, -10]}
    assert brief.difference(a, b) == {"lufs": 4.0, "bands_db": {"sub": 3.5, "low": 0.0}, "rms_db": [3.0, 0.0]}
    assert brief.difference({"lufs": None}, {"lufs": -3.0}) is None  # nothing both hold as a number
    assert brief.difference({"rms_db": [1, 2]}, {"rms_db": [1, 2, 3]}) is None  # not the same steps
