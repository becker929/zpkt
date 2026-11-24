"""High-level MIDI chord progression and rhythm generation for arrangement clips."""

from __future__ import annotations

import re
from typing import Any

from hands.live.transport import McpTransport

NOTE_NAMES = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "F": 5,
    "E#": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}

CHORD_INTERVALS = {
    "maj": [0, 4, 7],
    "m": [0, 3, 7],
    "min": [0, 3, 7],
    "5": [0, 7],
    "7": [0, 4, 7, 10],
    "dom7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10],
    "min7": [0, 3, 7, 10],
    "9": [0, 4, 7, 10, 14],
    "dom9": [0, 4, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14],
    "m9": [0, 3, 7, 10, 14],
    "min9": [0, 3, 7, 10, 14],
    "add9": [0, 4, 7, 14],
    "dim": [0, 3, 6],
    "dim7": [0, 3, 6, 9],
    "m7b5": [0, 3, 6, 10],
    "aug": [0, 4, 8],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
    "7alt": [0, 4, 10, 13, 15],
    "alt": [0, 4, 10, 13, 15],
}

RHYTHMS = {
    "staccato-16ths": [
        (0.0, 0.22, 1.0),
        (0.75, 0.22, 0.88),
        (1.5, 0.22, 0.95),
        (2.25, 0.22, 0.85),
        (3.0, 0.22, 0.98),
        (3.5, 0.22, 0.92),
    ],
    "staccato-turn": [
        (0.0, 0.20, 1.0),
        (0.75, 0.20, 0.88),
        (1.5, 0.20, 0.95),
        (2.0, 0.20, 0.82),
        (2.5, 0.20, 0.87),
        (3.0, 0.20, 0.98),
        (3.5, 0.20, 0.92),
        (3.75, 0.20, 0.94),
    ],
    "quarters": [
        (0.0, 0.75, 1.0),
        (1.0, 0.75, 0.88),
        (2.0, 0.75, 0.95),
        (3.0, 0.75, 0.88),
    ],
    "eighths": [
        (0.0, 0.35, 1.0),
        (0.5, 0.35, 0.85),
        (1.0, 0.35, 0.95),
        (1.5, 0.35, 0.85),
        (2.0, 0.35, 0.98),
        (2.5, 0.35, 0.85),
        (3.0, 0.35, 0.95),
        (3.5, 0.35, 0.85),
    ],
    "offbeats": [
        (0.5, 0.35, 1.0),
        (1.5, 0.35, 0.95),
        (2.5, 0.35, 1.0),
        (3.5, 0.35, 0.95),
    ],
    "whole": [
        (0.0, 3.75, 1.0),
    ],
}


def parse_chord(spec: str, bass_octave: int = 2, upper_octave: int = 3) -> list[int]:
    """Parse a chord symbol (e.g. 'Dm9', 'Bbmaj9', 'Gm9', 'C9') or explicit MIDI numbers ('38,53,57,60,64')."""
    spec = spec.strip()
    if not spec:
        return []

    # Check explicit notes: "38,53,57,60,64" or "38 53 57"
    if re.fullmatch(r"[\d,\s]+", spec):
        parts = [int(p.strip()) for p in re.split(r"[,\s]+", spec) if p.strip()]
        return sorted(parts)

    # A slash chord ("D#m/A"): the chord, over another bass note.
    over = re.fullmatch(r"(.+)/([A-Ga-g][#b]?)", spec)
    if over:
        notes = parse_chord(over.group(1), bass_octave, upper_octave)
        bass = (bass_octave + 1) * 12 + NOTE_NAMES[over.group(2).upper()]
        while bass > 45:
            bass -= 12
        while bass < 30:
            bass += 12
        return sorted({bass, *notes[1:]})

    m = re.match(r"^([A-Ga-g][#b]?)(.*)$", spec)
    if not m:
        raise ValueError(f"cannot read the chord {spec!r}: write chords like Dm9, Bbmaj7 or D#m/A, separated by commas")

    root_name = m.group(1).upper()
    quality = m.group(2).strip()

    if root_name not in NOTE_NAMES:
        raise ValueError(f"Unknown root note name: {root_name!r}")

    root_pitch_class = NOTE_NAMES[root_name]
    bass_pitch = (bass_octave + 1) * 12 + root_pitch_class
    # Keep bass note within solid bass range (30..45: F#1 to A2)
    while bass_pitch > 45:
        bass_pitch -= 12
    while bass_pitch < 30:
        bass_pitch += 12

    upper_root = (upper_octave + 1) * 12 + root_pitch_class

    # Match quality
    q_key = quality.lower()
    if not q_key:
        q_key = "maj"
    elif q_key not in CHORD_INTERVALS:
        if q_key in ("m", "min"):
            q_key = "m"
        elif q_key in ("m9", "min9"):
            q_key = "m9"
        elif q_key in ("m7", "min7"):
            q_key = "m7"
        elif q_key in ("m7b5", "ø"):
            q_key = "m7b5"
        elif q_key in ("o", "dim7"):
            q_key = "dim7"
        else:
            raise ValueError(
                f"cannot read the chord {spec!r}: {quality!r} is not a chord kind. Kinds: {', '.join(sorted(CHORD_INTERVALS))} "
                '(nothing for major). Separate chords with commas ("Dm9,Bbmaj7,D#m/A"), or give "notes" instead'
            )

    intervals = CHORD_INTERVALS[q_key]

    # For 9th and 7th chords: root in bass, upper tones voiced in mid-high register
    if len(intervals) >= 4 and intervals[-1] >= 14:  # 9th chord
        upper_notes = [upper_root + iv for iv in intervals[1:]]
        # Keep upper notes in nice voicing register (48..76)
        notes = [bass_pitch, *upper_notes]
    elif len(intervals) >= 4:  # 7th chord
        upper_notes = [upper_root + iv for iv in intervals[1:]]
        notes = [bass_pitch, *upper_notes]
    else:  # triad or power chord
        upper_notes = [upper_root + iv for iv in intervals]
        notes = [bass_pitch, *upper_notes]

    return sorted(set(notes))


