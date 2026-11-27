"""A step pattern as MIDI notes in an Arrangement clip, and painting that clip across bars.

    steps.midi_tracks(live)                          # [{"name", "index", "color", "drum_rack"}]
    steps.sounds(live, "Drums")                      # a Drum Rack's filled pads: [{"pitch": 36, "name": "Kick"}, ...]
    steps.read(live, "Drums", 1, 2)                  # the pattern in bars 1-2, the clip that holds it, off_grid
    steps.write(live, "Drums", 1, pattern)           # the span holds exactly this pattern; what was there before
    steps.toggle(live, "Drums", 1, 2, 16, 36, 4)     # flip one step: {"on": True, "velocity": 100, ...}
    steps.set_step(live, "Drums", 1, 2, 16, 36, 4, velocity=64)
    steps.paint(live, "Drums", 1, 2, [3, 5, 7])      # stamp the clip of bars 1-2 onto bars 3, 5 and 7
    steps.erase(live, "Drums", [5], 2)               # delete the clip that covers bars 5-6 exactly
    steps.painted(live, "Drums", 2, 64)              # which bars start a 2-bar clip, with a hash of its notes

The grid (pure Python, no Live): a pattern is {"bars": 1|2|4, "steps_per_bar": 8|12|16|24|32, "rows": [{"pitch",
"name", "steps": [0 or a velocity 1..127 per step]}], "length": a note's length in steps, "swing": 0..0.75}.
`to_notes` turns it into (pitch, start, duration, velocity) in beats from the pattern's start, `from_notes` reads
notes back onto the grid and counts what the grid cannot show in `off_grid`.

Arrangement view only: nothing here makes, launches or reads a Session clip or a scene.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NotRequired, TypedDict

from zpkt.live.inlive import steps as inside

BARS = (1, 2, 4)
STEPS_PER_BAR = (8, 12, 16, 24, 32)
MIN_LENGTH = 0.25  # steps: the shortest note
MAX_SWING = 0.75  # of a step
ON_GRID = 0.25  # steps: a note this near a step is on it; further off, the grid does not show it
_NEAR = 1e-6  # steps: rounding room for the comparisons above
_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

Note = tuple[int, float, float, int]  # pitch, start in beats from the pattern's start, duration in beats, velocity


class Row(TypedDict):
    """One sound's steps: 0 for an empty step, else the note's velocity. `lengths` is there only when a note is not
    as long as the pattern's `length`: per step, its own length in steps, 0 where the pattern's holds."""

    pitch: int
    name: str
    steps: list[int]
    lengths: NotRequired[list[float]]


class Pattern(TypedDict):
    """A step pattern. `off_grid` is set by `from_notes`: how many notes the grid does not show."""

    bars: int
    steps_per_bar: int
    rows: list[Row]
    length: float
    swing: NotRequired[float]
    off_grid: NotRequired[int]


def note_name(pitch: int) -> str:
    """A pitch as Live names it: 60 is C3, 36 is C1."""
    return f"{_PITCH_NAMES[pitch % 12]}{pitch // 12 - 2}"


def content_hash(notes: Iterable[Sequence[float]]) -> str:
    """Eight hex digits for a list of notes, the same that `painted` gives for a clip holding them."""
    return inside.content_hash(notes)


def _int(value: object, what: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{what} is {lo} to {hi}, not {value!r}")
    return value


def _number(value: object, what: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f"{what} is {lo:g} to {hi:g}, not {value!r}")
    return float(value)


def check_grid(bars: object, steps_per_bar: object) -> int:
    """The number of steps in a grid of `bars` bars; ValueError for a size the sequencer does not have."""
    if isinstance(bars, bool) or not isinstance(bars, int) or bars not in BARS:
        raise ValueError(f"a pattern is 1, 2 or 4 bars long, not {bars!r}")
    if isinstance(steps_per_bar, bool) or not isinstance(steps_per_bar, int) or steps_per_bar not in STEPS_PER_BAR:
        raise ValueError(f"a bar has 8, 12, 16, 24 or 32 steps, not {steps_per_bar!r}")
    return bars * steps_per_bar


def check_swing(swing: object) -> float:
    return _number(swing, "swing (of a step)", 0.0, MAX_SWING)


def check_length(length: object, total: int) -> float:
    return _number(length, "a note's length in steps", MIN_LENGTH, total)


def check_velocity(velocity: object) -> int:
    return _int(velocity, "a velocity", 1, 127)


def check_pitch(pitch: object) -> int:
    return _int(pitch, "a pitch", 0, 127)


def check_bar(bar: object) -> int:
    """A bar of the song, counted from 1."""
    return _int(bar, "a bar (counted from 1)", 1, 100_000)


def check(pattern: Mapping[str, Any]) -> Pattern:
    """The pattern with its defaults filled in (length 1.0, swing 0.0, a row's name from its pitch); ValueError
    saying what is wrong otherwise."""
    total = check_grid(pattern.get("bars"), pattern.get("steps_per_bar", 16))
    length = check_length(pattern.get("length", 1.0), total)
    rows: list[Row] = []
    seen: set[int] = set()
    for given in pattern.get("rows", ()):
        pitch = check_pitch(given.get("pitch"))
        if pitch in seen:
            raise ValueError(f"two rows have the pitch {pitch}")
        seen.add(pitch)
        cells = list(given.get("steps", ()))
        if len(cells) != total:
            raise ValueError(f"the row of pitch {pitch} has {len(cells)} steps; the pattern has {total}")
        if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 127 for v in cells):
            raise ValueError(f"the row of pitch {pitch}: a step is 0 (empty) or a velocity 1 to 127")
        row: Row = {"pitch": pitch, "name": str(given.get("name") or note_name(pitch)), "steps": cells}
        if given.get("lengths") is not None:
            own = list(given["lengths"])
            if len(own) != total:
                raise ValueError(f"the row of pitch {pitch} has {len(own)} lengths; the pattern has {total} steps")
            row["lengths"] = [check_length(v, total) if v else 0.0 for v in own]
        rows.append(row)
    return {
        "bars": int(pattern["bars"]),
        "steps_per_bar": int(pattern.get("steps_per_bar", 16)),
        "rows": rows,
        "length": length,
        "swing": check_swing(pattern.get("swing", 0.0)),
    }


def blank(
    bars: int = 1,
    steps_per_bar: int = 16,
    pitches: Sequence[int] = (),
    names: Mapping[int, str] | None = None,
    length: float = 1.0,
    swing: float = 0.0,
) -> Pattern:
    """An empty pattern with a row for each of `pitches`."""
    total = check_grid(bars, steps_per_bar)
    rows = [{"pitch": p, "name": (names or {}).get(p) or note_name(p), "steps": [0] * total} for p in pitches]
    return check({"bars": bars, "steps_per_bar": steps_per_bar, "rows": rows, "length": length, "swing": swing})


def late(step: int, swing: float) -> float:
    """How far after its place on the grid a step starts, in steps: every second step (the 2nd, the 4th: every
    second 16th when a bar has 16 steps) is delayed by `swing` of a step."""
    return swing if step % 2 else 0.0


def sounding(length: float, step: int, total: int, swing: float = 0.0) -> float:
    """How long the note on `step` sounds, in steps, when it is `length` steps long: a delayed step still ends
    where it would have, but sounds for a quarter step at least, and no note runs past the pattern's end."""
    delay = late(step, swing)
    return min(max(length - delay, MIN_LENGTH), total - step - delay)


def _notes(pattern: Pattern, step_size: float) -> list[tuple[int, float, float, int]]:
    """The pattern's notes with times in units of which one step is `step_size`, in order of start, then pitch."""
    total = pattern["bars"] * pattern["steps_per_bar"]
    swing = pattern.get("swing", 0.0)
    out = []
    for row in pattern["rows"]:
        own = row.get("lengths")
        for step, velocity in enumerate(row["steps"]):
            if velocity:
                length = own[step] if own and own[step] else pattern["length"]
                start = (step + late(step, swing)) * step_size
                out.append((row["pitch"], start, sounding(length, step, total, swing) * step_size, velocity))
    return sorted(out, key=lambda n: (n[1], n[0]))


def to_notes(pattern: Mapping[str, Any], beats_per_bar: float = 4.0) -> list[Note]:
    """The pattern's notes as (pitch, start, duration, velocity), in beats from the pattern's start, in order of
    start, then pitch. `beats_per_bar` is the bar in quarter notes: 4.0 in 4/4, 3.0 in 3/4. Swing is applied here."""
    checked = check(pattern)
    step_size = beats_per_bar / checked["steps_per_bar"]
    return [(p, round(s, 6), round(d, 6), v) for p, s, d, v in _notes(checked, step_size)]


def _step_of(at: float, total: int, swing: float) -> int | None:
    """The step a note starting `at` (in steps) is on, or None when it is more than a quarter step from every one."""
    near = int(at // 1)
    best = min(
        (k for k in (near - 1, near, near + 1) if 0 <= k < total),
        key=lambda k: abs(at - k - late(k, swing)),
        default=None,
    )
    if best is None or abs(at - best - late(best, swing)) > ON_GRID + _NEAR:
        return None
    return best


def from_notes(
    notes: Iterable[Sequence[float]],
    bars: int,
    steps_per_bar: int,
    beats_per_bar: float,
    pitches: Sequence[int] | None = None,
    *,
    names: Mapping[int, str] | None = None,
    swing: float = 0.0,
) -> Pattern:
    """The pattern that notes (pitch, start, duration, velocity; beats from the pattern's start) make on a grid.

    A note snaps to the nearest step. The grid cannot show a note more than a quarter step from every step, a
    second note on a step that is taken, or (when `pitches` is given) a note of another pitch: those are counted in
    the pattern's `off_grid`, so a page can say the clip holds more than the grid shows. Rows are `pitches` in that
    order, or every pitch found, lowest first; a row is named from `names`, else by its note ("C1"). `length` is
    the length most notes have (1.0 with no notes); a note of another length gets its own in its row's `lengths`.

    Swing is not guessed back: with the default 0.0, a note written with more than a quarter step of swing is off
    the grid. Give the `swing` the notes were written with and each delayed step is read where it was put.
    """
    total = check_grid(bars, steps_per_bar)
    swing = check_swing(swing)
    step_size = beats_per_bar / steps_per_bar
    wanted = None if pitches is None else list(dict.fromkeys(check_pitch(p) for p in pitches))
    cells: dict[int, dict[int, tuple[int, float]]] = {p: {} for p in wanted or ()}
    off_grid = 0
    for pitch, start, duration, velocity in sorted(notes, key=lambda n: (n[1], n[0])):
        step = _step_of(start / step_size, total, swing)
        row = cells.get(int(pitch))
        if step is None or (wanted is not None and row is None) or (row is not None and step in row):
            off_grid += 1
            continue
        cells.setdefault(int(pitch), {})[step] = (max(1, min(127, round(velocity))), duration / step_size)

    asked = Counter(
        round(sounds_for + late(step, swing), 4) for row in cells.values() for step, (_, sounds_for) in row.items()
    )
    most = max(asked.values(), default=0)
    length = max(MIN_LENGTH, min(float(total), min((v for v, n in asked.items() if n == most), default=1.0)))

    rows: list[Row] = []
    for pitch in wanted if wanted is not None else sorted(cells):
        row = cells[pitch]
        made: Row = {
            "pitch": pitch,
            "name": (names or {}).get(pitch) or note_name(pitch),
            "steps": [row[k][0] if k in row else 0 for k in range(total)],
        }
        own = [0.0] * total
        for step, (_, sounds_for) in row.items():
            if abs(sounding(length, step, total, swing) - sounds_for) > 1e-4:
                own[step] = max(MIN_LENGTH, min(float(total), round(sounds_for + late(step, swing), 4)))
        if any(own):
            made["lengths"] = own
        rows.append(made)
    return {
        "bars": bars,
        "steps_per_bar": steps_per_bar,
        "rows": rows,
        "length": length,
        "swing": swing,
        "off_grid": off_grid,
    }
