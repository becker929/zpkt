"""Dataclasses for the ears AudioProfile and all sub-feature types."""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field


@dataclass
class SpectralFeatures:
    spectral_centroid_mean: float = 0.0
    spectral_centroid_std: float = 0.0
    spectral_rolloff_mean: float = 0.0
    spectral_bandwidth_mean: float = 0.0
    spectral_flatness_mean: float = 0.0
    zero_crossing_rate_mean: float = 0.0
    harmonic_ratio_mean: float = 0.0
    onset_strength_mean: float = 0.0
    onset_strength_std: float = 0.0
    mfcc_means: list[float] = field(default_factory=list)
    mfcc_stds: list[float] = field(default_factory=list)
    chroma_means: list[float] = field(default_factory=list)
    key: str | None = None
    key_strength: float = 0.0
    danceability: float | None = None


@dataclass
class LoudnessFeatures:
    lufs_integrated: float | None = None
    lufs_short_term_peak: float | None = None
    lufs_momentary_max: float | None = None
    true_peak_db: float | None = None  # dBTP (4x oversampled, BS.1770)
    band_energy: dict[str, float] = field(default_factory=dict)
    camelot_key: str | None = None


@dataclass
class RhythmFeatures:
    bpm: float | None = None
    bpm_confidence: float = 0.0
    beats: list[float] = field(default_factory=list)
    downbeats: list[float] = field(default_factory=list)
    meter_numerator: int = 4
    swing_ratio: float | None = None
    beat_regularity: float = 0.0
    groove_density: float = 0.0


@dataclass
class PitchFeatures:
    predominant_pitch_hz: float | None = None
    pitch_confidence: float = 0.0
    note_events: list[dict] = field(default_factory=list)


@dataclass
class AudioProfile:
    clip_id: str = ""
    audio_path: str = ""
    duration_seconds: float = 0.0
    sample_rate: int = 0
    spectral: SpectralFeatures | None = None
    loudness: LoudnessFeatures | None = None
    rhythm: RhythmFeatures | None = None
    pitch: PitchFeatures | None = None
    embedding: list[float] | None = None
    description: str = ""
    extracted_at: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SimilarityResult:
    clip_a: str
    clip_b: str
    embedding_cosine: float | None = None
    spectral_distance: float | None = None
    overall_score: float | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
