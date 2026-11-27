"""A step pattern's clip in the Arrangement: the part of zpkt.live.steps that runs inside Live.

zpkt.live.steps sends this file above one line that calls one function here, so each call to Live is one short
piece of work on one track: look at a span of bars, put notes in it, flip one step, stamp a clip onto other bars.
Times are beats (quarter notes) as Live counts them; a span is [start, end) on the Arrangement's timeline; a note is
[pitch, beats after the span's start, duration in beats, velocity]. Nothing here uses Session view.

What is taken on trust about Live, and not yet seen on the real one, is marked GUESS.

Stdlib only, Python 3.11: this file also runs inside Live (zpkt.live.inlive), and imports no other inlive module.
"""

import time
from collections.abc import Iterable, Sequence
from typing import Any

EPS = 1e-6  # beats: two times closer than this are the same place
TICKS = 960  # per beat: the grain of content_hash


def bar_beats(song) -> float:  # song: Live's Song
    """One bar in beats, by the song's signature: 4.0 in 4/4, 3.0 in 3/4 and in 6/8. GUESS: one signature for the
    whole song; a signature change along the timeline is not followed."""
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


# --------------------------------------------------------------------------- tracks and sounds

INSTRUMENT = 1  # GUESS: int(device.type) of Live.Device.DeviceType.instrument


def instrument(track) -> Any:  # track: Live's Track
    """The track's first instrument, or None."""
    for device in track.devices:
        if int(device.type) == INSTRUMENT:
            return device
    return None


def midi_track_list(song):
    """The set's MIDI tracks: name, index among the tracks, colour (0xRRGGBB), and whether the first instrument is
    a Drum Rack."""
    out = []
    for index, track in enumerate(song.tracks):
        if track.has_midi_input and not track.is_foldable:
            first = instrument(track)
            out.append(
                {
                    "name": track.name,
                    "index": index,
                    "color": int(track.color),
                    "drum_rack": bool(first is not None and first.can_have_drum_pads),
                }
            )
    return out


def pad_sounds(track, cap: int) -> list[dict[str, Any]]:
    """The pads of the track's Drum Rack that hold something, as [{"pitch", "name"}], lowest first, at most `cap`;
    an empty list when the track's first instrument is not a Drum Rack. A pad holds something when it has chains
    (ableton-guide 6). GUESS: a filled pad's name is its sound's name."""
    rack = instrument(track)
    if rack is None or not rack.can_have_drum_pads:
        return []
    filled = [{"pitch": int(pad.note), "name": pad.name} for pad in rack.drum_pads if len(pad.chains)]
    filled.sort(key=lambda sound: sound["pitch"])
    return filled[:cap]


# --------------------------------------------------------------------------- a span of the Arrangement

IN_THE_WAY = "clips are in the way"


def clip_info(clip) -> dict[str, Any]:
    return {"name": clip.name, "start": clip.start_time, "end": clip.end_time}


def span_clips(track, start: float, end: float):
    """(the MIDI clip that alone covers exactly [start, end), every clip that touches the span otherwise). The
    first is None unless one MIDI clip starts and ends with the span; then the second is empty."""
    touching = [c for c in track.arrangement_clips if c.start_time < end - EPS and c.end_time > start + EPS]
    if len(touching) == 1:
        clip = touching[0]
        if clip.is_midi_clip and abs(clip.start_time - start) <= EPS and abs(clip.end_time - end) <= EPS:
            return clip, []
    return None, touching


def plays_straight(clip) -> bool:
    """Does the clip play its notes once through, so that a place in the clip is a place in the Arrangement? Not
    when it loops over a stretch shorter than itself (a one-bar loop dragged out over four bars). GUESS: a clip
    Live makes with create_midi_clip does not loop, or loops over its whole length; were it otherwise, a clip made
    here would be reported as in the way on the next call."""
    return (not clip.looping) or clip.loop_end - clip.start_marker >= clip.end_time - clip.start_time - EPS


def span_to_edit(track, start: float, end: float):
    """(the clip whose notes are the span's, or None; the clips in the way as clip_info). Both empty: the span is
    free. ValueError on a track that takes no MIDI clips."""
    if not track.has_midi_input:
        raise ValueError(f"{track.name!r} is not a MIDI track")
    clip, others = span_clips(track, start, end)
    if clip is not None and not plays_straight(clip):
        clip, others = None, [clip]
    return clip, [clip_info(c) for c in others]


