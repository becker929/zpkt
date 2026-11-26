"""The desk's monitor tracks in Live: the original render, the recipe's render and the references, as audio clips in
the Arrangement, and the switch that chooses which one is heard.

"mon A" and "mon B" hold the two renders at beat 0; "mon C1".."mon C4" hold the references at the drop, warping off.
All stay muted unless they are being heard, so a render of the set never doubles. While one plays, Main's desk devices
are bypassed (the clip was rendered after them) and put back when the working mix (W) is heard again.

Every function takes the Live connection (the app hands it in) and keeps each call short, as the ableton guide asks.
This is the logic that used to sit in contrib/mixdesk/pager.py (inside Live) and server.py; the pager keeps its own
copy so the old desk still works.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from zpkt.live.desk_pager import MODULE as PAGER_MODULE
from zpkt.live.inlive import with_source
from zpkt.live.transport import McpTransport

PREFIX = "mon "
MAIN_DEVICES = ("desk headroom", "desk Glue", "desk Utility")  # bypassed while a monitor track plays
WORKING_MIX = "W"
MISSING = "monitor tracks missing"


class Switched(TypedDict):
    """What `switch` did: the On values it saved from Main's desk devices (None: not bypassed) and any error."""

    main_saved: dict[str, float] | None
    error: NotRequired[str]
    placed: NotRequired[list[float]]  # with a Place: [where the playhead was, where it went], in beats


class Grid(TypedDict):
    """A bar grid on the set's timeline: the beat its bar 0 starts at, and its tempo (None: the set's own). `bars`
    (a count of its own bars) or `span` (beats) is the stretch that repeats; neither: it does not wrap."""

    origin: float
    bpm: float | None
    bars: NotRequired[float | None]
    span: NotRequired[float | None]


class Place(TypedDict):
    """Where the playhead goes with a switch, so that what is heard next is at the same bar and the same place in the
    bar as what was heard, each on its own tempo: from one grid to the other. `loop` is what Live loops afterwards:
    [start, length] in beats, "span" for the target grid's own stretch, False for no loop; left out: as it is."""

    src: Grid
    dst: Grid
    loop: NotRequired[list[float] | str | bool]


def track_name(slot: str, ref: str) -> str | None:
    """The monitor track heard for a slot: A and B are their own, C is the reference; W has none."""
    if slot == WORKING_MIX:
        return None
    return PREFIX + (ref if slot == "C" else slot)


def track_names(live: McpTransport) -> list[str]:
    return list(live.run("result = [t.name for t in song.tracks]"))


def missing(live: McpTransport, wanted: Mapping[str, Any]) -> list[str]:
    """The wanted monitor tracks that the set does not have."""
    have = track_names(live)
    return [name for name in wanted if name not in have]


def ensure(
    live: McpTransport,
    want: Mapping[str, tuple[Path, float]],
    log: Callable[..., None] = print,
    pause: Callable[[float], None] = time.sleep,
) -> None:
    """Add the monitor tracks and clips that are missing. `want` is {track name: (wav file, beat)}. Idempotent."""
    for name, (wav, beat) in want.items():
        if not wav.exists():
            raise FileNotFoundError(f"missing {wav}: run analyze.py")
        if name not in track_names(live):
            live.run("song.create_audio_track(-1)\nresult = 'ok'")
            pause(0.3)
            n = live.run("result = len(song.tracks)") - 1
            live.run(f"song.tracks[{n}].name = {name!r}\nresult = 'ok'")
            log("added", name)
        i = track_names(live).index(name)
        if live.run(f"result = len(list(song.tracks[{i}].arrangement_clips))") == 0:
            live.run(f"song.tracks[{i}].create_audio_clip({str(wav)!r}, {beat})\nresult = 'ok'")
            pause(0.4)
            log("clip", name)
        # warping off (a file of its own length must not be stretched), muted unless heard
        live.run(f"for c in song.tracks[{i}].arrangement_clips:\n    c.warping = False\nresult = 'ok'")
        live.run(f"song.tracks[{i}].mute = True\nresult = 'ok'")
        pause(0.2)


def remove(live: McpTransport, pause: Callable[[float], None] = time.sleep) -> None:
    """Delete every monitor track (before a render you keep)."""
    while True:
        found = [i for i, n in enumerate(track_names(live)) if n.startswith(PREFIX)]
        if not found:
            return
        live.run(f"song.delete_track({found[-1]})\nresult = 'ok'")
        pause(0.3)


def status(live: McpTransport) -> list[Any]:
    """[name, mute, solo, [(file, start, end, warping)]] for each monitor track."""
    return list(
        live.run(
            "result = [[t.name, t.mute, t.solo, [(c.file_path.split('/')[-1], c.start_time, c.end_time, c.warping) "
            f"for c in t.arrangement_clips]] for t in song.tracks if t.name.startswith({PREFIX!r})]"
        )
    )


