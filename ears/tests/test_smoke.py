"""Smoke tests for the ears package.

All tests run offline — no audio files or ML models required.
"""

from __future__ import annotations

import json
import math

from ears.models import (
    AudioProfile,
    LoudnessFeatures,
    RhythmFeatures,
    SimilarityResult,
    SpectralFeatures,
)
from ears.similarity import compare, cosine


def test_audio_profile_round_trip() -> None:
    profile = AudioProfile(
        clip_id="abc123",
        source_path="/tmp/test.mp3",
        duration_seconds=4.5,
        spectral=SpectralFeatures(centroid_hz=2000.0, mfcc=[1.0, 2.0, 3.0]),
        rhythm=RhythmFeatures(bpm=130.0),
        embedding=[0.1] * 512,
    )
    restored = AudioProfile.model_validate_json(profile.model_dump_json())
    assert restored.clip_id == profile.clip_id
    assert restored.duration_seconds == 4.5
    assert restored.rhythm is not None
    assert restored.rhythm.bpm == 130.0


def test_audio_profile_defaults() -> None:
    profile = AudioProfile(clip_id="x", source_path="/tmp/x.mp3")
    assert profile.spectral is None
    assert profile.embedding is None
    assert profile.errors == []


def test_cosine_identical() -> None:
    v = [1.0, 0.0, 0.0]
    assert cosine(v, v) == pytest_approx(1.0)


def test_cosine_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine(a, b) == pytest_approx(0.0)


def test_cosine_none_on_mismatch() -> None:
    from ears.similarity import cosine as _cosine
    result = _cosine([1.0, 2.0], [1.0])
    assert result is None


def test_compare_no_embeddings() -> None:
    a = AudioProfile(clip_id="a", source_path="/a.mp3")
    b = AudioProfile(clip_id="b", source_path="/b.mp3")
    result = compare(a, b)
    assert isinstance(result, SimilarityResult)
    assert result.embedding_cosine is None
    assert result.overall_score is None


def test_compare_with_embeddings() -> None:
    emb = [1.0] + [0.0] * 511
    a = AudioProfile(clip_id="a", source_path="/a.mp3", embedding=emb)
    b = AudioProfile(clip_id="b", source_path="/b.mp3", embedding=emb)
    result = compare(a, b)
    assert result.embedding_cosine is not None
    assert abs(result.embedding_cosine - 1.0) < 1e-6


def test_analyzer_missing_file() -> None:
    from ears.analyzer import analyze
    profile = analyze("/nonexistent/path/to/audio.mp3")
    assert len(profile.errors) > 0
    assert "not found" in profile.errors[0].lower()


# compat shim — avoid importing pytest just for approx
def pytest_approx(value: float, rel: float = 1e-6) -> "_Approx":
    return _Approx(value, rel)


class _Approx:
    def __init__(self, expected: float, rel: float) -> None:
        self.expected = expected
        self.rel = rel

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, float):
            return False
        return abs(other - self.expected) <= self.rel * max(abs(self.expected), 1e-12)
