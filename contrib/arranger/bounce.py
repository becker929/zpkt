"""Bounce HW002's loops from Live: one Main export per solo state, to ~/_agent_scratch/arranger/raw/stems.

Each state solos one or more tracks, so the file is what the set plays when only they sound: through their own
devices, their group's devices and Main. Run from hands' environment, one state at a time or all:

    uv run --project hands python contrib/arranger/bounce.py [state ...]

Exports go through hands/scripts/rummage/liveops.py (menu clicks and accessibility, no keystrokes: a macOS
permission prompt on screen takes every key). Stops at the first surprise.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("~/_agent_scratch/arranger/raw").expanduser()
SET = "HW002_121_pp_loops"
os.environ["ZPKT_SETS_DIR"] = str(Path("~/_agent_scratch/HW002").expanduser())
os.environ["ZPKT_SET_PREFIXES"] = "HW002_121_pp_"
os.environ["ZPKT_DATA_DIR"] = str(OUT / "data")
os.environ["ZPKT_RENDERS_DIR"] = str(OUT)
sys.path.insert(0, str(ROOT / "hands" / "scripts" / "rummage"))
import liveops  # noqa: E402

liveops.EXPORT_DIR = OUT

SONG = (0.0, 720.0)      # beats: the 176 bars and a 4-bar tail
BREAK = (320.0, 80.0)    # the break (bars 81-96) and a 4-bar tail
# state -> (track indices soloed, (start beat, length in beats)); no solo = the mix
STATES = {
    "mix": ((), SONG),
    "kick-rumble": ((2, 3), SONG),
    "kick": ((2,), SONG),
    "rumble": ((3,), SONG),
    "crash": ((5,), SONG),
    "perc1": ((6,), SONG),
    "perc2": ((7,), SONG),
    "splash": ((9,), SONG),
    "chord": ((11,), SONG),
    "break": ((13, 14, 15, 16, 17), BREAK),
    "break-hit": ((13,), BREAK),
    "break-stab": ((14,), BREAK),
    "break-horn": ((15,), BREAK),
    "break-chop": ((16,), BREAK),
    "break-beatbox": ((17,), BREAK),
}


def solo(indices: tuple[int, ...]) -> None:
    liveops.run(f"for i, t in enumerate(song.tracks):\n    t.solo = i in {set(indices) or set()!r}\nresult = 'ok'"
                .replace("set()", "()"))
    time.sleep(0.3)
    got = tuple(liveops.run("result = [i for i, t in enumerate(song.tracks) if t.solo]"))
    if got != tuple(indices):
        sys.exit(f"STOP: soloed {got}, wanted {indices}")


def main(names: list[str]) -> None:
    for name in names or list(STATES):
        indices, (start, length) = STATES[name]
        out = OUT / "stems" / f"{name}.wav"
        if out.exists():
            print(f"{name}: already there", flush=True)
            continue
        if liveops.guard(f"bounce {name}") != SET:
            sys.exit(f"STOP: {SET} is not in front")
        solo(indices)
        t0 = time.time()
        liveops.export(out, start, length, bits=24, timeout_s=600)
        print(f"{name}: {out.stat().st_size / 1e6:.1f} MB in {time.time() - t0:.0f} s", flush=True)
    solo(())


if __name__ == "__main__":
    main(sys.argv[1:])
