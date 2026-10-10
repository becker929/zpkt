"""Rewrite the hat parts as sections of accumulating layers (HW002 batch 4.3-4.4).

Each layer is a set of drum-rack pads with its own rhythm and register. HW002's:
  A  perc 2  OH main + OH layer   loud offbeat open hats
  B  perc 1  CH                   accented 16th closed hat
  C  perc 2  RD1 + RD2            loud 8th rides
  D  perc 2  VEC1 CH 27 + CH1     bright 16th closed hats
  E  perc 1  RD + OH + VEC1 OH    quiet 8th ride, soft offbeat opens
Patterns are the set's own (one loop of each track's first arrangement clip), tiled per section.
"""

from __future__ import annotations

import json

from hands.live.transport import McpTransport

LAYERS = {
    "A": ("perc 2", [60, 61]),
    "B": ("perc 1", [95]),
    "C": ("perc 2", [32, 33]),
    "D": ("perc 2", [120, 127]),
    "E": ("perc 1", [83, 117, 120]),
}

PATTERN = """
t = next(t for t in song.tracks if t.name == NAME)
c = t.arrangement_clips[0]
result = [c.loop_end - c.loop_start, [[n.pitch, n.start_time - c.loop_start, n.duration, n.velocity]
          for n in c.get_notes_extended(0, 128, c.loop_start, c.loop_end - c.loop_start)]]
"""


def tracks(layers: dict = LAYERS) -> list[str]:
    return sorted({track for track, _ in layers.values()})


def patterns(client: McpTransport, layers: dict = LAYERS) -> dict[str, list]:
    """{track: [loop length, [[pitch, start, duration, velocity], ...]]} from each hat track."""
    return {name: client.run(f"NAME = {name!r}\n" + PATTERN) for name in tracks(layers)}


def tile(loop: float, notes: list, length: float, pitches: set[int]) -> list[list]:
    """The notes of `pitches` from a `loop`-beat pattern, repeated to fill `length` beats; notes
    that would run past the end are shortened."""
    out, k = [], 0
    while k * loop < length:
        for pitch, start, duration, velocity in notes:
            s = k * loop + start
            if pitch in pitches and s < length:
                out.append([pitch, s, min(duration, length - s), velocity])
        k += 1
    return out


def rewrite(client: McpTransport, sections: list[tuple[float, float, str]], pats: dict,
            layers: dict = LAYERS) -> list[tuple]:
    """Clear the hat tracks, then write one MIDI clip per track and section.

    sections: [(start_beat, length_beats, "ABC"), ...] on the current timeline; a track gets a clip
    only where one of its layers plays. Returns (track, start, length, layers, notes written).
    """
    for name in tracks(layers):
        client.run(f"""
t = next(t for t in song.tracks if t.name == {name!r})
for c in list(t.arrangement_clips):
    t.delete_clip(c)
result = len(t.arrangement_clips)
""")
    made = []
    for start, length, section in sections:
        for name in tracks(layers):
            pitches = {p for layer in section if layers[layer][0] == name for p in layers[layer][1]}
            if not pitches:
                continue
            loop, notes = pats[name]
            n = client.run(f"""
import Live
t = next(t for t in song.tracks if t.name == {name!r})
c = t.create_midi_clip({float(start)}, {float(length)})
NOTES = {json.dumps(tile(loop, notes, length, pitches))}
c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v, mute=False) for p, s, d, v in NOTES))
c.name = {section!r}
result = len(c.get_notes_extended(0, 128, 0, {float(length)}))
""")
            made.append((name, start, length, section, n))
    return made
