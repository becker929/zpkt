"""The score: everything the booth will take from the bot, as data (docs/bluesky-bot.md, "The score").

A score never carries code, paths or device names. Instruments, returns and macros are palette ids and names that
the booth looks up in its own table (palette.py); numbers are bounded here and again by the palette (check.py). The
shapes are deliberately plain for Claude's structured outputs: lists of objects with fixed keys, no maps keyed by
the model's own names, no tuples.

Time is in beats, 4/4 only. A pattern is `bars` long and repeats to fill each song section that plays it (cut at
the section's end).

A part plays a palette instrument or a sample (samples.py): an id the booth gave the bot for a file it uploaded, never
a path. A sample is either placed in the arrangement as audio clips (mode "clip", which plays no patterns), or held
by a Simpler that the part's patterns play like any instrument (modes "one_shot" and "slices").

lib/contracts/score.schema.json is generated from Score by scripts/gen_schema.py; tests fail if it is stale.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

BEATS_PER_BAR = 4
MAX_PARTS = 8
MAX_PATTERNS = 64
MAX_SECTIONS = 32
MAX_PATTERN_NOTES = 512
MAX_NOTES = 2000          # after patterns repeat; add_new_notes calls stay well under the transport's 12 s
MAX_BARS = 64
MAX_AUDIO_S = 60.0
MAX_CLIPS = 64            # arrangement clips a looped sample becomes, all parts together
MAX_SLICES = 32

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,23}$")]
PaletteId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.]{1,64}$")]
SampleId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Feel(_Strict):
    """Applied by the booth's compiler, seeded: the same score always gives the same notes."""

    swing: float = Field(0.0, ge=0.0, le=0.5, description="how far each off-beat 16th moves late, as a share of a 16th")
    humanize_ms: float = Field(0.0, ge=0.0, le=25.0, description="random timing spread, milliseconds")
    velocity_jitter: int = Field(0, ge=0, le=24, description="random velocity spread")
    seed: int = Field(0, ge=0, le=2**31 - 1)


class Macro(_Strict):
    name: Id = Field(description="one of the instrument's macros in the guide")
    value: float = Field(ge=0.0, le=1.0)


class Sample(_Strict):
    """A sample the part plays. Fields for another mode are left out."""

    id: SampleId = Field(description="a sample id the booth gave for an uploaded file")
    mode: Literal["clip", "one_shot", "slices"] = Field(
        "clip", description="clip: the audio itself in the arrangement, no patterns; one_shot: patterns trigger the whole "
        "sample, pitch 60 as recorded; slices: patterns trigger slices, pitch 36 the first")
    start_beat: float = Field(0.0, ge=0.0, le=MAX_BARS * BEATS_PER_BAR, description="clip: where it starts, in song beats")
    length_beats: float | None = Field(None, gt=0.0, le=MAX_BARS * BEATS_PER_BAR,
                                       description="clip: cut after this many beats; none plays it out (looped: to the song's end)")
    loop: bool = Field(False, description="clip: repeat it back to back until length_beats or the song's end")
    warp: Literal["off", "beats", "complex"] = Field(
        "off", description="clip: off plays it as recorded; beats (drums, loops) or complex (anything else) stretch it to fit_beats")
    fit_beats: float | None = Field(None, gt=0.0, le=MAX_BARS * BEATS_PER_BAR,
                                    description="clip, warped: how many beats the whole sample lasts; none is the nearest whole bars")
    transpose: int = Field(0, ge=-24, le=24, description="clip: semitones; with warp off it also plays faster or slower, like tape")
    slices: list[float] = Field(default_factory=list, max_length=MAX_SLICES,
                                description="slices: where each slice starts, seconds into the sample, rising, the first 0")


class Part(_Strict):
    id: Id
    instrument: PaletteId | None = Field(None, description="an instrument id from the guide; or give sample instead")
    sample: Sample | None = Field(None, description="a sample instead of an instrument")
    gain_db: float = Field(0.0, ge=-30.0, le=6.0)
    pan: float = Field(0.0, ge=-1.0, le=1.0)
    room: float = Field(0.0, ge=0.0, le=1.0, description="send to the room return")
    echo: float = Field(0.0, ge=0.0, le=1.0, description="send to the echo return")
    macros: list[Macro] = Field(default_factory=list, max_length=8)


class Note(_Strict):
    p: int = Field(ge=0, le=127, description="MIDI pitch")
    t: float = Field(ge=0.0, description="start, beats from the pattern's start")
    d: float = Field(gt=0.0, le=64.0, description="length, beats")
    v: int = Field(ge=1, le=127, description="velocity")


class Pattern(_Strict):
    id: Id
    part: Id = Field(description="the part that plays it")
    bars: int = Field(ge=1, le=8)
    notes: list[Note] = Field(default_factory=list, max_length=MAX_PATTERN_NOTES)


class Play(_Strict):
    part: Id
    pattern: Id


class Section(_Strict):
    bars: int = Field(ge=1, le=32)
    play: list[Play] = Field(default_factory=list, max_length=MAX_PARTS, description="silent parts are left out")


class Mix(_Strict):
    room: Id = Field(description="a room setting from the guide")
    echo: Id = Field(description="an echo setting from the guide")


class Score(_Strict):
    """A short piece for the booth to build in Live and render."""

    score: Literal[1] = 1
    palette: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}$")]
    title: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    bpm: float = Field(ge=60.0, le=180.0)
    key: Annotated[str, StringConstraints(max_length=24)] = ""
    feel: Feel = Field(default_factory=Feel)
    parts: list[Part] = Field(min_length=1, max_length=MAX_PARTS)
    patterns: list[Pattern] = Field(max_length=MAX_PATTERNS, description="none only when every part is a clip-mode sample")
    song: list[Section] = Field(min_length=1, max_length=MAX_SECTIONS)
    mix: Mix

    @property
    def bars(self) -> int:
        return sum(s.bars for s in self.song)

    @property
    def beats(self) -> float:
        return float(self.bars * BEATS_PER_BAR)

    @property
    def seconds(self) -> float:
        return self.beats * 60.0 / self.bpm
