"""Pairwise similarity between two AudioProfiles.

Initial implementation: cosine similarity on DCLAP embeddings + weighted
Euclidean distance on normalised spectral features. Returns a SimilarityResult
with per-dimension scores and an overall composite.
"""

from __future__ import annotations

from ears.models import AudioProfile, SimilarityResult


def compare(a: AudioProfile, b: AudioProfile) -> SimilarityResult:
    """Compare two AudioProfiles and return multi-dimensional similarity."""
    embedding_score = cosine(a.embedding, b.embedding)
    spectral_score = _spectral_distance(a, b)

    overall = embedding_score

    return SimilarityResult(
        clip_a=a.clip_id,
        clip_b=b.clip_id,
        embedding_cosine=embedding_score,
        spectral_distance=spectral_score,
        overall_score=overall,
    )


def cosine(v1: list[float] | None, v2: list[float] | None) -> float | None:
    """Cosine similarity between two vectors. Returns None if inputs are incompatible."""
    if v1 is None or v2 is None or len(v1) != len(v2):
        return None
    import numpy as np
    a = np.asarray(v1, dtype=np.float32)
    b = np.asarray(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return None
    return float(np.dot(a, b) / (norm_a * norm_b))


def _spectral_distance(a: AudioProfile, b: AudioProfile) -> float | None:
    if a.spectral is None or b.spectral is None:
        return None
    ca = a.spectral.spectral_centroid_mean
    cb = b.spectral.spectral_centroid_mean
    max_hz = 20_000.0
    return abs(ca - cb) / max_hz
