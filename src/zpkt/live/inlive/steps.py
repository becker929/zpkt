"""A step pattern's clip in the Arrangement: the part of zpkt.live.steps that runs inside Live.

zpkt.live.steps sends this file above one line that calls one function here, so each call to Live is one short
piece of work on one track: look at a span of bars, put notes in it, flip one step, stamp a clip onto other bars.
Times are beats (quarter notes) as Live counts them; a span is [start, end) on the Arrangement's timeline; a note is
[pitch, beats after the span's start, duration in beats, velocity]. Nothing here uses Session view.

Stdlib only, Python 3.11: this file also runs inside Live (zpkt.live.inlive), and imports no other inlive module.
"""

from collections.abc import Iterable, Sequence
from typing import Any

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


# --------------------------------------------------------------------------- tracks and sounds

INSTRUMENT = 1  # Live.Device.DeviceType.instrument


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
    an empty list when the track's first instrument is not a Drum Rack."""
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
    when it loops over a stretch shorter than itself (a one-bar loop dragged out over four bars)."""
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
    duration, velocity], in order of start, then pitch. The clip's start marker is what plays at its start."""
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
    found = []
    for c in [clip] if clip is not None else span_clips(track, start, end)[1]:
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
