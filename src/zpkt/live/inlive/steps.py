"""A step pattern's clip in the Arrangement: the part of zpkt.live.steps that runs inside Live.

zpkt.live.steps sends this file above one line that calls one function here, so each call to Live is one short
piece of work on one track: look at a span of bars, put notes in it, flip one step, stamp a clip onto other bars.
Times are beats (quarter notes) as Live counts them; a span is [start, end) on the Arrangement's timeline; a note is
[pitch, beats after the span's start, duration in beats, velocity]. Nothing here uses Session view.

Stdlib only, Python 3.11: this file also runs inside Live (zpkt.live.inlive), and imports no other inlive module.
"""

from collections.abc import Iterable, Sequence

EPS = 1e-6  # beats: two times closer than this are the same place
TICKS = 960  # per beat: the grain of content_hash


def bar_beats(song) -> float:  # song: Live's Song
    """One bar in beats, by the song's signature: 4.0 in 4/4, 3.0 in 3/4 and in 6/8."""
    return 4.0 * song.signature_numerator / song.signature_denominator


def content_hash(notes: Iterable[Sequence[float]]) -> str:
    """Eight hex digits for a list of (pitch, start, duration, velocity), the same in Live and outside it, whatever
    the order of the notes: times count in 1/960 of a beat, and the numbers go through FNV-1a."""
    rows = sorted((round(s * TICKS), int(p), round(d * TICKS), round(v)) for p, s, d, v in notes)
    h = 2166136261
    for row in rows:
        for x in row:
            h = ((h ^ (x & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"
