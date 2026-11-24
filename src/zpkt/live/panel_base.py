"""What the panel family (zpkt.live.panel, mix, versions, song) shares: its error and its limits."""

from __future__ import annotations

TRACK_PREFIX = "panel "
LEAD_SECONDS = 1.5  # rendered before the riff and cut off: the first ~0.9 s of a resampled take is not on the timeline
SAMPLES = 33  # points per parameter when reading what Live shows across its range
ROUNDS = 2  # of narrowing in on the value that reads as asked: the whole range, then one stretch of it
FINE = 513  # points in the second round: 1/16384 of the range, in one call
ANCHORS = 9  # of those, how many go into a control's `display`
MAX_BEATS = 128.0  # renders are real time
MAX_CONTROLS = 16
CHUNK = 40  # parameters read per call (ableton-guide rule 2)

Note = tuple[int, float, float, int]


class PanelError(RuntimeError):
    """The panel cannot be made or changed as asked; the message says what to change."""


def _track(name: str) -> str:
    return f"next(x for x in song.tracks if x.name == {name!r})"


class Loc(str):
    """Where a device is when it is not a panel track's instrument: the Live expression for it (zpkt.live.mix)."""


def _device(name: str) -> str:
    return str(name) if isinstance(name, Loc) else f"{_track(name)}.devices[0]"
