"""Polyphonic pitch / note transcription via basic-pitch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class PitchFeatures:
    note_density: float = 0.0            # notes per second
    pitch_range_semitones: int = 0       # max - min MIDI pitch
    pitch_min_midi: Optional[int] = None
    pitch_max_midi: Optional[int] = None
    pitch_center_midi: Optional[float] = None
    dominant_pitch_class: Optional[str] = None   # e.g. "A"
    interval_distribution: dict[int, float] = field(default_factory=dict)  # semitone intervals
    polyphony_mean: float = 0.0          # average simultaneous notes
    note_count: int = 0


def extract(audio_path: str) -> PitchFeatures:
    """Extract pitch features from an audio file path via basic-pitch."""
    feats = PitchFeatures()

    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH

        model_output, midi_data, note_events = predict(audio_path)
        # note_events: list of (start_time, end_time, pitch_midi, amplitude, pitch_bends)
        if not note_events:
            return feats

        feats.note_count = len(note_events)
        pitches = [int(n[2]) for n in note_events]
        starts = [float(n[0]) for n in note_events]
        ends = [float(n[1]) for n in note_events]

        duration = max(ends) - min(starts) if ends else 1.0
        feats.note_density = feats.note_count / max(duration, 0.1)
        feats.pitch_min_midi = min(pitches)
        feats.pitch_max_midi = max(pitches)
        feats.pitch_range_semitones = feats.pitch_max_midi - feats.pitch_min_midi
        feats.pitch_center_midi = float(np.mean(pitches))

        # Dominant pitch class
        pitch_classes = [p % 12 for p in pitches]
        if pitch_classes:
            dominant_class = max(set(pitch_classes), key=pitch_classes.count)
            feats.dominant_pitch_class = NOTE_NAMES[dominant_class]

        # Interval distribution (semitones between consecutive notes)
        if len(pitches) > 1:
            intervals = [abs(pitches[i + 1] - pitches[i]) for i in range(len(pitches) - 1)]
            total = len(intervals)
            interval_counts: dict[int, int] = {}
            for iv in intervals:
                interval_counts[iv] = interval_counts.get(iv, 0) + 1
            feats.interval_distribution = {
                k: v / total for k, v in sorted(interval_counts.items())
            }

        # Polyphony: average number of notes active at any given time
        feats.polyphony_mean = _mean_polyphony(note_events)

    except Exception:
        pass

    return feats


def _mean_polyphony(note_events: list) -> float:
    """Compute mean number of simultaneously active notes."""
    if not note_events:
        return 0.0
    events: list[tuple[float, int]] = []
    for note in note_events:
        events.append((float(note[0]), +1))
        events.append((float(note[1]), -1))
    events.sort(key=lambda x: x[0])
    active = 0
    samples = []
    for _, delta in events:
        active += delta
        samples.append(active)
    return float(np.mean(samples)) if samples else 0.0
