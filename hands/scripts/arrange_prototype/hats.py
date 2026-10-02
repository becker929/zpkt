"""Rewrite the hat parts (perc 1, perc 2) as sections of accumulating layers.

Each layer is a set of drum-rack pads with its own rhythm and register:
  A  perc 2  OH main + OH layer   loud offbeat open hats
  B  perc 1  CH                   accented 16th closed hat
  C  perc 2  RD1 + RD2            loud 8th rides
  D  perc 2  VEC1 CH 27 + CH1     bright 16th closed hats
  E  perc 1  RD + OH + VEC1 OH    quiet 8th ride, soft offbeat opens
Patterns are the set's own (one loop of each track's clip), tiled per section.
"""
import json

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


def patterns(r):
    out = {}
    for name in ("perc 1", "perc 2"):
        out[name] = r(f"NAME = {name!r}\n" + PATTERN)
    return out


def rewrite(r, sections, pats):
    """sections: [(start_beat, length_beats, "ABC"), ...] on the current timeline."""
    for name in ("perc 1", "perc 2"):
        r(f"""
t = next(t for t in song.tracks if t.name == {name!r})
for c in list(t.arrangement_clips):
    t.delete_clip(c)
result = len(t.arrangement_clips)
""")
    made = []
    for start, length, layers in sections:
        for name in ("perc 1", "perc 2"):
            pitches = sorted({p for L in layers for (trk, ps) in [LAYERS[L]] if trk == name for p in ps})
            if not pitches:
                continue
            loop, notes = pats[name]
            tiled = []
            k = 0
            while k * loop < length:
                for p, st, du, ve in notes:
                    s = k * loop + st
                    if p in pitches and s < length:
                        tiled.append([p, s, min(du, length - s), ve])
                k += 1
            n = r(f"""
import Live
t = next(t for t in song.tracks if t.name == {name!r})
c = t.create_midi_clip({float(start)}, {float(length)})
NOTES = {json.dumps(tiled)}
c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v, mute=False) for p, s, d, v in NOTES))
c.name = {layers!r}
result = len(c.get_notes_extended(0, 128, 0, {float(length)}))
""")
            made.append((name, start, length, layers, n))
    return made
