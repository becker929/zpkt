"""Audio analysis orchestrator — runs extractors in parallel, returns AudioProfile."""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import AudioProfile


def _clip_id(path: str) -> str:
    stat = os.stat(path)
    raw = f"{os.path.abspath(path)}:{stat.st_mtime}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def analyze(
    audio_path: str,
    run_embeddings: bool = True,
    run_rhythm: bool = False,
    run_pitch: bool = False,
) -> AudioProfile:
    """Run audio extractors in parallel and return an AudioProfile.

    Args:
        audio_path:     Path to WAV or MP3 file.
        run_embeddings: Compute 512-dim DCLAP embedding (requires onnxruntime). Default True.
        run_rhythm:     BPM / beat tracking via madmom (optional dep). Default False.
        run_pitch:      Predominant pitch via basic-pitch (optional dep). Default False.

    Returns:
        AudioProfile with all available features. Failed extractors are noted in
        ``profile.errors`` and their fields are left None rather than raising.
    """
    import librosa

    profile = AudioProfile(
        clip_id=_clip_id(audio_path),
        audio_path=os.path.abspath(audio_path),
        extracted_at=time.time(),
    )

    try:
        audio, sr = librosa.load(audio_path, sr=None, mono=True)
        profile.duration_seconds = float(len(audio) / sr)
        profile.sample_rate = int(sr)
    except Exception as exc:
        profile.errors.append(f"audio load failed: {exc}")
        return profile

    def run_spectral():
        from .features import extract
        return "spectral", extract(audio, sr)

    def run_loudness():
        from .loudness import extract
        return "loudness", extract(audio, sr)

    def run_rhythm_task():
        from .rhythm import extract
        return "rhythm", extract(audio_path)

    def run_pitch_task():
        from .pitch import extract
        return "pitch", extract(audio_path)

    def run_embed():
        from .embeddings import embed
        return "embedding", embed(audio_path)

    tasks = [run_spectral, run_loudness]
    if run_embeddings:
        tasks.append(run_embed)
    if run_rhythm:
        tasks.append(run_rhythm_task)
    if run_pitch:
        tasks.append(run_pitch_task)

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
                elif key == "embedding":
                    profile.embedding = [float(v) for v in result]
            except Exception as exc:
                profile.errors.append(f"{futures[future]} failed: {exc}")

    return profile
