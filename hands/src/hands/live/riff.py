"""A panel's riff: notes from names, chords, a sequence or a sound's preset, as (pitch, start, length, velocity).

Pure functions over a panel spec; hands.live.panel writes the notes into Live. C3 is MIDI note 60, as Live shows it.
"""

from __future__ import annotations

import math
import re
from typing import Any

from hands.live.panel_base import MAX_BEATS, Note, PanelError


_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def pitch(v: Any) -> int:
    """A MIDI note number from a number or a name. C3 is 60, as Live shows it."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = int(v)
    else:
        m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d)", str(v).strip())
        if not m:
            raise PanelError(f"cannot read the pitch {v!r}: use a MIDI number or a name like A1 or C#3 (C3 is 60)")
        n = _PITCH_CLASS[m[1].upper()] + {"#": 1, "b": -1, "": 0}[m[2]] + (int(m[3]) + 2) * 12
    if not 0 <= n <= 127:
        raise PanelError(f"the pitch {v!r} is outside MIDI's 0..127")
    return n


def riff(spec: dict) -> tuple[list[Note], float]:
    """A spec's notes as (pitch, start, length, velocity) in beats, and the riff's length.

    `notes` is one pattern ([[pitch, start, length, velocity], ...]), repeated to fill `beats`; the pattern
    is as long as `pattern_beats`, or runs to the end of the bar its last note starts in. `chords` with `rhythm` is the
    other way in (hands.live.midi).
    """
    if spec.get("chords"):
        from hands.live import midi

        try:
            chords = midi.parse_progression(str(spec["chords"]))
            beats = float(spec.get("beats") or 4 * len(chords))
            _check_beats(beats)
            notes = midi.generate_clip_notes(
                chords,
                beats=beats,
                rhythm=str(spec.get("rhythm") or "staccato-16ths"),
                base_velocity=int(spec.get("velocity") or 110),
            )
        except ValueError as exc:
            raise PanelError(str(exc)) from exc
        return [(int(p), float(s), float(d), int(v)) for p, s, d, v in notes], beats
    raw = spec.get("notes")
    if spec.get("seq") and not raw:
        raw, period = sequence(
            str(spec["seq"]),
            every=float(spec.get("every") or 1),
            gate=float(spec.get("gate") or 0.9),
            velocity=int(spec.get("velocity") or 100),
        )
        spec = {"pattern_beats": period, **spec}
    if not isinstance(raw, list) or not raw:
        raise PanelError(
            'the spec needs "seq" ("A B C D"), "notes" ([[pitch, start, length, velocity], ...], in beats) or "chords"'
        )
    pattern: list[Note] = []
    for n in raw:
        if not isinstance(n, (list, tuple)) or len(n) < 3:
            raise PanelError(f"a note is [pitch, start, length, velocity]; got {n!r}")
        start, length = float(n[1]), float(n[2])
        if start < 0 or length <= 0:
            raise PanelError(f"a note starts at 0 or later and has a length above 0; got {n!r}")
        pattern.append((pitch(n[0]), start, length, max(1, min(127, int(n[3]) if len(n) > 3 else 100))))
    last = max(s for _, s, _, _ in pattern)  # a note may ring past the bar line; its start decides the bar
    period = float(spec.get("pattern_beats") or (math.floor(last / 4 + 1e-9) + 1) * 4)
    beats = float(spec.get("beats") or period)
    _check_beats(beats)
    if period <= 0:
        raise PanelError("pattern_beats must be above 0")
    out: list[Note] = []
    k = 0
    while k * period < beats - 1e-9:
        for p, s, d, v in pattern:
            at = s + k * period
            if at < beats - 1e-9:
                out.append((p, round(at, 6), round(min(d, beats - at), 6), v))
        k += 1
    return out, beats


def sequence(
    seq: str, *, every: float = 1.0, gate: float = 0.9, velocity: int = 100, octave: int = 2
) -> tuple[list[list], float]:
    """Notes from "A B C D": one every `every` beats, sounding for `gate` of the step; "-" is a rest. A name
    without an octave takes the pitch nearest the note before it (the first one sits in `octave`), so
    "A B C D" climbs. Returns the notes and the length of one pass."""
    steps = [t for t in re.split(r"[\s,]+", seq.strip()) if t]
    if not steps or not 0 < every <= 16 or not 0 < gate <= 1 or len(steps) > 128:
        raise PanelError(
            'seq is 1 to 128 notes ("A B C D", "-" for a rest), every is beats between notes (up to 16), gate is 0..1'
        )
    notes, last = [], None
    for k, step in enumerate(steps):
        if step in "-._":
            continue
        m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d)?", step)
        if not m:
            raise PanelError(
                f"cannot read the note {step!r} in seq: use names like A, C#, Bb2 (C3 is 60), or - for a rest"
            )
        if m[3] is not None:
            n = pitch(step)
        else:
            pc = (_PITCH_CLASS[m[1].upper()] + {"#": 1, "b": -1, "": 0}[m[2]]) % 12
            near = [pc + 12 * o for o in range(11)]
            n = pc + (octave + 2) * 12 if last is None else min(near, key=lambda c: (abs(c - last), -c))
        last = n
        notes.append([n, k * every, every * gate, velocity])
    if not notes:
        raise PanelError("seq has only rests")
    return notes, len(steps) * every


# Plain words for a sound: an Operator with that wave and the knobs most worth having.
SOUNDS = {
    "saw": "Saw D",
    "sawtooth": "Saw D",
    "square": "Square D",
    "sine": "Sine",
    "triangle": "Triangle",
    "noise": "Noise White",
}
SOUND_CONTROLS = [
    {"param": "Filter Freq", "label": "Cutoff"},
    {"param": "Filter Res", "label": "Resonance"},
    {"param": "Ae Decay", "label": "Decay"},
    {"param": "Ae Release", "label": "Release"},
]
# Designed sounds: Operator with four detuned saws side by side, a slow swell and a low-pass filter.
_LAYERS = {
    "Algorithm": 10,
    "Osc-A Wave": "Saw D",
    "Osc-A Level": 1.0,
    "Osc-B On": 1,
    "Osc-B Wave": "Saw D",
    "Osc-B Level": 0.85,
    "B Fine": 14,
    "Osc-C On": 1,
    "Osc-C Wave": "Saw D",
    "Osc-C Level": 0.75,
    "C Fine": 986,
    "Osc-D On": 1,
    "Osc-D Wave": "Saw D",
    "Osc-D Level": 0.6,
    "D Coarse": 2,
    "D Fine": 8,
    "Spread": 85,
    "Filter On": 1,
    "Filter Type": "Lowpass",
    "Filter Slope": "24 dB",
    "Ae Decay": "3.5 s",
    "Ae Sustain": "80 %",
}
PRESETS = {
    "pad": {**_LAYERS, "Ae Attack": "1.4 s", "Ae Release": "2.8 s", "Filter Freq": "1.1 kHz", "Filter Res": "30 %"},
    "strings": {
        **_LAYERS,
        "Ae Attack": "350 ms",
        "Ae Release": "1.2 s",
        "Filter Freq": "2.5 kHz",
        "Filter Res": "15 %",
    },
}
PRESET_CONTROLS = [
    {"param": "Filter Freq", "label": "Cutoff"},
    {"param": "Filter Res", "label": "Resonance"},
    {"param": "Ae Attack", "label": "Attack"},
    {"param": "Ae Release", "label": "Release"},
    {"param": "Spread", "label": "Width"},
]


def expand(spec: dict, *, new: bool) -> dict:
    """A spec with `sound` ("saw") written out as instrument, params and, for a new panel, controls."""
    if not spec.get("sound"):
        return spec
    sound = str(spec["sound"]).strip().lower()
    if sound in PRESETS:  # held chords by default: a pad that plays staccato is not a pad
        out = {**spec, "params": {**PRESETS[sound], **(spec.get("params") or {})}}
        if spec.get("chords"):
            out.setdefault("rhythm", "whole")
        if new:
            out.setdefault("instrument", "Operator")
            out.setdefault("controls", PRESET_CONTROLS)
            out.setdefault("tail", 4.0)
        return out
    if sound not in SOUNDS:
        raise PanelError(
            f'no sound {sound!r}; sounds: {", ".join(sorted({*SOUNDS, *PRESETS}))}. For anything else give "instrument" and "params"'
        )
    out = {**spec, "params": {"Osc-A Wave": SOUNDS[sound], **(spec.get("params") or {})}}
    if new:
        out.setdefault("instrument", "Operator")
        out.setdefault("controls", SOUND_CONTROLS)
    return out


def _check_beats(beats: float) -> None:
    if not 1 <= beats <= MAX_BEATS:
        raise PanelError(f"a riff is 1 to {MAX_BEATS:g} beats long (it renders in real time); got {beats:g}")
