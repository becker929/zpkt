"""Tests for hands.live.midi chord parsing, rhythm generation, and clip note synthesis."""

import pytest
from hands.live import midi


def test_parse_chord_explicit_notes():
    assert midi.parse_chord("38,53,57,60,64") == [38, 53, 57, 60, 64]
    assert midi.parse_chord("60 64 67") == [60, 64, 67]


def test_parse_chord_symbols():
    dm9 = midi.parse_chord("Dm9")
    # Bass D2 = 38, upper D3=48 -> F3=53, A3=57, C4=60, E4=64
    assert dm9[0] == 38
    assert 53 in dm9
    assert 60 in dm9
    assert 64 in dm9

    c9 = midi.parse_chord("C9")
    assert c9[0] == 36

    f_min = midi.parse_chord("Fm")
    assert f_min[0] == 41  # F2


def test_parse_progression():
    prog = midi.parse_progression("Dm9, Bbmaj9, Gm9, C9")
    assert len(prog) == 4
    assert prog[0][0] == 38  # D
    assert prog[1][0] == 34  # Bb
    assert prog[2][0] == 43  # G
    assert prog[3][0] == 36  # C


def test_parse_rhythm():
    r = midi.parse_rhythm("staccato-16ths")
    assert len(r) == 6
    assert r[0][0] == 0.0

    r_custom = midi.parse_rhythm("0, 1.0, 2.0")
    assert len(r_custom) == 3
    assert r_custom[1][0] == 1.0


def test_generate_clip_notes():
    chords = [[38, 53, 57, 60, 64]]  # 5-note chord
    notes = midi.generate_clip_notes(chords, beats=8.0, rhythm="staccato-16ths", turnaround=False)
    # 2 bars * 6 hits * 5 notes = 60 notes
    assert len(notes) == 60
    assert all(len(n) == 4 for n in notes)
    # verify pitch, start, dur, vel
    p, s, d, v = notes[0]
    assert p == 38
    assert s == 0.0
    assert d > 0
    assert 1 <= v <= 127
