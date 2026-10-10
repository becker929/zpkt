"""Clip-level edits on a set's own clips, so their warp settings are kept (HW002 batches 4.1-4.2).

Tracks are passed by index: Live renames auto-named audio tracks when their clips change
("18-beatbox" became "18-Audio"), so names are not stable here.

Noise splash (HW002 track 5, 2022-05-30-005.wav): the song cuts a 16-beat sample to 2 beats with a
looped clip. Unloop it and set its end: the clip grows in place.

Beatbox phrase (HW002 track 17, beatbox.mp3, Texture warp, -13 st, gain 0.4, warped linearly at
0.1875 s per clip beat): clip beats 55.5-64.056, the sustained "wuh" is 61.6-64.056. The phrase is
copied (duplicate_clip_to_arrangement keeps its warp), placed so it ends at a given beat, and the
wuh stretched by adding a warp marker at its start and moving the end later. New clips from the
file are auto-warped at a detected tempo, which is why the original is copied instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from hands.live.transport import McpTransport

TEMP = 8000.0  # far past the music, for a temporary copy


@dataclass(frozen=True)
class Phrase:
    """A phrase inside a linearly warped clip, in clip beats: where it starts, where its held
    end starts, where it ends; and the clip's seconds per clip beat."""
    start: float
    hold: float
    end: float
    sec_per_beat: float


BEATBOX = Phrase(start=55.5, hold=61.6, end=64.056, sec_per_beat=0.1875)  # HW002's beatbox "wuh"


def clips_near(client: McpTransport, track: int, lo: float, hi: float) -> list:
    """[start, end, loop_start] of the arrangement clips on `track` that overlap [lo, hi)."""
    return client.run(f"result = [[c.start_time, c.end_time, c.loop_start] for c in song.tracks[{track}].arrangement_clips "
                      f"if c.start_time < {hi} and c.end_time > {lo}]")


def splash(client: McpTransport, track: int, at: float, beats: float) -> list:
    """Lengthen the looped clip starting at `at` to `beats` beats, in place."""
    return client.run(f"""
c = [c for c in song.tracks[{track}].arrangement_clips if abs(c.start_time - {at}) < 1e-6][0]
c.looping = False
c.loop_start = 0.0
c.loop_end = {float(beats)}
result = [c.start_time, c.end_time]""")


def splash_copies(client: McpTransport, track: int, src_at: float, times: list[float], beats: float) -> list:
    """Copy the clip at `src_at` to each time, unlooped and `beats` long."""
    out = []
    for t in times:
        out.append(client.run(f"""
tr = song.tracks[{track}]
src = [c for c in tr.arrangement_clips if abs(c.start_time - {src_at}) < 1e-6][0]
tr.duplicate_clip_to_arrangement(src, {float(t)})
n = [c for c in tr.arrangement_clips if abs(c.start_time - {float(t)}) < 1e-6][0]
n.looping = False
n.loop_start = 0.0
n.loop_end = {float(beats)}
result = [n.start_time, n.end_time]"""))
    return out


def place_phrase(client: McpTransport, track: int, end_at: float, stretch: float, lo: float, hi: float,
                 phrase: Phrase = BEATBOX) -> list:
    """Replace the clips on `track` in [lo, hi) with one copy of `phrase` ending at `end_at`, its
    held end stretched by `stretch`."""
    end_beat = phrase.hold + (phrase.end - phrase.hold) * stretch
    at = end_at - (end_beat - phrase.start)
    return client.run(f"""
t = song.tracks[{track}]
src = [c for c in t.arrangement_clips if abs(c.loop_start - {phrase.start}) < 1e-3][0]
t.duplicate_clip_to_arrangement(src, {TEMP})
for c in list(t.arrangement_clips):
    if c.start_time < {hi} and c.end_time > {lo}:
        t.delete_clip(c)
tmp = [c for c in t.arrangement_clips if abs(c.start_time - {TEMP}) < 1e-6][0]
t.duplicate_clip_to_arrangement(tmp, {at})
t.delete_clip(tmp)
n = [c for c in t.arrangement_clips if abs(c.start_time - {at}) < 1e-6][0]
if {stretch} != 1.0:
    n.add_warp_marker(Live.Clip.WarpMarker({phrase.hold * phrase.sec_per_beat}, {phrase.hold}))
    n.add_warp_marker(Live.Clip.WarpMarker({phrase.end * phrase.sec_per_beat}, {end_beat}))
    n.loop_end = {end_beat}
result = [n.start_time, n.end_time, n.loop_start, n.loop_end, [[w.beat_time, w.sample_time] for w in n.warp_markers]]""")


def phrase_at(client: McpTransport, track: int, hold_start: float, hold_beats: float, lo: float, hi: float,
              phrase: Phrase = BEATBOX) -> tuple[float, float, float]:
    """Place the phrase so its held end starts on `hold_start` (a grid point) and lasts
    `hold_beats`; returns (clip start, clip end, end clip-beat)."""
    stretch = hold_beats / (phrase.end - phrase.hold)
    info = place_phrase(client, track, hold_start + hold_beats, stretch, lo, hi, phrase)
    return info[0], info[1], phrase.hold + (phrase.end - phrase.hold) * stretch


def tail_slices(client: McpTransport, track: int, phrase_start: float, end_beat: float, times: list[float],
                slice_beats: float) -> list:
    """Copy the last `slice_beats` of the placed phrase onto each grid time (the "chops")."""
    out = []
    for t in times:
        out.append(client.run(f"""
tr = song.tracks[{track}]
src = [c for c in tr.arrangement_clips if abs(c.start_time - {phrase_start}) < 1e-6][0]
tr.duplicate_clip_to_arrangement(src, {float(t)})
n = [c for c in tr.arrangement_clips if abs(c.start_time - {float(t)}) < 1e-6][0]
n.loop_start = {end_beat - slice_beats}
result = [n.start_time, n.end_time]"""))
    return out


def fader_db(client: McpTransport, track: int, db: float) -> list:
    """Set an unautomated track's fader to `db` dB: Live alone knows the fader's dB curve, so
    bisect its display. Returns [position, display], computed before the write (reading the value
    back in the same call crashes Live)."""
    return client.run(f"""
v = song.tracks[{track}].mixer_device.volume
lo, hi = v.min, v.max
for _ in range(40):
    mid = (lo + hi) / 2
    s = v.str_for_value(mid).replace(" dB", "")
    if "inf" in s or float(s) < {float(db)}:
        lo = mid
    else:
        hi = mid
result = [hi, v.str_for_value(hi)]
v.value = hi""")
