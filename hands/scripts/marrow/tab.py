"""Marrow (Meshuggah, Koloss, 2012) as notes: Songsterr's transcription, read from the local copy.

The transcription is not in this repo. `fetch` downloads it into ~/_agent_scratch/marrow/tab/ (part0.json ...
part7.json, the Songsterr revision named below); everything else reads it from there.

  cd hands && uv run python scripts/marrow/tab.py fetch      # once
  cd hands && uv run python scripts/marrow/tab.py show 1 9 16 # part 1, measures 9-16, as note names

The song is 150 BPM in 4/4, 209 measures (334.4 s; the band's upload on YouTube is 335.1 s). Eight parts:
0, 2 the intro guitars; 1, 3 the two rhythm guitars (Thordendal, Hagström); 4 the bass (Lövgren); 5 the drums
(Haake, General MIDI note numbers); 6 the solo; 7 the "FX" layer (the low dyads and the second solo's line).
Guitars are eight-string, F standard (low F1 = MIDI 29).

A note is (beat, pitch, beats, flags): beats are quarter notes from the song's start, so an eighth is 0.5.
"""
from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction as F
from functools import cache
from pathlib import Path

TAB = Path("~/_agent_scratch/marrow/tab").expanduser()
SONG, REVISION, IMAGE = 385274, 7918175, "v0-3-2-nzPUk5VV_893EYmS"
PARTS = 8
TUPLET = {3: 2, 5: 4, 6: 4, 7: 4, 9: 8, 10: 8, 11: 8, 12: 8}   # n notes in the time of TUPLET[n]


def fetch() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    for i in range(PARTS):
        url = f"https://dqsljvtekg760.cloudfront.net/{SONG}/{REVISION}/{IMAGE}/{i}.json"
        subprocess.run(["curl", "-sS", "--compressed", "-m", "30", "-o", str(TAB / f"part{i}.json"), url], check=True)
        d = json.loads((TAB / f"part{i}.json").read_text())
        print(i, d["name"], len(d["measures"]), "measures")


@cache
def part(i: int) -> tuple[tuple, ...]:
    """Part i's notes, sorted, ties merged."""
    d = json.loads((TAB / f"part{i}.json").read_text())
    tuning = d.get("tuning")
    notes, held = [], {}
    pos, sig = F(0), (4, 4)
    for m in d["measures"]:
        sig = tuple(m.get("signature", sig))
        for vi, v in enumerate(m["voices"]):
            t = pos
            for b in v["beats"]:
                dur = F(b["duration"][0], b["duration"][1]) * 4
                dur *= {0: 1, 1: F(3, 2), 2: F(7, 4)}[b.get("dots", 0)]
                if b.get("tuplet"):
                    dur *= F(TUPLET.get(b["tuplet"], b["tuplet"]), b["tuplet"])
                for n in b["notes"] if not b.get("rest") else []:
                    if n.get("rest") or "fret" not in n:
                        continue
                    pitch = tuning[n["string"]] + n["fret"] if tuning else n["fret"]   # drums: fret is the GM note
                    flags = frozenset(k for k in ("dead", "ghost", "slide", "hp", "bend") if n.get(k))
                    if n.get("tie") and (vi, pitch) in held:
                        held[(vi, pitch)][2] += dur
                        continue
                    ev = [t, pitch, dur, flags]
                    notes.append(ev)
                    held[(vi, pitch)] = ev
                t += dur
        pos += F(sig[0] * 4, sig[1])
    return tuple(sorted(((float(a), p, float(c), f) for a, p, c, f in notes), key=lambda n: (n[0], n[1])))


def window(i: int, m0: int, m1: int) -> list[tuple]:
    """Part i's notes in measures m0..m1 (1-based, inclusive), with beats from the window's start."""
    lo, hi = (m0 - 1) * 4.0, m1 * 4.0
    return [(b - lo, p, min(d, hi - b), f) for b, p, d, f in part(i) if lo <= b < hi]


NAMES = "C C# D D# E F F# G G# A A# B".split()


def name(p: int) -> str:
    return f"{NAMES[p % 12]}{p // 12 - 1}"


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    if cmd == "fetch":
        fetch()
    elif cmd == "show":
        i, m0, m1 = (int(x) for x in rest)
        for b, p, d, f in window(i, m0, m1):
            print(f"m{m0 + int(b // 4):3d} {(b % 4) * 2:5.2f}e  {name(p):4s} {d * 2:5.2f}e  {' '.join(sorted(f))}")
    else:
        print(__doc__)
