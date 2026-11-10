"""Base ProjectConfig for the one-instrument sweep spike (§5 #2).

ONE instrument, ONE continuous knob. This module only describes the *static*
instrument — a single sampled kick on a Drum Rack with a 4-on-4 MIDI clip.
The sweep itself (stepping the knob, bouncing, measuring) lives in
`run_sweep.py`, because `ProjectConfig` has no sweep primitive: it is a
declarative snapshot of one project state, not a parameter trajectory.

Track layout produced by ProjectBuilder for this config:
    track 0  "1-ref_kick"  (audio, empty reference slot)
    track 1  "3-Kick"      (midi)  -> devices[0] = Drum Rack
                                       drum_pads[36].chains[0].devices[0] = Simpler

So the swept Simpler lives at:
    song.tracks[1].devices[0].drum_pads[36].chains[0].devices[0]
and the swept knob is the Simpler `Transpose` parameter (semitones, direct).

Run `python base_kick.py --dump-json base_kick.json` to emit the JSON that
`hands build --config base_kick.json` consumes.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from hands.models import KickConfig, MidiNote, MidiPattern, ProjectConfig, SamplePad

# The drum-rack MIDI note the kick sits on (C1). Keep in sync with the sweep
# spec's `note` field and the device_expr `drum_pads[36]`.
KICK_NOTE = 36

# A sample that resolves to exactly one hit on THIS machine (Live 12 Suite core
# library). `find_item(browser.samples, ...)` matches by substring; the ".wav"
# suffix keeps it unambiguous vs. "Kick 49 Hz Processed.wav". A 49 Hz sub kick
# is a good fit for the pitch -> sub_share hypothesis. (The prior value,
# "VEC2 Bassdrums Clubby 001", is not installed here.)
KICK_SAMPLE = "Kick 49 Hz.wav"


def build_config() -> ProjectConfig:
    """Build the static one-kick project the sweep runs against."""
    pad = SamplePad(note=KICK_NOTE, name=KICK_SAMPLE)
    return ProjectConfig(
        name="Kick Pitch Sweep - base",
        tempo=130.0,
        kick=KickConfig(
            # `samples` gates track creation in ProjectBuilder; `main` is the
            # pad actually loaded. Both must be set for the kick track to exist.
            samples=(pad,),
            main=pad,
            midi=MidiPattern(
                name="kick_4on4",
                length_beats=4.0,
                notes=tuple(
                    MidiNote(pitch=KICK_NOTE, time=float(i), duration=0.25, velocity=100)
                    for i in range(4)
                ),
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-json",
        metavar="PATH",
        help="Write the ProjectConfig JSON to PATH (for `hands build --config`).",
    )
    args = parser.parse_args()

    cfg = build_config()
    if args.dump_json:
        Path(args.dump_json).write_text(cfg.model_dump_json(indent=2))
        print(f"Wrote {args.dump_json}")
    else:
        print(cfg.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