def notes_in(clip, start: float, end: float):
    """The notes of `clip` that start inside [start, end) of the Arrangement, as [pitch, beats after `start`,
    duration, velocity], in order of start, then pitch. GUESS: the clip's start marker is what plays at its start
    (0 in a clip made here), so a note at start_marker + x sounds x beats into the clip."""
    first, last = max(start, clip.start_time), min(end, clip.end_time)
    if last <= first or not clip.is_midi_clip:
        return []
    shift = clip.start_marker - clip.start_time  # a time in the clip = a time in the Arrangement + shift
    found = [
        [int(n.pitch), round(n.start_time - shift - start, 6), round(n.duration, 6), round(n.velocity)]
        for n in clip.get_notes_extended(0, 128, first + shift, last - first)
    ]
    found.sort(key=lambda n: (n[1], n[0]))
    return found


def add_notes(clip, note_spec, notes) -> None:
    """Add [pitch, beats after the clip's start, duration, velocity] notes; `note_spec` is Live's
    Live.Clip.MidiNoteSpecification."""
    if notes:
        shift = clip.start_marker
        clip.add_new_notes(
            tuple(note_spec(pitch=int(p), start_time=s + shift, duration=d, velocity=v) for p, s, d, v in notes)
        )


def pattern_look(song, track, bar: int, bars: int):
    """What the span of `bars` bars from `bar` (counted from 1) holds: its notes, the clip that covers exactly it
    ("clip"; None otherwise), the clips in the way of writing it ("blocked"), and the Drum Rack's pad names."""
    per_bar = bar_beats(song)
    start = (bar - 1) * per_bar
    end = start + bars * per_bar
    clip, blocked = span_to_edit(track, start, end)
    exact, others = span_clips(track, start, end)
    found = []
    for c in others if exact is None else [exact]:
        found.extend(notes_in(c, start, end))
    found.sort(key=lambda n: (n[1], n[0]))
    return {
        "beats_per_bar": per_bar,
        "clip": None if clip is None else clip_info(clip),
        "blocked": blocked,
        "notes": found,
        "names": {str(sound["pitch"]): sound["name"] for sound in pad_sounds(track, 128)},
    }


def pattern_put(song, track, note_spec, bar: int, bars: int, notes, name):
    """Make the span hold exactly `notes` ([pitch, start, duration, velocity] with times in bars): into the clip
    that covers exactly it, else into a new clip when the span is free. Clips in the way are left as they are and
    named in the answer. Nothing is read after it is written."""
    per_bar = bar_beats(song)
    start = (bar - 1) * per_bar
    end = start + bars * per_bar
    clip, blocked = span_to_edit(track, start, end)
    if blocked:
        return {"error": IN_THE_WAY, "blocked": blocked}
    created = clip is None
    before = [] if created else notes_in(clip, start, end)
    if created:
        clip = track.create_midi_clip(start, end - start)
    else:
        clip.remove_notes_extended(0, 128, clip.start_marker, end - start)
    if name is not None and (created or clip.name != name):
        clip.name = name
    add_notes(clip, note_spec, [[p, s * per_bar, d * per_bar, v] for p, s, d, v in notes])
    return {"before": before, "created": created}


# --------------------------------------------------------------------------- one step

NO_NOTE = "no note on that step"


def step_flip(
    song,
    track,
    note_spec,
    bar: int,
    bars: int,
    pitch: int,
    at: float,
    lo: float,
    hi: float,
    duration: float,
    velocity,
    name,
):
    """Flip one step of the span: when a note of `pitch` starts in [lo, hi) it is removed, otherwise one is added at
    `at`, `duration` long. Times are in bars from the span's start. A free span gets its clip first."""
    per_bar = bar_beats(song)
    start = (bar - 1) * per_bar
    end = start + bars * per_bar
    clip, blocked = span_to_edit(track, start, end)
    if blocked:
        return {"error": IN_THE_WAY, "blocked": blocked}
    created = clip is None
    before = [] if created else notes_in(clip, start, end)
    first, last = max(lo * per_bar - EPS, 0.0), min(hi * per_bar + EPS, end - start)
    if any(n[0] == pitch and first <= n[1] < last for n in before):
        clip.remove_notes_extended(pitch, 1, clip.start_marker + first, last - first)
        return {"on": False, "velocity": 0, "before": before, "created": False}
    if created:
        clip = track.create_midi_clip(start, end - start)
        if name is not None:
            clip.name = name
    add_notes(clip, note_spec, [[pitch, at * per_bar, duration * per_bar, velocity]])
    return {"on": True, "velocity": velocity, "before": before, "created": created}


