"""One-minute arrangements (40 bars at 160 BPM) for the arranger, in the shape of a Klangkuenstler short: breakdown
first, a build to the drop, at least 16 bars of peak, then 4-16 bars of more peak or an outro.

    python3 contrib/arranger/shorts.py            # writes the variation tabs (8d2a ...); tab 8d2 itself only when named
    python3 contrib/arranger/shorts.py 8d2 8d2a   # writes just those; this overwrites edits made in the page

"8d2 Opens on P1 open 2, no P1 closed" is the parent (Anthony, 12 Nov 2026: "I like 8d2 best"); 8, 8a-8d and the
other 8d variations are gone (git history has them). In 8d2 an off-beat open hat comes in, then another off-beat open
hat in the same range. Anthony wants the ramp to alternate rhythms and frequency ranges instead, so in the others each
new pad plays the other rhythm from the one before it and, where the pads allow, sits in another range. The page has
no gain or filter, so a ramp is only which hat pads play when. `measure.py` prints each tab's level above 6 kHz bar by
bar.

Bars below are 1-based and inclusive, as the page shows them. Clip ids are the ones in loops.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

DATA = Path("~/_agent_scratch/arranger").expanduser()
BARS = 40

# Tab 8 without its hats: 12 bars of break led by the horn, 4 of build, the drop at 17, the horn back from 33.
# The kick group stays out until the drop (Anthony, 11 Nov 2026): a build is hats and break parts, never the kick.
BASE = [
    ("break-horn", "break-horn-a", 1, 8), ("break-chop", "break-chop-a", 1, 4), ("break-chop", "break-chop-b", 5, 12),
    ("break-stab", "break-stab-b", 5, 16), ("break-horn", "break-horn-b", 9, 14), ("break-beatbox", "break-beatbox-b", 9, 16),
    ("break-horn", "break-horn-c", 15, 16), ("splash", "splash-b", 1, 5), ("splash", "splash-c", 9, 12),
    ("kick", "kick-rumble-a", 17, 40), ("chord", "chord-a", 17, 40), ("splash", "splash-d", 17, 20), ("crash", "crash-b", 17, 17),
    ("splash", "splash-c", 25, 28), ("crash", "crash-b", 25, 25),
    ("break-horn", "break-horn-b", 33, 40), ("crash", "crash-b", 33, 33), ("splash", "splash-e", 37, 40),
]

# The nine hat pads: level above 6 kHz (dB, one bar, measure.py --clips), rhythm and range (spectral centroid, measured
# on the loop). Two rhythms only: "off" is one hit on each off-beat 8th, "16ths" is every 16th. Ranges: low (centroid
# under 6 kHz), mid (6-7 kHz), high (over 7 kHz).
CH_A = ("p1-ch", "p1-ch-a")          # -48, off,   low  3.6k   the quiet closed hat, darkest; not a ramp opener (Anthony)
CH = ("p1-ch", "p1-ch-b")            # -44, 16ths, low  3.8k   the same pad, full
OH = ("p1-oh", "p1-oh-b")            # -42, off,   low  5.3k   the twin of OH66: same rhythm, same range
CH27 = ("p2-ch27", "p2-ch27-a")      # -41, 16ths, high 7.5k   thin, most of it 9-14 kHz
RD1 = ("p2-rd1", "p2-rd1-a")         # -41, off,   high 9.5k   a washy ride, the only pad with real air above 14 kHz
OH66 = ("p1-oh66", "p1-oh66-c")      # -40, off,   low  5.5k   opens 8d2
OH2 = ("p2-oh", "p2-oh-b")           # -39, off,   mid  6.2k
RD2 = ("p2-rd2", "p2-rd2-a")         # -36, off,   mid  6.4k   a washy ride
RD = ("p1-rd", "p1-rd-a")            # -35, 16ths, high 7.5k   a washy ride, accented
CH1 = ("p2-ch1", "p2-ch1-a")         # -34, 16ths, mid  6.4k   the loudest


def hats(*rows: tuple) -> list[tuple]:
    """(pad, first bar, last bar) -> region rows."""
    return [(*pad, a, b) for pad, a, b in rows]


SHORTS = {
    "8d2": ("8d2 Opens on P1 open 2, no P1 closed", [   # the parent: off-beat open hats stack up before anything else
        *BASE,
        *hats((OH66, 5, 40), (OH, 9, 40), (OH2, 13, 40), (CH27, 17, 40), (CH1, 21, 40), (RD2, 25, 40), (RD, 29, 40),
              (RD1, 37, 40)),
    ]),
    # 8d2's variations: still open on P1 open 2 with no P1 closed, but each new pad flips the rhythm (off <-> 16ths).
    # P1 open is left out: next to P1 open 2 it adds nothing new. With 4 off-beat pads and 3 sixteenth pads, only one
    # step in 8d2a keeps the range of the step before it (8d2b gives up two, to keep the rides last).
    "8d2a": ("8d2a Alternating, every 4 bars", [   # low off, high 16ths, mid off, high 16ths, mid off, mid 16ths, high off
        *BASE,
        *hats((OH66, 5, 40), (CH27, 9, 40), (OH2, 13, 40), (RD, 17, 40), (RD2, 21, 40), (CH1, 25, 40), (RD1, 33, 40)),
    ]),
    "8d2b": ("8d2b Alternating, closed hats before rides", [   # the tight pads first, the three washy rides last
        *BASE,
        *hats((OH66, 5, 40), (CH27, 9, 40), (OH2, 13, 40), (CH1, 17, 40), (RD1, 21, 40), (RD, 25, 40), (RD2, 33, 40)),
    ]),
    "8d2c": ("8d2c Alternating, every 8 bars", [   # fewer, further apart, every range change heard on its own
        *BASE,
        *hats((OH66, 5, 40), (CH27, 13, 40), (OH2, 21, 40), (RD, 29, 40), (RD1, 37, 40)),
    ]),
}


def regions_of(key: str, clips: dict) -> tuple[str, list[dict]]:
    name, rows = SHORTS[key]
    drop = min(a for _, clip, a, _ in rows if clip == "splash-d")      # the drop is where the long splash lands
    assert all(a >= drop for lane, _, a, _ in rows if lane == "kick"), f"{name}: the kick comes in before the drop"
    regions = []
    for lane, clip, a, b in rows:
        assert clips[clip]["lane"] == lane and 1 <= a <= b <= BARS, (name, lane, clip, a, b)
        for r in regions:   # one clip at a time on a lane
            assert r["lane"] != lane or r["start"] + r["len"] <= a - 1 or r["start"] >= b, (name, lane, clip, a, b)
        regions.append({"lane": lane, "clip": clip, "start": a - 1, "len": b - a + 1, "off": 0})
    return name, regions


def main() -> None:
    clips = {c["id"]: c for c in json.loads((DATA / "loops.json").read_text())["clips"]}
    folder = DATA / "arrangements"
    folder.mkdir(parents=True, exist_ok=True)
    for key in sys.argv[1:] or [k for k in reversed(SHORTS) if k != "8d2"]:   # the page lists the newest first
        name, regions = regions_of(key, clips)
        (folder / f"short-{key}.json").write_text(json.dumps({"name": name, "bars": BARS, "regions": regions, "mutes": [], "saved": time.time()}))
        print(f"short-{key}: {name}, {len(regions)} regions")


if __name__ == "__main__":
    main()
