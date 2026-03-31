"""
Audio analysis orchestrator.
Runs all extractors in parallel and returns a unified AudioProfile.
"""

from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from .features import SpectralFeatures
from .loudness import LoudnessFeatures
from .rhythm import RhythmFeatures
from .pitch import PitchFeatures
from .separator import Stems


@dataclass
class AudioProfile:
    clip_id: str = ""                    # SHA-256 of file path + mtime
    audio_path: str = ""
    duration_seconds: float = 0.0
    sample_rate: int = 0
    # Extractors
    spectral: Optional[SpectralFeatures] = None
    loudness: Optional[LoudnessFeatures] = None
    rhythm: Optional[RhythmFeatures] = None
    pitch: Optional[PitchFeatures] = None
    stems: Optional[Stems] = None
    # 512-dim DCLAP embedding (stored as list for JSON serialization)
    embedding: list[float] = field(default_factory=list)
    # LLM-generated natural language description
    description: str = ""
    # Extraction metadata
    extracted_at: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)


def _clip_id(path: str) -> str:
    stat = os.stat(path)
    raw = f"{os.path.abspath(path)}:{stat.st_mtime}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def analyze(
    audio_path: str,
    decomposition: str = "full_mix",
    run_pitch: bool = True,
    run_stems: bool = True,
    run_embeddings: bool = True,
) -> AudioProfile:
    """
    Run all audio extractors in parallel.

    Args:
        audio_path: Path to audio file (WAV or MP3).
        decomposition: One of "full_mix", "stem:<name>", "band:<range>".
        run_pitch: Whether to run basic-pitch (slow, ~10s per track).
        run_stems: Whether to attempt stem separation.
        run_embeddings: Whether to compute DCLAP embedding.

    Returns:
        AudioProfile with all available features populated.
    """
    import librosa
    import soundfile as sf

    profile = AudioProfile(
        clip_id=_clip_id(audio_path),
        audio_path=os.path.abspath(audio_path),
        extracted_at=time.time(),
    )

    # Load audio for in-memory extractors
    try:
        audio, sr = librosa.load(audio_path, sr=None, mono=True)
        profile.duration_seconds = float(len(audio) / sr)
        profile.sample_rate = sr
    except Exception as e:
        profile.errors.append(f"audio load failed: {e}")
        return profile

    # Define extractor tasks
    def run_spectral():
        from .features import extract as feat_extract
        return "spectral", feat_extract(audio, sr)

    def run_loudness():
        from .loudness import extract as loud_extract
        return "loudness", loud_extract(audio, sr)

    def run_rhythm():
        from .rhythm import extract as rhythm_extract
        return "rhythm", rhythm_extract(audio_path)

    def run_pitch_task():
        from .pitch import extract as pitch_extract
        return "pitch", pitch_extract(audio_path)

    def run_stems_task():
        from .separator import separate
        return "stems", separate(audio_path)

    def run_embed():
        from .embeddings import embed
        return "embedding", embed(audio_path)

    tasks = [run_spectral, run_loudness, run_rhythm]
    if run_pitch:
        tasks.append(run_pitch_task)
    if run_stems:
        tasks.append(run_stems_task)
    if run_embeddings:
        tasks.append(run_embed)

    with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futures = {pool.submit(t): t.__name__ for t in tasks}
        for future in as_completed(futures):
            try:
                key, result = future.result()
                if key == "spectral":
                    profile.spectral = result
                elif key == "loudness":
                    profile.loudness = result
                elif key == "rhythm":
                    profile.rhythm = result
                elif key == "pitch":
                    profile.pitch = result
                elif key == "stems":
                    profile.stems = result
                elif key == "embedding":
                    profile.embedding = [float(v) for v in result]
            except Exception as e:
                profile.errors.append(f"{futures[future]} failed: {e}")

    return profile