def step_change(song, track, note_spec, bar: int, bars: int, pitch: int, lo: float, hi: float, velocity, duration):
    """Give the note of `pitch` that starts in [lo, hi) (bars from the span's start) another velocity, another
    duration (in bars), or both; None leaves one as it is. The note is taken out and put back changed, with what
    else it carries (its probability and the like)."""
    per_bar = bar_beats(song)
    start = (bar - 1) * per_bar
    end = start + bars * per_bar
    clip, blocked = span_to_edit(track, start, end)
    if blocked:
        return {"error": IN_THE_WAY, "blocked": blocked}
    if clip is None:
        return {"error": NO_NOTE, "before": []}
    before = notes_in(clip, start, end)
    first, last = max(lo * per_bar - EPS, 0.0), min(hi * per_bar + EPS, end - start)
    shift = clip.start_marker
    changed = [
        {
            "pitch": pitch,
            "start_time": n.start_time,
            "duration": n.duration if duration is None else duration * per_bar,
            "velocity": n.velocity if velocity is None else velocity,
            "mute": n.mute,
            "probability": n.probability,
            "velocity_deviation": n.velocity_deviation,
            "release_velocity": n.release_velocity,
        }
        for n in clip.get_notes_extended(pitch, 1, shift + first, last - first)
    ]
    if not changed:
        return {"error": NO_NOTE, "before": before}
    clip.remove_notes_extended(pitch, 1, shift + first, last - first)
    clip.add_new_notes(tuple(note_spec(**note) for note in changed))
    return {
        "on": True,
        "velocity": round(changed[0]["velocity"]),
        "duration": changed[0]["duration"],
        "beats_per_bar": per_bar,
        "before": before,
    }


# --------------------------------------------------------------------------- painting

NO_SOURCE = "no MIDI clip covers exactly the bars to paint from"
THE_SOURCE = "the bars painted from"
OVERLAP = "a clip of another length is in the way"
AUDIO = "an audio clip is there"
NOTHING = "no clip there"


def why_not(others) -> str:
    """Why a span whose clips are `others` is left alone."""
    if not others:
        return NOTHING
    return AUDIO if any(c.is_audio_clip for c in others) else OVERLAP


def clip_stamp(song, track, source: int, bars: int, to, pause: float):
    """Copy the clip that covers exactly `bars` bars from bar `source` onto each bar in `to` (the first bar of a
    copy). A target that one MIDI clip covers exactly is replaced: its notes are kept in the answer, it is deleted,
    then the copy is made. A target another clip reaches into is skipped. `pause` seconds pass between copies.
    The clips are read again before each copy, as zpkt.live.arrange.fx does on the real Live. GUESS: the copy of
    an Arrangement clip is as long as its source and starts at the time given."""
    if not track.has_midi_input:
        raise ValueError(f"{track.name!r} is not a MIDI track")
    per_bar = bar_beats(song)
    length = bars * per_bar
    origin = (source - 1) * per_bar
    clip, others = span_clips(track, origin, origin + length)
    if clip is None:
        return {"error": NO_SOURCE, "blocked": [clip_info(c) for c in others]}
    painted: list[int] = []
    skipped: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    for bar in to:
        start = (bar - 1) * per_bar
        if bar == source:
            skipped.append({"bar": bar, "why": THE_SOURCE})
            continue
        there, others = span_clips(track, start, start + length)
        if others:
            skipped.append({"bar": bar, "why": why_not(others), "clips": [clip_info(c) for c in others]})
            continue
        if there is not None:
            replaced.append({"bar": bar, "name": there.name, "notes": notes_in(there, start, start + length)})
            track.delete_clip(there)
        if painted and pause:
            time.sleep(pause)
        track.duplicate_clip_to_arrangement(span_clips(track, origin, origin + length)[0], start)
        painted.append(bar)
    return {"painted": painted, "skipped": skipped, "replaced": replaced}


def clip_wipe(song, track, bars_list, bars: int):
    """Delete the MIDI clips that cover exactly `bars` bars from each bar in `bars_list`, keeping their notes in
    the answer. An audio clip, a clip of another length and a free span are left as they are, and named."""
    per_bar = bar_beats(song)
    length = bars * per_bar
    erased, skipped = [], []
    for bar in bars_list:
        start = (bar - 1) * per_bar
        clip, others = span_clips(track, start, start + length)
        if clip is None:
            skipped.append({"bar": bar, "why": why_not(others), "clips": [clip_info(c) for c in others]})
            continue
        erased.append({"bar": bar, "name": clip.name, "notes": notes_in(clip, start, start + length)})
        track.delete_clip(clip)
    return {"erased": erased, "skipped": skipped}


def clips_stamped(song, track, bars: int, total_bars: int, cap: int):
    """The bars (counted from 1, up to `total_bars`) on which a MIDI clip of exactly `bars` bars starts, each with
    the content hash of its notes and its name; at most `cap` of them, earliest first."""
    per_bar = bar_beats(song)
    length = bars * per_bar
    found = []
    for clip in track.arrangement_clips:
        at = clip.start_time / per_bar
        bar = round(at) + 1
        if (
            clip.is_midi_clip
            and abs(clip.end_time - clip.start_time - length) <= EPS
            and abs(at - round(at)) * per_bar <= EPS
            and bar <= total_bars
        ):
            notes = notes_in(clip, clip.start_time, clip.end_time)
            found.append({"bar": bar, "hash": content_hash(notes), "name": clip.name})
            if len(found) >= cap:
                break
    return found


