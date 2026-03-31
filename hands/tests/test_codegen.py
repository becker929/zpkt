"""Tests for hands.codegen — Step, gen_* functions, and hz_to_eq8_norm."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from hands.codegen import (
    Step,
    gen_create_tracks,
    gen_load_sample_to_pad,
    gen_midi_clip,
    gen_set_simpler_params,
    gen_set_tempo,
    hz_to_eq8_norm,
)
from hands.models import MidiNote, MidiPattern, SamplePad


def test_gen_set_tempo_label_contains_bpm() -> None:
    step = gen_set_tempo(140.0)
    assert "140" in step.label


def test_gen_set_tempo_code_sets_song_tempo() -> None:
    step = gen_set_tempo(140.0)
    assert "song.tempo" in step.code
    assert "140.0" in step.code


def test_hz_to_eq8_norm_low_bound() -> None:
    assert hz_to_eq8_norm(20.0) == pytest.approx(0.0)


def test_hz_to_eq8_norm_high_bound() -> None:
    assert hz_to_eq8_norm(20000.0) == pytest.approx(1.0)


def test_hz_to_eq8_norm_midpoint_is_between_bounds() -> None:
    val = hz_to_eq8_norm(2000.0)
    assert 0.0 < val < 1.0


def test_gen_create_tracks_contains_create_midi_track() -> None:
    step = gen_create_tracks([("Kick", "midi"), ("Perc", "midi")])
    assert "create_midi_track" in step.code


def test_gen_create_tracks_label() -> None:
    step = gen_create_tracks([("Kick", "midi"), ("Perc", "midi")])
    assert step.label


def test_gen_midi_clip_create_clip_call() -> None:
    pattern = MidiPattern(
        name="test",
        length_beats=4.0,
        notes=(MidiNote(pitch=36, time=0.0, duration=0.25),),
    )
    step = gen_midi_clip(0, 0, pattern)
    assert "create_clip(4.0)" in step.code


def test_gen_midi_clip_midi_note_specification() -> None:
    pattern = MidiPattern(
        name="test",
        length_beats=4.0,
        notes=(MidiNote(pitch=36, time=0.0, duration=0.25),),
    )
    step = gen_midi_clip(0, 0, pattern)
    assert "MidiNoteSpecification" in step.code


def test_gen_midi_clip_note_pitch_in_code() -> None:
    pattern = MidiPattern(
        name="test",
        length_beats=4.0,
        notes=(MidiNote(pitch=60, time=0.0, duration=0.5),),
    )
    step = gen_midi_clip(0, 0, pattern)
    assert "pitch=60" in step.code


def test_gen_load_sample_to_pad_drum_pad_index() -> None:
    step = gen_load_sample_to_pad(0, 0, 36, "Kick 01")
    assert "drum_pads[36]" in step.code


def test_gen_load_sample_to_pad_sample_query_in_code() -> None:
    step = gen_load_sample_to_pad(0, 0, 36, "Kick 01")
    assert "Kick 01" in step.code


def test_gen_set_simpler_params_s_start_in_code() -> None:
    pad = SamplePad(note=36, name="x", start=10, end=90)
    step = gen_set_simpler_params(0, 0, 36, pad)
    assert "S Start" in step.code


def test_gen_set_simpler_params_s_length_in_code() -> None:
    pad = SamplePad(note=36, name="x", start=10, end=90)
    step = gen_set_simpler_params(0, 0, 36, pad)
    assert "S Length" in step.code


def test_step_is_frozen() -> None:
    step = gen_set_tempo(120.0)
    with pytest.raises(Exception):
        step.label = "changed"  # type: ignore[misc]


def test_step_note_defaults_to_none() -> None:
    step = Step(label="x", code="y")
    assert step.note is None
