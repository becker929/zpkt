"""Predominant pitch extraction via basic-pitch (optional dependency)."""

from __future__ import annotations

import logging

from .models import PitchFeatures

log = logging.getLogger(__name__)


def extract(audio_path: str) -> PitchFeatures:
    """Extract predominant pitch. Needs basic-pitch, which ears does not install (see pyproject.toml)."""
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict
    except ImportError:
        raise ImportError("basic-pitch is not installed: run `uv pip install basic-pitch` in ears/") from None

    feats = PitchFeatures()
    try:
        _model_output, _midi_data, note_events = predict(audio_path, ICASSP_2022_MODEL_PATH)
        if note_events:
            pitches = [n[2] for n in note_events if len(n) > 2]
            if pitches:
                import numpy as np

                feats.predominant_pitch_hz = float(np.median(pitches))
        feats.note_events = [
            {
                "start": float(n[0]),
                "end": float(n[1]),
                "pitch_hz": float(n[2]),
                "velocity": int(n[3]) if len(n) > 3 else 80,
            }
            for n in (note_events or [])
        ]
    except Exception:
        log.debug("pitch and note events skipped", exc_info=True)  # best effort: the field stays empty
    return feats