# --------------------------------------------------------------------------- a span put back (the app's undo)


def span_put(song, track, note_spec, bar: int, bars: int, notes, name):
    """Make the span of `bars` bars from `bar` hold what it is told to, and say what it held: with `notes` ([pitch,
    beats after the span's start, duration in beats, velocity]) one MIDI clip covers exactly the span and holds
    exactly them (a free span gets the clip, named `name` if one is given); with `notes` None no clip is there at
    all (the clip that covers exactly the span is deleted). The answer's "was" is None for a span that was free,
    else {"name", "notes"}: put back the same way, it takes this call back. Clips in the way: nothing is changed."""
    per_bar = bar_beats(song)
    start = (bar - 1) * per_bar
    end = start + bars * per_bar
    clip, blocked = span_to_edit(track, start, end)
    if blocked:
        return {"error": IN_THE_WAY, "blocked": blocked}
    was = None if clip is None else {"name": clip.name, "notes": notes_in(clip, start, end)}
    if notes is None:
        if clip is not None:
            track.delete_clip(clip)
        return {"was": was}
    if clip is None:
        clip = track.create_midi_clip(start, end - start)
    else:
        clip.remove_notes_extended(0, 128, clip.start_marker, end - start)
    if name is not None and (was is None or was["name"] != name):
        clip.name = name
    add_notes(clip, note_spec, notes)
    return {"was": was}


# --------------------------------------------------------------------------- the loop


def loop_put(song, on: bool, start: float, length: float):
    """Set the Arrangement's loop to `length` beats from `start` and switch it on or off; what the loop was comes
    back as {"on", "start", "length"}. A playhead outside a loop that is switched on goes to the loop's start, as
    the mix desk's own loop keys do; inside it, Live plays on undisturbed."""
    was = {"on": bool(song.loop), "start": float(song.loop_start), "length": float(song.loop_length)}
    now, playing = song.current_song_time, song.is_playing
    song.loop_start = start
    song.loop_length = length
    song.loop = bool(on)
    if on and not start - EPS <= now < start + length:
        song.current_song_time = start
        if not playing:
            song.start_time = start
    return was


def loop_bars(song, bar: int, bars: int):
    """Loop `bars` bars from `bar` (counted from 1); what the loop was comes back (loop_put)."""
    per_bar = bar_beats(song)
    return loop_put(song, True, (bar - 1) * per_bar, bars * per_bar)


# --------------------------------------------------------------------------- a new drum track

KIT_END = ".adg"  # GUESS: a Drum Rack preset in Live's browser is named "<kit>.adg"


def kit_items(browser) -> list[Any]:
    """The Drum Rack presets Live's browser offers under Drums, in the browser's order. GUESS: they are the
    loadable children of browser.drums whose names end in ".adg" (contrib/arranger/fxset.py loads "909 Core
    Kit.adg" from there); the folders beside them (Drum Hits) are not opened, so the call stays short."""
    return [c for c in browser.drums.children if c.is_loadable and c.name.lower().endswith(KIT_END)]


def kit_names(browser, cap: int) -> list[str]:
    """The kits' names without ".adg", at most `cap`."""
    return [item.name[: -len(KIT_END)] for item in kit_items(browser)[:cap]]


def kit_item(browser, kit: str):
    """The browser's item for the kit called `kit` (with or without ".adg"), or None."""
    want = kit.lower()
    want = want[: -len(KIT_END)] if want.endswith(KIT_END) else want
    for item in kit_items(browser):
        if item.name[: -len(KIT_END)].lower() == want:
            return item
    return None


def new_track_look(song, browser, kit: str):
    """What making a drum track needs to know first: the tracks' names in order, and whether Live has the kit."""
    return {"names": [t.name for t in song.tracks], "kit": kit_item(browser, kit) is not None}


def kit_load(song, browser, select, index: int, name: str, kit: str) -> int:
    """Load the kit onto the track at `index`, which must be called `name` (the track made for it a call ago).
    `select` is zpkt.live.agent's select_track: selecting a track arms it, and the arm states are put back. The
    answer is how many devices the track had; whether the kit arrived is read in a later call."""
    track = song.tracks[index]
    if track.name != name:
        raise ValueError(f"the track at {index} is {track.name!r}, not {name!r}: the tracks changed")
    item = kit_item(browser, kit)
    if item is None:
        raise ValueError(f"no kit {kit!r} under Drums in Live's browser")
    had = len(track.devices)
    select(track)
    browser.load_item(item)
    return had