def parse_progression(prog_str: str) -> list[list[int]]:
    """Parse comma, semicolon, pipe, or slash separated chord progression."""
    bare = r"[A-Ga-g][#b]?"  # after a slash, a bare note is a bass note: D#m/A
    if ";" in prog_str:
        chunks = [c.strip() for c in prog_str.split(";") if c.strip()]
    elif "," in prog_str and not re.fullmatch(r"[\d,\s/|]+", prog_str):
        chunks = [c.strip() for c in prog_str.split(",") if c.strip()]
    elif (
        "/" in prog_str
        and not re.search(r"\d+/\d+", prog_str)
        and not all(re.fullmatch(bare, c.strip()) for c in prog_str.split("/")[1:])
    ):
        chunks = [c.strip() for c in prog_str.split("/") if c.strip()]
    elif "|" in prog_str:
        chunks = [c.strip() for c in prog_str.split("|") if c.strip()]
    elif "-" in prog_str and not prog_str.startswith("-") and "/" not in prog_str:
        chunks = [c.strip() for c in prog_str.split("-") if c.strip()]
    else:
        chunks = [c.strip() for c in prog_str.split(",") if c.strip()]

    return [parse_chord(c) for c in chunks]


def parse_rhythm(rhythm: str) -> list[tuple[float, float, float]]:
    """Get rhythm pattern as list of (offset, duration, vel_ratio)."""
    r_key = rhythm.strip().lower()
    if r_key in RHYTHMS:
        return RHYTHMS[r_key]

    if re.match(r"^[\d.,\s]+$", rhythm):
        offsets = [float(x.strip()) for x in rhythm.split(",") if x.strip()]
        return [(off, 0.22, 1.0) for off in offsets]

    raise ValueError(f"Unknown rhythm preset or format: {rhythm!r}")


def generate_clip_notes(
    chords: list[list[int]],
    beats: float = 32.0,
    rhythm: str = "staccato-16ths",
    base_velocity: int = 110,
    duration: float | None = None,
    turnaround: bool = True,
) -> list[tuple[int, float, float, int]]:
    """Generate notes list [(pitch, start_time, duration, velocity)] for an arrangement clip."""
    if not chords:
        return []

    rhythm_std = parse_rhythm(rhythm)
    rhythm_turn = parse_rhythm("staccato-turn") if turnaround and rhythm == "staccato-16ths" else rhythm_std

    num_bars = int(beats / 4.0)
    notes: list[tuple[int, float, float, int]] = []

    for bar_idx in range(num_bars):
        bar_start = bar_idx * 4.0
        chord = chords[bar_idx % len(chords)]

        is_turn = turnaround and ((bar_idx + 1) % 4 == 0 or bar_idx == num_bars - 1)
        pattern = rhythm_turn if is_turn else rhythm_std

        for offset, dur, vel_scale in pattern:
            note_start = bar_start + offset
            note_dur = duration if duration is not None else dur
            note_vel = max(1, min(127, round(base_velocity * vel_scale)))

            for pitch in chord:
                notes.append((pitch, note_start, note_dur, note_vel))

    return notes


def create_arrangement_clip(
    client: McpTransport,
    track: str | int,
    start: float,
    length: float,
    name: str,
    notes: list[tuple[int, float, float, int]],
) -> dict[str, Any]:
    """Create an arrangement clip and populate it with notes in a single LOM execution."""
    t_expr = (
        f"song.tracks[{track}]" if isinstance(track, int) else f"next(x for x in song.tracks if x.name == {track!r})"
    )

    code = f"""
_t = {t_expr}
_c = _t.create_midi_clip({float(start)!r}, {float(length)!r})
_c.name = {name!r}
_notes = tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v)
               for p, s, d, v in {notes!r})
_c.add_new_notes(_notes)
result = {{"track": _t.name, "clip": _c.name, "start": _c.start_time, "length": _c.length, "notes_count": len(_notes)}}
"""
    return client.run(code)
