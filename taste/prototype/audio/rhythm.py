"""Beat, tempo, and groove extraction via madmom."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class RhythmFeatures:
    bpm: Optional[float] = None
    bpm_confidence: float = 0.0
    beats: list[float] = field(default_factory=list)       # beat times in seconds
    downbeats: list[float] = field(default_factory=list)   # downbeat times
    meter_numerator: int = 4                               # estimated time signature numerator
    swing_ratio: Optional[float] = None                    # > 0.5 = swung, ~0.5 = straight
    beat_regularity: float = 0.0                           # std of inter-beat intervals (lower = more regular)
    groove_density: float = 0.0                            # onsets per beat (higher = busier)


def extract(audio_path: str) -> RhythmFeatures:
    """Extract rhythm features from an audio file path. Uses madmom file-based API."""
    import madmom.features.beats as mb
    import madmom.features.tempo as mt

    feats = RhythmFeatures()

    try:
        # Beat activation function via RNN
        beat_proc = mb.RNNBeatProcessor()(audio_path)

        # Beat tracking via dynamic programming
        beat_tracker = mb.BeatTrackingProcessor(fps=100)
        beats = beat_tracker(beat_proc)
        feats.beats = [float(b) for b in beats]

        # Tempo from beat intervals
        if len(beats) > 1:
            ibi = np.diff(beats)  # inter-beat intervals
            bpm = 60.0 / np.median(ibi)
            feats.bpm = float(bpm)
            feats.beat_regularity = float(np.std(ibi))

        # Downbeat detection via RNN
        try:
            downbeat_proc = mb.RNNDownBeatProcessor()(audio_path)
            downbeat_tracker = mb.DBNDownBeatTrackingProcessor(
                beats_per_bar=[3, 4], fps=100
            )
            downbeats_raw = downbeat_tracker(downbeat_proc)
            # downbeats_raw is array of (time, beat_number)
            downbeat_times = [
                float(row[0]) for row in downbeats_raw if int(row[1]) == 1
            ]
            feats.downbeats = downbeat_times
            # Infer meter from most common beat count between downbeats
            if len(downbeats_raw) > 1:
                beat_nums = [int(row[1]) for row in downbeats_raw]
                feats.meter_numerator = int(max(set(beat_nums), key=beat_nums.count))
        except Exception:
            pass

        # Swing ratio: compare even vs odd 8th-note spacings within beats
        if len(beats) > 2:
            feats.swing_ratio = _compute_swing(beats)

        # Groove density via onset detection with librosa
        try:
            import librosa
            import soundfile as sf
            audio, sr = sf.read(audio_path, dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
            onsets = librosa.onset.onset_detect(
                onset_envelope=onset_env, sr=sr, units="time"
            )
            if len(feats.beats) > 0 and feats.bpm and feats.bpm > 0:
                duration = feats.beats[-1] if feats.beats else 1.0
                n_beats = max(1, len(feats.beats))
                feats.groove_density = len(onsets) / n_beats
        except Exception:
            pass

    except Exception:
        pass

    return feats


def _compute_swing(beats: list[float]) -> Optional[float]:
    """Estimate swing ratio from beat sequence (values >0.5 indicate swing)."""
    if len(beats) < 4:
        return None
    ibis = np.diff(beats)
    # Compare adjacent pairs as 8th-note on/off
    if len(ibis) < 2:
        return None
    even = ibis[0::2]
    odd = ibis[1::2]
    min_len = min(len(even), len(odd))
    if min_len == 0:
        return None
    total = even[:min_len] + odd[:min_len]
    mask = total > 0
    if not np.any(mask):
        return None
    ratio = np.mean(even[:min_len][mask] / total[mask])
    return float(ratio)
