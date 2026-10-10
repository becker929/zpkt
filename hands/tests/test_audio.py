"""hands.audio on synthetic audio: silence and length checks, slicing, trimming, timeline checks."""
from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from hands import audio
from hands.audio import AudioError

SR = 44100


def tone(seconds, hz=110.0, dbfs=-12.0, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    x = 10 ** (dbfs / 20) * np.sin(2 * np.pi * hz * t)
    return np.stack([x, x], axis=1)


def write(path, x, sr=SR):
    sf.write(path, x, sr, subtype="FLOAT")
    return path


def test_check_audio_passes_a_real_render(tmp_path):
    s = audio.check_audio(write(tmp_path / "ok.wav", tone(2.0)), seconds=2.0)
    assert s["channels"] == 2 and s["peak_dbfs"] == pytest.approx(-12.0, abs=0.01)
    assert s["rms_dbfs"] == pytest.approx(-15.01, abs=0.05)


def test_check_audio_catches_silence_length_and_garbage(tmp_path):
    with pytest.raises(AudioError, match="silent"):
        audio.check_audio(write(tmp_path / "silent.wav", np.zeros((SR, 2))), seconds=1.0)
    with pytest.raises(AudioError, match="1.000 s long, expected 1.500"):
        audio.check_audio(write(tmp_path / "short.wav", tone(1.0)), seconds=1.5)
    nan = tone(1.0)
    nan[100] = np.nan
    with pytest.raises(AudioError, match="NaN"):
        audio.check_audio(write(tmp_path / "nan.wav", nan), seconds=1.0)
    (tmp_path / "junk.wav").write_bytes(b"not audio")
    with pytest.raises(AudioError, match="unreadable"):
        audio.check_audio(tmp_path / "junk.wav", seconds=1.0)
    with pytest.raises(AudioError, match="unreadable"):
        audio.check_audio(tmp_path / "missing.wav", seconds=1.0)
    quiet = tone(1.0, dbfs=-70.0)
    assert audio.check_audio(write(tmp_path / "quiet.wav", quiet), seconds=1.0, min_rms_dbfs=-80.0)


def test_slice_render_cuts_at_the_pattern_starts(tmp_path):
    # a 2 s lead and three 1 s patterns, each a different constant level
    x = np.concatenate([np.full((2 * SR, 2), 0.1)] + [np.full((SR, 2), v) for v in (0.2, 0.3, 0.4)])
    files = audio.slice_render(write(tmp_path / "all.wav", x), [2.0, 3.0, 4.0, 5.0], tmp_path / "out")
    assert [f.name for f in files] == ["pattern_00.wav", "pattern_01.wav", "pattern_02.wav"]
    pieces = [sf.read(f, always_2d=True)[0] for f in files]
    assert [len(p) for p in pieces] == [SR, SR, SR]
    assert [round(float(p.mean()), 3) for p in pieces] == [0.2, 0.3, 0.4]
    assert sf.info(files[0]).subtype == "FLOAT"


def test_slice_render_refuses_a_render_that_ends_early(tmp_path):
    path = write(tmp_path / "all.wav", tone(4.995))
    assert len(audio.slice_render(path, [0.0, 2.5, 5.0], tmp_path / "a")) == 2   # 5 ms short: fine
    with pytest.raises(AudioError, match="before the last cut"):
        audio.slice_render(path, [0.0, 2.5, 5.1], tmp_path / "b")


def test_trim_take_cuts_at_song_beat_zero_plus_the_lead(tmp_path):
    zero_s, tempo = 0.9, 160.0            # song beat 0 sits 0.9 s into the take
    x = np.full((int(6 * SR), 2), 0.5)
    beat8 = int(round(zero_s * SR)) + int(8 * 60 / tempo * SR)   # song beat 8: the end of a 2-bar lead
    x[beat8 + 4410] = 1.0                                         # a click 0.1 s after it
    take = write(tmp_path / "take.wav", x)
    (tmp_path / "take.wav.timing.json").write_text(json.dumps({"song_zero_seconds": zero_s, "tempo": tempo}))
    y, sr = audio.trim_take(take, lead_beats=8, length_beats=4)
    assert sr == SR and len(y) == int(round(4 * 60 / tempo * SR))
    assert y[0, 0] == 0.0 and y[-1, 0] == 0.0               # faded in and out
    assert np.argmax(y[:, 0]) == 4410                        # cut exactly at song beat 8
    assert y[int(0.02 * SR), 0] == pytest.approx(0.5)


def test_best_lag_finds_a_known_shift():
    rng = np.random.default_rng(7)
    b = rng.standard_normal(SR)
    a = b[20_000 + 300:20_000 + 300 + 4000]
    lag, corr = audio.best_lag(a, b, 20_000, 1000)
    assert lag == 300 and corr == pytest.approx(1.0, abs=1e-6)


def test_low_band_keeps_the_kick_and_drops_the_hats():
    t = np.arange(SR) / SR
    x = np.sin(2 * np.pi * 50 * t) + np.sin(2 * np.pi * 5000 * t)
    y = audio.low_band(np.stack([x, x], axis=1), SR, hz=150)
    assert np.allclose(y, np.sin(2 * np.pi * 50 * t), atol=1e-6)


def test_timeline_check_finds_a_slip():
    rng = np.random.default_rng(3)
    ref = rng.standard_normal(4 * SR)
    assert audio.timeline_check(ref[:3 * SR], ref, SR) == {"median_lag_s": 0.0, "jumps_s": [], "ok": True}
    slipped = np.concatenate([ref[:2 * SR], ref[2 * SR + int(0.05 * SR):]])[:3 * SR]   # 50 ms lost at 2 s
    res = audio.timeline_check(slipped, ref, SR)
    assert not res["ok"] and res["jumps_s"][0] == 2.0
    assert audio.timeline_check(slipped, ref, SR, skip=lambda t: t >= 2.0)["ok"]
