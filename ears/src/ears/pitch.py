"""Predominant pitch extraction via basic-pitch (optional dependency)."""
from __future__ import annotations

from .models import PitchFeatures


def extract(audio_path: str) -> PitchFeatures:
    """Extract predominant pitch. Requires: uv pip install 'ears[pitch]'."""
    try:
        from basic_pitch.inference import predict  # type: ignore[import]
        from basic_pitch import ICASSP_2022_MODEL_PATH  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "basic-pitch is not installed. Install with: uv pip install 'ears[pitch]'"
        )

    feats = PitchFeatures()
    try:
        model_output, midi_data, note_events = predict(audio_path, ICASSP_2022_MODEL_PATH)
        if note_events:
            pitches = [n[2] for n in note_events if len(n) > 2]
            if pitches:
                import numpy as np
                feats.predominant_pitch_hz = float(np.median(pitches))
        feats.note_events = [
            {"start": float(n[0]), "end": float(n[1]), "pitch_hz": float(n[2]),
             "velocity": int(n[3]) if len(n) > 3 else 80}
            for n in (note_events or [])
        ]
    except Exception:
        pass
    return feats
