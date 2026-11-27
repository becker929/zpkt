"""Bounce the mix, a track or a group to a file: what the set must say first, and one export per file.

`facts` is one call to Live: the tempo, the bar, where the song ends, the loop, whether it plays, and each track
with its kind and whether it is soloed or muted. `bounce` is one pass through Live's Export dialog
(zpkt.live.render.export) for Main or for one track, and gives the file the name the caller asked for (Live adds the
track's name to a track's file). The export makes the range the loop and the time selection: `facts` holds the loop
as it was, for zpkt.live.steps.loop_put.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from zpkt.live import render
from zpkt.live.session import stop
from zpkt.live.transport import McpTransport

MIX = "mix"  # what a caller calls Main's output

_FACTS = """
import json
_tracks = []
for _t in song.tracks:
    _kind = "group" if _t.is_foldable else ("midi" if _t.has_midi_input else "audio")
    _tracks.append({"name": str(_t.name), "kind": _kind, "solo": bool(_t.solo), "mute": bool(_t.mute)})
for _t in song.return_tracks:
    _tracks.append({"name": str(_t.name), "kind": "return", "solo": bool(_t.solo), "mute": bool(_t.mute)})
_was = bool(song.is_playing)
if _was and STOP:
    song.stop_playing()
result = json.dumps({
    "tempo": float(song.tempo),
    "beats_per_bar": 4.0 * song.signature_numerator / song.signature_denominator,
    "end": float(song.last_event_time),
    "loop": {"on": bool(song.loop), "start": float(song.loop_start), "length": float(song.loop_length)},
    "playing": _was,
    "tracks": _tracks,
})
"""


class Track(TypedDict):
    name: str
    kind: str  # "audio", "midi", "group" or "return"
    solo: bool
    mute: bool


class Facts(TypedDict):
    tempo: float
    beats_per_bar: float
    end: float  # the last event of the Arrangement, in beats
    loop: dict[str, Any]  # {"on", "start", "length"}, as zpkt.live.steps.loop_put takes it
    playing: bool  # before this call; `stop` stopped it
    tracks: list[Track]


def facts(live: McpTransport, *, stop_playing: bool = False) -> Facts:
    """What a bounce must know of the set, in one call. `stop_playing` stops the transport in the same call (an
    export stops it anyway; this way the answer can say so)."""
    found: Facts = json.loads(live.run(f"STOP = {bool(stop_playing)!r}\n{_FACTS}"))
    return found


def bounce(
    live: McpTransport, out: Path, start_beat: float, length_beats: float, *, track: str | None = None, bits: int = 24
) -> Path:
    """Render [start_beat, start_beat + length_beats) of Main (`track` None) or of one track or group, as Live's
    Export dialog names it, to `out` (a new .wav). Returns `out`. An export costs about 13 s and 0.1 s per second of
    audio; it takes Live's window for that time and leaves the range as the loop and the time selection."""
    out = Path(out)
    written = render.export(live, out, start_beat, length_beats, mode="Main" if track is None else track, bits=bits)
    if len(written) != 1:
        stop(f"bounce: wanted one file for {track or MIX}, Live wrote {[f.name for f in written]}")
    if written[0] != out:  # a track's file is "<out's stem> <track>.wav"
        written[0].replace(out)
    return out


__all__ = ["MIX", "Facts", "Track", "bounce", "facts"]
