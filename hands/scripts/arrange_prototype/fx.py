"""Clip-level edits for batch 4.1, on the set's own clips (their warp settings kept).

Noise splash (track 5, 2022-05-30-005.wav): the song cuts a 16-beat sample to
2 beats with a looped clip. Unloop it and set its end: the clip grows in place.

Beatbox phrase (track 17, beatbox.mp3, Texture warp, -13 st, gain 0.4, warped
linearly at 0.1875 s per clip beat): clip beats 55.5-64.056, the sustained
"wuh" is 61.6-64.056. The phrase is copied (duplicate_clip_to_arrangement keeps
its warp), placed so it ends at a given beat, and the wuh stretched by adding a
warp marker at its start and moving the end later. New clips from the file are
auto-warped at a detected tempo, which is why the original is copied instead.
Tracks are addressed by index: Live renames auto-named audio tracks when their
clips change ("18-beatbox" became "18-Audio").
"""

SPLASH_TRACK, BEATBOX_TRACK = 5, 17
SEC_PER_BEAT_BB = 0.1875
BB_START, BB_WUH, BB_END = 55.5, 61.6, 64.056
TEMP = 8000.0  # far past the music, for a temporary copy


def clips_near(r, track, lo, hi):
    return r(f"result = [[c.start_time, c.end_time, c.loop_start] for c in song.tracks[{track}].arrangement_clips "
             f"if c.start_time < {hi} and c.end_time > {lo}]")


def splash(r, at, beats):
    """Lengthen the splash clip starting at `at` to `beats` beats, in place."""
    return r(f"""
c = [c for c in song.tracks[{SPLASH_TRACK}].arrangement_clips if abs(c.start_time - {at}) < 1e-6][0]
c.looping = False
c.loop_start = 0.0
c.loop_end = {float(beats)}
result = [c.start_time, c.end_time]""")


def beatbox_phrase(r, end_at, stretch, lo, hi):
    """Replace the beatbox clips in [lo, hi) with one phrase ending at `end_at`."""
    wuh = BB_END - BB_WUH
    end_beat = BB_WUH + wuh * stretch
    at = end_at - (end_beat - BB_START)
    return r(f"""
t = song.tracks[{BEATBOX_TRACK}]
src = [c for c in t.arrangement_clips if abs(c.loop_start - {BB_START}) < 1e-3][0]
t.duplicate_clip_to_arrangement(src, {TEMP})
for c in list(t.arrangement_clips):
    if c.start_time < {hi} and c.end_time > {lo}:
        t.delete_clip(c)
tmp = [c for c in t.arrangement_clips if abs(c.start_time - {TEMP}) < 1e-6][0]
t.duplicate_clip_to_arrangement(tmp, {at})
t.delete_clip(tmp)
n = [c for c in t.arrangement_clips if abs(c.start_time - {at}) < 1e-6][0]
if {stretch} != 1.0:
    n.add_warp_marker(Live.Clip.WarpMarker({BB_WUH * SEC_PER_BEAT_BB}, {BB_WUH}))
    n.add_warp_marker(Live.Clip.WarpMarker({BB_END * SEC_PER_BEAT_BB}, {end_beat}))
    n.loop_end = {end_beat}
result = [n.start_time, n.end_time, n.loop_start, n.loop_end, [[w.beat_time, w.sample_time] for w in n.warp_markers]]""")


BREAK_GROUP = 12


def phrase_at(r, wuh_start, wuh_beats, lo, hi):
    """Place the phrase so its wuh starts on `wuh_start` (a grid point) and lasts
    `wuh_beats`; returns (clip start, clip end, end clip-beat)."""
    stretch = wuh_beats / (BB_END - BB_WUH)
    end_at = wuh_start + wuh_beats
    info = beatbox_phrase(r, end_at, stretch, lo, hi)
    return info[0], info[1], BB_WUH + (BB_END - BB_WUH) * stretch


def tail_slices(r, phrase_start, end_beat, times, slice_beats):
    """Copy the last `slice_beats` of the placed phrase onto each grid time."""
    out = []
    for t in times:
        out.append(r(f"""
tr = song.tracks[{BEATBOX_TRACK}]
src = [c for c in tr.arrangement_clips if abs(c.start_time - {phrase_start}) < 1e-6][0]
tr.duplicate_clip_to_arrangement(src, {float(t)})
n = [c for c in tr.arrangement_clips if abs(c.start_time - {float(t)}) < 1e-6][0]
n.loop_start = {end_beat - slice_beats}
result = [n.start_time, n.end_time]"""))
    return out


def splash_copies(r, src_at, times, beats):
    """Copy the splash clip at `src_at` to each time, `beats` long."""
    out = []
    for t in times:
        out.append(r(f"""
tr = song.tracks[{SPLASH_TRACK}]
src = [c for c in tr.arrangement_clips if abs(c.start_time - {src_at}) < 1e-6][0]
tr.duplicate_clip_to_arrangement(src, {float(t)})
n = [c for c in tr.arrangement_clips if abs(c.start_time - {float(t)}) < 1e-6][0]
n.looping = False
n.loop_start = 0.0
n.loop_end = {float(beats)}
result = [n.start_time, n.end_time]"""))
    return out


def break_level(r, db):
    """Set the Break group fader (not automated in HW002) to `db` dB."""
    return r(f"""
v = song.tracks[{BREAK_GROUP}].mixer_device.volume
lo, hi = 0.0, 0.85
for _ in range(40):
    mid = (lo + hi) / 2
    s = v.str_for_value(mid).replace(" dB", "")
    val = -999.0 if "inf" in s else float(s)
    if val < {float(db)}:
        lo = mid
    else:
        hi = mid
v.value = hi
result = v.str_for_value(v.value)""")
