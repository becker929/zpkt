"""Write a LOM snippet that puts a note list into a new looping clip, for live_step.py exec.

    run lom_clip.py recipe.json notes.bass --track "Bass Line A" > practice/snippets/bass_a.py
    run lom_clip.py recipe.json notes.perc_substitute --track "Perc Loop A" --pitch 38 > practice/snippets/perc_a.py
    run lom_clip.py practice/plan_b.json bass_b --track "Bass Line B" --length 8 > practice/snippets/bass_b.py
    run lom_clip.py recipe.json notes.kick_substitute+notes.clap_substitute+notes.hats_substitute --track Drums

KEY is a dotted path to a list of {pitch, start_beat, length_beats, velocity}; join several with +.
--pitch replaces every pitch (a Drum Rack pad). The snippet creates a --length-beat clip in session
slot --slot (refusing if the slot is taken), names it and adds every note in one add_new_notes call.
It does not read anything back: read the clip in a separate `live_step.py read` (writing and reading
in one call can crash Live).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def notes_at(doc: dict, key: str) -> list[dict]:
    v = doc
    for part in key.split("."):
        v = v[part]
    if not isinstance(v, list):
        raise SystemExit(f"{key} is not a note list")
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="recipe.json or a plan file")
    ap.add_argument("key", help="dotted path to a note list; several joined with +")
    ap.add_argument("--track", required=True)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--length", type=float, default=8.0, help="clip length, beats")
    ap.add_argument("--pitch", type=int, help="override every pitch")
    ap.add_argument("--name", help="clip name (default: '<track> loop')")
    a = ap.parse_args()

    doc = json.loads(Path(a.source).read_text())
    notes = [n for k in a.key.split("+") for n in notes_at(doc, k)]
    bad = [n for n in notes if not 0 <= n["start_beat"] < a.length]
    if bad:
        raise SystemExit(f"{len(bad)} notes fall outside a {a.length}-beat clip: {bad[:3]}")
    specs = ",\n    ".join(
        f"MidiNoteSpecification(pitch={n['pitch'] if a.pitch is None else a.pitch}, "
        f"start_time={float(n['start_beat'])}, "
        f"duration={float(n['length_beats'])}, velocity={int(n['velocity'])})" for n in notes)
    print(f"""t = find_track({a.track!r})
slot = t.clip_slots[{a.slot}]
if slot.has_clip:
    raise RuntimeError('slot {a.slot} of {a.track} already has a clip')
slot.create_clip({a.length})
c = slot.clip
c.name = {(a.name or a.track + ' loop')!r}
c.add_new_notes((
    {specs},
))
result = {{'track': t.name, 'notes_written': {len(notes)}}}""")


if __name__ == "__main__":
    main()
