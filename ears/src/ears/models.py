"""Dataclasses for the ears AudioProfile and all sub-feature types."""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Optional


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
    key: Optional[str] = None
    key_strength: float = 0.0
    danceability: Optional[float] = None


@dataclass
class LoudnessFeatures:
    lufs_integrated: Optional[float] = None
    lufs_short_term_peak: Optional[float] = None
    lufs_momentary_max: Optional[float] = None
    true_peak_db: Optional[float] = None
    band_energy: dict[str, float] = field(default_factory=dict)
    camelot_key: Optional[str] = None


@dataclass
class RhythmFeatures:
    bpm: Optional[float] = None
    bpm_confidence: float = 0.0
    beats: list[float] = field(default_factory=list)
    downbeats: list[float] = field(default_factory=list)
    meter_numerator: int = 4
    swing_ratio: Optional[float] = None
    beat_regularity: float = 0.0
    groove_density: float = 0.0


@dataclass
class PitchFeatures:
    predominant_pitch_hz: Optional[float] = None
    pitch_confidence: float = 0.0
    note_events: list[dict] = field(default_factory=list)


@dataclass
class AudioProfile:
    clip_id: str = ""
    audio_path: str = ""
    duration_seconds: float = 0.0
    sample_rate: int = 0
    spectral: Optional[SpectralFeatures] = None
    loudness: Optional[LoudnessFeatures] = None
    rhythm: Optional[RhythmFeatures] = None
    pitch: Optional[PitchFeatures] = None
    embedding: list[float] = field(default_factory=list)
    description: str = ""
    extracted_at: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
