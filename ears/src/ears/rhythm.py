"""Beat, tempo, and groove extraction via madmom (optional dependency)."""
from __future__ import annotations

import numpy as np

from .models import RhythmFeatures


def extract(audio_path: str) -> RhythmFeatures:
    """Extract rhythm features. Requires: uv pip install 'ears[rhythm]'."""
    try:
        import madmom.features.beats as mb
    except ImportError:
        raise ImportError(
            "madmom is not installed. Install with: uv pip install 'ears[rhythm]'"
        )

    feats = RhythmFeatures()
    try:
        beat_proc = mb.RNNBeatProcessor()(audio_path)
        beats = mb.BeatTrackingProcessor(fps=100)(beat_proc)
        feats.beats = [float(b) for b in beats]
        if len(beats) > 1:
            ibi = np.diff(beats)
            feats.bpm = float(60.0 / np.median(ibi))
            feats.beat_regularity = float(np.std(ibi))
        try:
            db_proc = mb.RNNDownBeatProcessor()(audio_path)
            db_raw = mb.DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)(db_proc)
            feats.downbeats = [float(r[0]) for r in db_raw if int(r[1]) == 1]
            if len(db_raw) > 1:
                nums = [int(r[1]) for r in db_raw]
                feats.meter_numerator = int(max(set(nums), key=nums.count))
        except Exception:
            pass
    except Exception:
        pass
    return feats