def placed_beat(position: float, own_bar: float, tempo: float, place: Place) -> tuple[float, float | None]:
    """(where `place` sends a playhead at `position`, the stretch that repeats there or None), in beats. `own_bar` is
    the set's bar in beats and `tempo` its BPM. This is the arithmetic `switch_code` runs inside Live, kept here so
    it can be read and tested: the bars since the source grid's origin, counted in the source's bars, are the bars
    since the target's origin, counted in the target's."""

    def bar(grid: Grid) -> float:
        bpm = grid.get("bpm")
        return own_bar * tempo / bpm if bpm else own_bar

    src, dst = place["src"], place["dst"]
    bars = dst.get("bars")
    span = bars * bar(dst) if bars else dst.get("span")
    at = (position - src["origin"]) / bar(src) * bar(dst)
    at = at % span if span else max(at, 0.0)
    return dst["origin"] + at, span


def switch_code(
    slot: str, ref: str, gain_db: float, main_saved: Mapping[str, float] | None, place: Place | None = None
) -> str:
    """The Live code that makes `slot` heard. The result is a Switched dict. If the mix desk's pager runs in Live, it
    is told the new choice too (so a pager reload carries it on) and its own listeners stay quiet for a moment.

    With a `place` the same call moves the playhead and sets the loop (`placed_beat`), so the switch lands on the
    beat: the position is read and written inside Live, in one go with the solo, and no second call is waited for
    (a call from the app takes Live a few hundred milliseconds to get to)."""
    target = track_name(slot, ref)
    body = f"""
import sys, time
slot, ref, target, gain = {slot!r}, {ref!r}, {target!r}, {gain_db!r}
_pager = sys.modules.get({PAGER_MODULE!r})
_desk = getattr(_pager, "DESK", None) if _pager is not None else None
if _desk is not None:
    _desk.sys_until = time.time() + 0.8
saved = json.loads({json.dumps(None if main_saved is None else dict(main_saved))!r})
mons = dict((t.name, t) for t in song.tracks if t.name.startswith({PREFIX!r}))
heard = mons.get(target) if target else None
if target and heard is None:
    result = {{"main_saved": saved, "error": {MISSING!r}}}
else:
    if heard is not None:
        for t in list(song.tracks) + list(song.return_tracks):
            if t.solo and t is not heard:
                t.solo = False
    for t in mons.values():
        if t is not heard:
            if t.solo:
                t.solo = False
            if not t.mute:
                t.mute = True
    if heard is not None:
        if heard.mute:
            heard.mute = False
        volume = heard.mixer_device.volume
        value = raw_for(volume, "%.2f dB" % gain)
        if value is not None:
            volume.value = value
        if not heard.solo:
            heard.solo = True
    devs = [d for d in song.master_track.devices if d.name in {list(MAIN_DEVICES)!r}]
    if slot != {WORKING_MIX!r}:
        if saved is None:
            saved = dict((d.name, d.parameters[0].value) for d in devs)
        for d in devs:
            if d.parameters[0].value != 0.0:
                d.parameters[0].value = 0.0
    else:
        was = saved or {{}}
        for d in devs:
            d.parameters[0].value = was.get(d.name, 1.0)
        saved = None
    if _desk is not None:
        _desk.monitor_slot, _desk.monitor_ref, _desk.main_saved = slot, ref, saved
    result = {{"main_saved": saved}}
    place = json.loads({json.dumps(place)!r})
    if place is not None:
        own = 4.0 * song.signature_numerator / song.signature_denominator
        src, dst = place["src"], place["dst"]
        src_bar = own * song.tempo / src["bpm"] if src.get("bpm") else own
        dst_bar = own * song.tempo / dst["bpm"] if dst.get("bpm") else own
        span = dst["bars"] * dst_bar if dst.get("bars") else dst.get("span")
        here = song.current_song_time
        at = (here - src["origin"]) / src_bar * dst_bar
        at = at % span if span else max(at, 0.0)
        to = dst["origin"] + at
        loop = place.get("loop")
        if loop == "span":
            loop = [dst["origin"], span] if span else None
        if loop is False:
            song.loop = False
        elif loop:
            song.loop_start = loop[0]
            song.loop_length = loop[1]
            song.loop = True
        song.current_song_time = to
        if not song.is_playing:
            song.start_time = to
        result["placed"] = [here, to]
"""
    return with_source("import json\n" + body, "shown")


def switch(
    live: McpTransport,
    slot: str,
    ref: str,
    gain_db: float,
    main_saved: Mapping[str, float] | None,
    place: Place | None = None,
) -> Switched:
    """Choose what is heard (W: the working mix; A, B, C: a monitor track) at `gain_db`, with Main's desk devices
    bypassed while a track plays. `main_saved` is what an earlier switch returned. `place` moves the playhead and
    sets the loop with it (`placed_beat`). One call to Live."""
    out: Switched = live.run(switch_code(slot, ref, gain_db, main_saved, place))
    return out
