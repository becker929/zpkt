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
    steps.restore(live, "Drums", 5, 2, notes)        # the span holds exactly these notes again (None: no clip); "was"
    steps.loop(live, 17, 2)                          # loop bars 17-18; what the loop was (steps.loop_put puts it back)
    steps.kits(live)                                 # the Drum Rack presets Live's browser offers, by name
    steps.new_drum_track(live, "Drums", "909 Core Kit")   # a MIDI track before the monitor tracks, with that kit

The grid (pure Python, no Live): a pattern is {"bars": 1|2|4, "steps_per_bar": 8|12|16|24|32, "rows": [{"pitch",
"name", "steps": [0 or a velocity 1..127 per step]}], "length": a note's length in steps, "swing": 0..0.75}.
`to_notes` turns it into (pitch, start, duration, velocity) in beats from the pattern's start, `from_notes` reads
notes back onto the grid and counts what the grid cannot show in `off_grid`.

In Live: every function takes the Live connection (the app hands it in) and a track by name (as everywhere in
zpkt.live: zpkt.live.inlive.tracks) or by index. Bars count from 1 and are as long as the song's signature says.
Each call to Live is one line over zpkt.live.inlive.steps, which travels above it, and never reads back what it
wrote (ableton-guide rule 1): `write` reads the span in a second short call, `paint` sends 16 copies to a call.

A span of bars is in one of three states. One MIDI clip covers exactly it: that clip's notes are the pattern. No
clip touches it: it is free, and a write or a tap makes a clip of that length. Anything else (a longer or shorter
clip reaching in, an audio clip, a clip that loops inside itself) is in the way: nothing is changed, and the answer
names those clips. A clip is never cut, shortened or moved here.

For an undo in the app, `write`, `toggle` and `set_step` return `before`, the notes the span held (as `to_notes`
gives them); `paint` returns the clips it replaced and `erase` the clips it deleted, each with its name and notes.
`restore` puts a span back from those: its notes into one exact clip, or no clip at all, and returns what the span
held, so the same call takes itself back.

Arrangement view only: nothing here makes, launches or reads a Session clip or a scene.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, NotRequired, TypedDict

from zpkt.live.agent import with_prelude
from zpkt.live.inlive import steps as inside
from zpkt.live.inlive import with_source
from zpkt.live.transport import McpTransport

BARS = (1, 2, 4)
STEPS_PER_BAR = (8, 12, 16, 24, 32)
MIN_LENGTH = 0.25  # steps: the shortest note
MAX_SWING = 0.75  # of a step
ON_GRID = 0.25  # steps: a note this near a step is on it; further off, the grid does not show it
_NEAR = 1e-6  # steps: rounding room for the comparisons above
_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAX_SOUNDS = 64  # pads `sounds` gives at most
MAX_TARGETS = 64  # bars one `paint` or `erase` takes
PER_CALL = 16  # copies one call to Live makes: each call stays short (ableton-guide rule 6)
# Seconds Live waits between two copies in a call. The ableton guide asks for a pause between
# duplicate_clip_to_arrangement calls (0.1 s in its example) and for at most half a second of sleep in a call
# (rule 7); sixteen copies cannot have both, so the pause is the longest that keeps a full call under the half
# second. GUESS: it is long enough (zpkt.live.arrange.fx copies back to back with none).
COPY_PAUSE_S = 0.03
MAX_PAINTED = 256  # clips `painted` reports at most
MAX_KITS = 60  # kits `kits` gives at most
MONITOR_PREFIX = "mon "  # the mix desk's monitor tracks: a new drum track goes in front of the first of them
SETTLE_S = 0.3  # after a track is made or a kit loaded, before the set is read again (ableton-guide rule 3)
POLLS = 12  # times the set is read after that, SETTLE_S apart, before the step counts as failed

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


# --------------------------------------------------------------------------- Live: tracks and sounds

TrackRef = str | int  # a track by name, as everywhere in zpkt.live (zpkt.live.inlive.tracks), or by index


class MidiTrack(TypedDict):
    name: str
    index: int  # among the set's tracks
    color: str  # "#rrggbb", or "" when Live gave none
    drum_rack: bool  # its first instrument is a Drum Rack


class Sound(TypedDict):
    pitch: int
    name: str


def _track(track: TrackRef) -> str:
    """The Live expression for a track: by index among the tracks, or by name (zpkt.live.inlive.tracks' rule)."""
    if isinstance(track, bool) or (isinstance(track, int) and track < 0):
        raise ValueError(f"a track is a name or an index from 0, not {track!r}")
    return f"song.tracks[{track}]" if isinstance(track, int) else f"find_track(song, {track!r})"


def _run(live: McpTransport, track: TrackRef, call: str, **args: Any) -> Any:
    """One call to Live: `call`, an expression over the track `_t` and the arguments `_a`, with zpkt.live.inlive's
    steps and tracks above it. The answer travels as JSON, so nested lists arrive whole."""
    code = f"import json\n_t = {_track(track)}\n_a = json.loads({json.dumps(args)!r})\nresult = json.dumps({call})"
    return json.loads(live.run(with_source(code, "tracks", "steps")))


def _colour(value: object) -> str:
    """Live's colour (0xRRGGBB as a number) as "#rrggbb"; "" when Live gave none."""
    return f"#{value & 0xFFFFFF:06x}" if isinstance(value, int) and value else ""


def midi_tracks(live: McpTransport) -> list[MidiTrack]:
    """The set's MIDI tracks, in the set's order. One call."""
    found = json.loads(live.run(with_source("import json\nresult = json.dumps(midi_track_list(song))", "steps")))
    return [
        {
            "name": str(t["name"]),
            "index": int(t["index"]),
            "color": _colour(t["color"]),
            "drum_rack": bool(t["drum_rack"]),
        }
        for t in found
    ]


def sounds(live: McpTransport, track: TrackRef) -> list[Sound]:
    """A Drum Rack track's pads that hold something, lowest first (64 at most); an empty list for any other
    instrument, where a page offers pitches itself. One call."""
    found = _run(live, track, "pad_sounds(_t, **_a)", cap=MAX_SOUNDS)
    return [{"pitch": int(s["pitch"]), "name": str(s["name"])} for s in found]


# --------------------------------------------------------------------------- Live: the pattern clip

_NOTE_SPEC = "Live.Clip.MidiNoteSpecification"


class ClipInfo(TypedDict):
    """An Arrangement clip: its name, and where it starts and ends in beats."""

    name: str
    start: float
    end: float


class Read(TypedDict):
    """What a span of bars holds. `clip` is the MIDI clip that covers exactly the span, None when there is none;
    `blocked` names the clips in the way of writing the span (a clip of another length, an audio clip, a clip that
    loops inside itself); `off_grid` is the pattern's: the notes the grid does not show; `hash` is the notes'
    content hash, the one `painted` gives for a clip holding the same notes."""

    pattern: Pattern
    clip: ClipInfo | None
    off_grid: int
    blocked: list[ClipInfo]
    beats_per_bar: float
    hash: str


class Blocked(TypedDict):
    """Nothing was changed: clips are in the way (they are never cut)."""

    error: str
    blocked: list[ClipInfo]


class Written(Read):
    """What `read` gives after the write, with the notes the span held before it and whether the clip is new."""

    before: list[Note]
    created: bool


def _as_notes(found: Iterable[Sequence[float]]) -> list[Note]:
    return [(int(p), float(s), float(d), int(v)) for p, s, d, v in found]


def _as_read(
    found: Mapping[str, Any],
    bars: int,
    steps_per_bar: int,
    pitches: Sequence[int] | None,
    swing: float,
    names: Mapping[int, str] | None,
) -> Read:
    notes = _as_notes(found["notes"])
    named = {**{int(pitch): str(name) for pitch, name in found["names"].items()}, **(names or {})}
    grid = from_notes(notes, bars, steps_per_bar, float(found["beats_per_bar"]), pitches, names=named, swing=swing)
    return {
        "pattern": grid,
        "clip": found["clip"],
        "off_grid": grid.get("off_grid", 0),
        "blocked": list(found["blocked"]),
        "beats_per_bar": float(found["beats_per_bar"]),
        "hash": content_hash(notes),
    }


def read(
    live: McpTransport,
    track: TrackRef,
    bar: int,
    bars: int,
    steps_per_bar: int = 16,
    pitches: Sequence[int] | None = None,
    *,
    swing: float = 0.0,
    names: Mapping[int, str] | None = None,
) -> Read:
    """The pattern in the Arrangement on `track` over `bars` bars from `bar` (counted from 1; a bar is as long as
    the song's signature says). The notes of every MIDI clip in the span are read, whether or not one clip covers
    exactly it. Rows are named from `names`, else from the Drum Rack's pads, else by note. `swing` is the swing the
    notes were written with, if the caller knows it (`from_notes`). One call."""
    check_grid(bars, steps_per_bar)
    found = _run(live, track, "pattern_look(song, _t, **_a)", bar=check_bar(bar), bars=bars)
    return _as_read(found, bars, steps_per_bar, pitches, check_swing(swing), names)


def write(
    live: McpTransport, track: TrackRef, bar: int, pattern: Mapping[str, Any], name: str | None = None
) -> Written | Blocked:
    """Make the span of the pattern's bars from `bar` hold exactly this pattern. A MIDI clip that covers exactly the
    span gets its notes replaced; a free span gets a new clip of that length (its loop settings stay as Live makes
    them); either is named `name` if one is given. When other clips reach into the span, nothing is changed and
    the answer is {"error", "blocked": [{"name", "start", "end"}]}: clips are never cut.

    The write is one call. What the span holds afterwards is read in a second short call (nothing is read in the
    call that wrote it: ableton-guide rule 1) and returned as `read` gives it, with `before`, the notes the span
    held, and `created`, whether the clip is new: enough to undo the write."""
    checked = check(pattern)
    notes = _notes(checked, 1.0 / checked["steps_per_bar"])  # times in bars: Live knows how long its bar is
    did = _run(
        live,
        track,
        f"pattern_put(song, _t, {_NOTE_SPEC}, **_a)",
        bar=check_bar(bar),
        bars=checked["bars"],
        notes=[list(n) for n in notes],
        name=name,
    )
    if "error" in did:
        return {"error": str(did["error"]), "blocked": list(did["blocked"])}
    after = read(
        live,
        track,
        bar,
        checked["bars"],
        checked["steps_per_bar"],
        [r["pitch"] for r in checked["rows"]],
        swing=checked.get("swing", 0.0),
        names={r["pitch"]: r["name"] for r in checked["rows"]},
    )
    return {**after, "before": _as_notes(did["before"]), "created": bool(did["created"])}


class Toggled(TypedDict):
    """One step after a flip: whether it holds a note now and its velocity (0 when it does not), the notes the
    span held before, and whether the flip made the clip."""

    on: bool
    velocity: int
    before: list[Note]
    created: bool


class Changed(TypedDict):
    """One step's note after `set_step`: its velocity, its length in steps, and the notes the span held before."""

    on: bool
    velocity: int
    length: float
    before: list[Note]


class NoNote(TypedDict):
    """Nothing was changed: the step holds no note."""

    error: str
    before: list[Note]


def _step_window(step: int, steps_per_bar: int, swing: float) -> dict[str, float]:
    """Where a step's note starts and the stretch in which a note counts as on that step (a quarter step either
    side, as `from_notes` reads it), in bars from the pattern's start."""
    at = step + late(step, swing)
    return {"at": at / steps_per_bar, "lo": (at - ON_GRID) / steps_per_bar, "hi": (at + ON_GRID) / steps_per_bar}


def toggle(
    live: McpTransport,
    track: TrackRef,
    bar: int,
    bars: int,
    steps_per_bar: int,
    pitch: int,
    step: int,
    velocity: int = 100,
    length: float = 1.0,
    *,
    swing: float = 0.0,
    name: str | None = None,
) -> Toggled | Blocked:
    """Flip ONE step (counted from 0) of the pattern in `bars` bars from `bar`: the fast path for a tap or a pad.
    When a note of `pitch` starts on the step it is removed; otherwise one is added with this velocity and length
    (in steps). A free span gets its clip first (named `name` if given). `swing` is the pattern's, so that a
    delayed step is found and put where `write` puts it. One call; clips in the way give {"error", "blocked"}."""
    total = check_grid(bars, steps_per_bar)
    step = _int(step, "a step (counted from 0)", 0, total - 1)
    swing = check_swing(swing)
    did = _run(
        live,
        track,
        f"step_flip(song, _t, {_NOTE_SPEC}, **_a)",
        bar=check_bar(bar),
        bars=bars,
        pitch=check_pitch(pitch),
        **_step_window(step, steps_per_bar, swing),
        duration=sounding(check_length(length, total), step, total, swing) / steps_per_bar,
        velocity=check_velocity(velocity),
        name=name,
    )
    if "error" in did:
        return {"error": str(did["error"]), "blocked": list(did["blocked"])}
    return {
        "on": bool(did["on"]),
        "velocity": int(did["velocity"]),
        "before": _as_notes(did["before"]),
        "created": bool(did["created"]),
    }


def set_step(
    live: McpTransport,
    track: TrackRef,
    bar: int,
    bars: int,
    steps_per_bar: int,
    pitch: int,
    step: int,
    velocity: int | None = None,
    length: float | None = None,
    *,
    swing: float = 0.0,
) -> Changed | NoNote | Blocked:
    """Change the velocity, the length (in steps) or both of the note of `pitch` on a step (counted from 0); what
    is None stays. One call. {"error": "no note on that step", "before"} when the step is empty."""
    total = check_grid(bars, steps_per_bar)
    step = _int(step, "a step (counted from 0)", 0, total - 1)
    swing = check_swing(swing)
    if velocity is None and length is None:
        raise ValueError("set_step changes a velocity, a length or both: give one")
    window = _step_window(step, steps_per_bar, swing)
    did = _run(
        live,
        track,
        f"step_change(song, _t, {_NOTE_SPEC}, **_a)",
        bar=check_bar(bar),
        bars=bars,
        pitch=check_pitch(pitch),
        lo=window["lo"],
        hi=window["hi"],
        velocity=None if velocity is None else check_velocity(velocity),
        duration=None if length is None else sounding(check_length(length, total), step, total, swing) / steps_per_bar,
    )
    if "blocked" in did:
        return {"error": str(did["error"]), "blocked": list(did["blocked"])}
    if "error" in did:
        return {"error": str(did["error"]), "before": _as_notes(did["before"])}
    in_steps = float(did["duration"]) / (float(did["beats_per_bar"]) / steps_per_bar) + late(step, swing)
    return {
        "on": True,
        "velocity": int(did["velocity"]),
        "length": float(length) if length is not None else round(in_steps, 4),
        "before": _as_notes(did["before"]),
    }


# --------------------------------------------------------------------------- Live: painting


class Kept(TypedDict):
    """A clip that was replaced or erased: the bar it started on, its name and its notes, enough to put it back."""

    bar: int
    name: str
    notes: list[Note]


class Skipped(TypedDict):
    """A bar that was left alone, why, and the clips there."""

    bar: int
    why: str
    clips: NotRequired[list[ClipInfo]]


class Painted(TypedDict):
    """What `paint` did. `error` (with `blocked`) when no MIDI clip covers exactly the bars to paint from."""

    painted: list[int]
    skipped: list[Skipped]
    replaced: list[Kept]
    error: NotRequired[str]
    blocked: NotRequired[list[ClipInfo]]


class Erased(TypedDict):
    erased: list[Kept]
    skipped: list[Skipped]


class PaintedBar(TypedDict):
    bar: int
    hash: str
    name: str


def _targets(bars_list: Iterable[int]) -> list[int]:
    targets = list(dict.fromkeys(check_bar(b) for b in bars_list))
    if len(targets) > MAX_TARGETS:
        raise ValueError(f"at most {MAX_TARGETS} bars in one call, not {len(targets)}")
    return targets


def _span_bars(bars: object) -> int:
    return _int(bars, "a clip's length in bars", 1, 1024)


def _kept(found: Iterable[Mapping[str, Any]]) -> list[Kept]:
    return [{"bar": int(k["bar"]), "name": str(k["name"]), "notes": _as_notes(k["notes"])} for k in found]


def paint(live: McpTransport, track: TrackRef, from_bar: int, bars: int, to_bars: Sequence[int]) -> Painted:
    """Stamp the clip that covers exactly [from_bar, from_bar + bars) onto each bar in `to_bars` (each the first
    bar of a copy), with Live's duplicate_clip_to_arrangement: the copy is the whole clip, its name and loop too.

    A target that one MIDI clip covers exactly is replaced (deleted, then the copy made) and its notes come back
    in `replaced`. A target that a clip of another length reaches into is skipped and reported, as is the source's
    own bar; nothing is ever cut. At most 64 targets; they go to Live 16 to a call, in the order given, each
    target looked at just before its copy, so a target that an earlier copy now covers partly is skipped too."""
    source, length, targets = check_bar(from_bar), _span_bars(bars), _targets(to_bars)
    out: Painted = {"painted": [], "skipped": [], "replaced": []}
    for k in range(0, len(targets), PER_CALL):
        did = _run(
            live,
            track,
            "clip_stamp(song, _t, **_a)",
            source=source,
            bars=length,
            to=targets[k : k + PER_CALL],
            pause=COPY_PAUSE_S,
        )
        if "error" in did:
            out["error"], out["blocked"] = str(did["error"]), list(did["blocked"])
            break
        out["painted"] += [int(b) for b in did["painted"]]
        out["skipped"] += list(did["skipped"])
        out["replaced"] += _kept(did["replaced"])
    return out


def erase(live: McpTransport, track: TrackRef, bars_list: Sequence[int], bars: int) -> Erased:
    """Delete the MIDI clips that cover exactly `bars` bars from each bar in `bars_list` (64 at most). Never an
    audio clip, never a clip of another length: those bars are skipped and reported, as are free ones. The erased
    clips' names and notes come back, enough to put them back. One call."""
    did = _run(live, track, "clip_wipe(song, _t, **_a)", bars_list=_targets(bars_list), bars=_span_bars(bars))
    return {"erased": _kept(did["erased"]), "skipped": list(did["skipped"])}


def painted(live: McpTransport, track: TrackRef, bars: int, total_bars: int) -> list[PaintedBar]:
    """The bars of the track, up to `total_bars`, on which a MIDI clip of exactly `bars` bars starts, earliest
    first, each with a content hash of its notes (`content_hash`, also `read`'s "hash") and the clip's name: the
    bars with the hash of the pattern at hand hold that pattern, the others another one. One call; 256 at most."""
    found = _run(
        live,
        track,
        "clips_stamped(song, _t, **_a)",
        bars=_span_bars(bars),
        total_bars=check_bar(total_bars),
        cap=MAX_PAINTED,
    )
    return [{"bar": int(c["bar"]), "hash": str(c["hash"]), "name": str(c["name"])} for c in found]


# --------------------------------------------------------------------------- Live: a span put back, the loop


class Held(TypedDict):
    """What a span held: its exact clip's name and notes (beats from the span's start)."""

    name: str
    notes: list[Note]


class Restored(TypedDict):
    """`was` is what the span held before the call: None when it was free."""

    was: Held | None


def restore(
    live: McpTransport,
    track: TrackRef,
    bar: int,
    bars: int,
    notes: Iterable[Sequence[float]] | None,
    name: str | None = None,
) -> Restored | Blocked:
    """Make the span of `bars` bars from `bar` hold exactly `notes` ((pitch, beats from the span's start, duration
    in beats, velocity), as `before`, `replaced` and `erased` give them) in one MIDI clip that covers exactly it:
    the clip there gets them, a free span gets a new clip (named `name` if given). With `notes` None the span is
    left with no clip: the one that covers exactly it is deleted. The answer's `was` is what the span held before
    (None: it was free), so calling `restore` again with it takes this call back: the app's undo and redo. Clips
    of another length in the way give {"error", "blocked"} and nothing is changed. One call."""
    did = _run(
        live,
        track,
        f"span_put(song, _t, {_NOTE_SPEC}, **_a)",
        bar=check_bar(bar),
        bars=_span_bars(bars),
        notes=None if notes is None else [[int(p), float(s), float(d), int(v)] for p, s, d, v in notes],
        name=name,
    )
    if "error" in did:
        return {"error": str(did["error"]), "blocked": list(did["blocked"])}
    was = did["was"]
    return {"was": None if was is None else {"name": str(was["name"]), "notes": _as_notes(was["notes"])}}


class Loop(TypedDict):
    """The Arrangement's loop: whether it is on, where it starts and how long it is, in beats."""

    on: bool
    start: float
    length: float


def _song_run(live: McpTransport, call: str, prelude: bool = False, **args: Any) -> Any:
    """One call to Live that is about no one track: `call`, an expression over the arguments `_a`, with
    zpkt.live.inlive.steps above it (and zpkt.live.agent's prelude, for select_track)."""
    code = f"import json\n_a = json.loads({json.dumps(args)!r})\nresult = json.dumps({call})"
    return json.loads(live.run(with_source(with_prelude(code) if prelude else code, "steps")))


def _as_loop(found: Mapping[str, Any]) -> Loop:
    return {"on": bool(found["on"]), "start": float(found["start"]), "length": float(found["length"])}


def loop(live: McpTransport, bar: int, bars: int) -> Loop:
    """Loop `bars` bars from `bar` (counted from 1) in the Arrangement and switch the loop on, so a pattern is heard
    going round with the song. A playhead outside the loop goes to its start; inside it, Live plays on. Returns
    what the loop was, for `loop_put`. One call."""
    return _as_loop(_song_run(live, "loop_bars(song, **_a)", bar=check_bar(bar), bars=_span_bars(bars)))


def loop_put(live: McpTransport, was: Mapping[str, Any]) -> Loop:
    """Put the loop back as `loop` found it ({"on", "start", "length"}); returns what it was just now. One call."""
    start = _number(was.get("start"), "a loop's start in beats", 0.0, 1e7)
    length = _number(was.get("length"), "a loop's length in beats", 0.25, 1e7)
    return _as_loop(_song_run(live, "loop_put(song, **_a)", on=bool(was.get("on")), start=start, length=length))


# --------------------------------------------------------------------------- Live: a new drum track


class StepsError(RuntimeError):
    """Live did not do the step. The message says what was asked and what was found."""


class NewTrack(TypedDict):
    name: str
    index: int  # among the set's tracks
    kit: str
    device: str  # the name the kit's Drum Rack has on the track


def kits(live: McpTransport, cap: int = MAX_KITS) -> list[str]:
    """The Drum Rack presets Live's browser offers under Drums, by name (without ".adg"), in the browser's order,
    at most `cap`. Names only; one call. GUESS (zpkt.live.inlive.steps.kit_items): which browser entries are kits."""
    return [str(name) for name in _song_run(live, "kit_names(browser, **_a)", cap=_int(cap, "how many kits", 1, 500))]


def _track_names(live: McpTransport) -> list[str]:
    return [str(name) for name in live.run("result = [t.name for t in song.tracks]")]


def new_drum_track(live: McpTransport, name: str, kit: str, pause: Callable[[float], None] = time.sleep) -> NewTrack:
    """Make a MIDI track called `name` with the kit `kit` (a name `kits` gives) on it. It is put in front of the
    first monitor track ("mon ...": the mix desk keeps those last), or last when the set has none.

    Short calls, none of which reads back what it wrote (ableton-guide rules 1, 4 and 6): look (the tracks' names,
    and whether the browser has the kit: nothing is made when it does not, or when a track has the name), make the
    track, read the tracks until there is one more, name it by its index, load the kit onto it (select the track,
    `browser.load_item`, as zpkt.live.chain loads an effect), read its devices until the kit is there. StepsError
    says which of those Live did not do. Nothing here takes the track away again.

    GUESS: `song.create_midi_track(i)` puts the new track at index i among the tracks; where it did land is read,
    and a track that landed somewhere else is still named and filled. GUESS: a track made at an index that
    follows a group's last track is outside the group."""
    name, kit = str(name).strip(), str(kit).strip()
    if not name or not kit:
        raise ValueError("a new drum track needs a name and a kit")
    look = _song_run(live, "new_track_look(song, browser, **_a)", kit=kit)
    before = [str(n) for n in look["names"]]
    if not look["kit"]:
        raise ValueError(f"Live's browser has no kit {kit!r} under Drums")
    if name in before:
        raise ValueError(f"the set already has a track called {name!r}")
    first_monitor = next((i for i, n in enumerate(before) if n.startswith(MONITOR_PREFIX)), None)
    live.run(f"song.create_midi_track({-1 if first_monitor is None else first_monitor})\nresult = 'ok'")
    after = before
    for _ in range(POLLS):
        pause(SETTLE_S)
        after = _track_names(live)
        if len(after) > len(before):
            break
    if len(after) != len(before) + 1:
        raise StepsError(f"Live did not make the track (the set had {len(before)} tracks and has {len(after)})")
    index = next((i for i, n in enumerate(before) if after[i] != n), len(before))  # where the new one landed
    live.run(f"song.tracks[{index}].name = {name!r}\nresult = 'ok'")
    had = int(
        _song_run(live, "kit_load(song, browser, select_track, **_a)", prelude=True, index=index, name=name, kit=kit)
    )
    devices: list[str] = []
    for _ in range(POLLS):
        pause(SETTLE_S)
        devices = [str(d) for d in live.run(f"result = [d.name for d in song.tracks[{index}].devices]")]
        if len(devices) > had:
            return {"name": name, "index": index, "kit": kit, "device": devices[0]}
    raise StepsError(f"Live did not load the kit {kit!r} onto {name!r} (its devices: {devices})")
