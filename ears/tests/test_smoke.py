"""Smoke tests for the ears package.

All tests run offline — no audio files or ML models required. Signals are
synthesized into tmp_path where a real file is needed.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from ears.models import (
    AudioProfile,
    LoudnessFeatures,
    RhythmFeatures,
    SimilarityResult,
    SpectralFeatures,
)
from ears.similarity import compare, cosine

SR = 48000


def _sine(freq: float, seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_audio_profile_round_trip() -> None:
    profile = AudioProfile(
        clip_id="abc123",
        audio_path="/tmp/test.mp3",
        duration_seconds=4.5,
        spectral=SpectralFeatures(spectral_centroid_mean=2000.0, mfcc_means=[1.0, 2.0]),
        rhythm=RhythmFeatures(bpm=130.0),
        embedding=[0.1] * 512,
    )
    restored = json.loads(json.dumps(profile.to_dict()))
    assert restored["clip_id"] == "abc123"
    assert restored["duration_seconds"] == 4.5
    assert restored["rhythm"]["bpm"] == 130.0
    assert restored["spectral"]["spectral_centroid_mean"] == 2000.0


def test_audio_profile_defaults() -> None:
    profile = AudioProfile(clip_id="x", audio_path="/tmp/x.mp3")
    assert profile.spectral is None
    assert profile.embedding is None
    assert profile.errors == []


def test_cosine_identical() -> None:
    v = [1.0, 0.0, 0.0]
    assert cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_none_on_mismatch_or_zero() -> None:
    assert cosine([1.0, 2.0], [1.0]) is None
    assert cosine([0.0, 0.0], [1.0, 0.0]) is None


def test_compare_no_embeddings() -> None:
    result = compare(AudioProfile(clip_id="a"), AudioProfile(clip_id="b"))
    assert isinstance(result, SimilarityResult)
    assert result.embedding_cosine is None
    assert result.overall_score is None
    assert result.spectral_distance is None


def test_compare_with_embeddings_and_spectral() -> None:
    emb = [1.0] + [0.0] * 511
    a = AudioProfile(clip_id="a", embedding=emb, spectral=SpectralFeatures(spectral_centroid_mean=1000.0))
    b = AudioProfile(clip_id="b", embedding=emb, spectral=SpectralFeatures(spectral_centroid_mean=3000.0))
    result = compare(a, b)
    assert result.embedding_cosine == pytest.approx(1.0)
    assert result.overall_score == pytest.approx(1.0)
    assert result.spectral_distance == pytest.approx(0.1)


def test_true_peak_is_dbtp() -> None:
    from ears.loudness import true_peak_dbtp

    # Full-scale-ish sine at 0.5 amplitude → about -6.02 dBTP.
    assert true_peak_dbtp(_sine(997.0, 1.0, 0.5), SR) == pytest.approx(-6.02, abs=0.05)
    assert true_peak_dbtp(np.zeros(SR, dtype=np.float32), SR) is None


def test_true_peak_catches_intersample_peak() -> None:
    from ears.loudness import true_peak_dbtp

    # fs/4 sine phased so every sample lands at ±0.707 of the true amplitude.
    n = np.arange(SR)
    x = np.sin(np.pi / 2 * n + np.pi / 4).astype(np.float32)
    sample_peak_db = 20 * np.log10(np.max(np.abs(x)))
    assert sample_peak_db == pytest.approx(-3.01, abs=0.05)
    assert true_peak_dbtp(x, SR) > sample_peak_db + 2.5


def test_loudness_uses_real_channels() -> None:
    from ears.loudness import extract

    tone = _sine(1000.0, 5.0, 0.25)
    silent = np.zeros_like(tone)
    hard_left = np.stack([tone, silent], axis=-1)
    dual_mono = np.stack([tone, tone], axis=-1)

    left = extract(tone, SR, hard_left)
    both = extract(tone, SR, dual_mono)
    assert left.lufs_integrated is not None and both.lufs_integrated is not None
    # Doubling the channels carrying the tone adds ~3 dB of summed power.
    assert both.lufs_integrated - left.lufs_integrated == pytest.approx(3.01, abs=0.1)
    assert isinstance(left, LoudnessFeatures)


def test_analyzer_on_stereo_file(tmp_path) -> None:
    from ears.analyzer import analyze

    path = tmp_path / "tone.wav"
    tone = _sine(220.0, 3.0, 0.5)
    sf.write(path, np.stack([tone, tone], axis=-1), SR)
    profile = analyze(str(path), run_embeddings=False)
    assert profile.errors == []
    assert profile.duration_seconds == pytest.approx(3.0, abs=0.01)
    assert profile.loudness.true_peak_db == pytest.approx(-6.02, abs=0.05)
    assert profile.spectral.spectral_centroid_mean > 0


def test_analyzer_missing_model_records_error(tmp_path, monkeypatch) -> None:
    from ears.analyzer import analyze

    path = tmp_path / "tone.wav"
    sf.write(path, _sine(220.0, 1.0, 0.5), SR)
    monkeypatch.setenv("EARS_DCLAP_MODEL", str(tmp_path / "missing.onnx"))
    profile = analyze(str(path), run_embeddings=True)
    assert profile.embedding is None
    assert any("DCLAP model not found" in e for e in profile.errors)


def test_analyzer_missing_file() -> None:
    from ears.analyzer import analyze

    profile = analyze("/nonexistent/path/to/audio.mp3")
    assert len(profile.errors) > 0
    assert "not found" in profile.errors[0].lower()
