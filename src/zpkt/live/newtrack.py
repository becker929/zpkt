"""A new track, one short call at a time: make it, see that the set grew, name it.

    newtrack.make(live, "audio", "Parallel")   # an audio track, last; "midi" likewise; "return" is a new return
    index = newtrack.create(live, "audio")     # the same in two steps, for a caller that records the track
    newtrack.set_name(live, "audio", index, "Parallel")   # as soon as it exists, before it is named

Each function takes the Live connection (the app hands it in). Each call to Live is short and never reads back what
it wrote: the count is read in calls of its own before and after (ableton-guide rules 1, 4 and 6), and the name is
set on the track by its index, not through an alias that the creation made stale. An audio or MIDI track is made
last (after the monitor tracks, which the desk finds by name). A return gets Live's letter in front of its name by
itself ("C-Parallel"); zpkt names it without the letter (zpkt.live.inlive.tracks).

Nothing here takes a track away again: the app does not undo a new track (zpkt.app.propose).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from zpkt.live.transport import McpTransport

KINDS = ("audio", "midi", "return")
SETTLE_S = 0.3  # after the creation, before the set is read again
POLLS = 6  # times the count is read, SETTLE_S apart, before the creation counts as failed

_MAKE = {
    "audio": "song.create_audio_track(-1)",
    "midi": "song.create_midi_track(-1)",
    "return": "song.create_return_track()",
}


class NewTrackError(RuntimeError):
    """Live did not make the track. The message says what was asked and what was found."""


def _tracks(kind: str) -> str:
    return "song.return_tracks" if kind == "return" else "song.tracks"


def create(client: McpTransport, kind: str, pause: Callable[[float], None] = time.sleep) -> int:
    """Make a track of `kind` ("audio", "midi" or "return") with the name Live gives it; returns its index among
    the tracks (the returns, for a return). NewTrackError when the set did not grow by one."""
    if kind not in KINDS:
        raise ValueError(f"a new track is one of {', '.join(KINDS)}, not {kind!r}")
    before = int(client.run(f"result = len({_tracks(kind)})"))
    client.run(f"{_MAKE[kind]}\nresult = 'ok'")
    after = before
    for _ in range(POLLS):
        pause(SETTLE_S)
        after = int(client.run(f"result = len({_tracks(kind)})"))
        if after > before:
            break
    if after != before + 1:
        raise NewTrackError(f"Live did not make the {kind} track (the set had {before} and has {after})")
    return after - 1


def set_name(client: McpTransport, kind: str, index: int, name: str) -> None:
    """Name the track at `index` of its kind's list (a call of its own: never in the call that made it)."""
    client.run(f"{_tracks(kind)}[{int(index)}].name = {name!r}\nresult = 'ok'")


def make(client: McpTransport, kind: str, called: str, pause: Callable[[float], None] = time.sleep) -> int:
    """Make a track of `kind` called `called`; returns its index among the tracks (the returns, for a return)."""
    index = create(client, kind, pause)
    set_name(client, kind, index, called)
    return index
