"""One-minute arrangements (40 bars at 160 BPM) for the arranger, in the shape of a Klangkuenstler short: breakdown
first, a build to the drop, at least 16 bars of peak, then 4-16 bars of more peak or an outro.

    python3 contrib/arranger/shorts.py            # writes the variation tabs (8d1 ...); tab 8d itself only when named
    python3 contrib/arranger/shorts.py 8d 8d1     # writes just those; this overwrites edits made in the page

"8d Ramp: from the bottom up" is the parent (Anthony, 12 Nov 2026: "8d is the best"); tab 8 and the ramps 8a-8c are
gone (git history has them). The others here are 8d with its high-frequency ramp opened on a different pad. The page
has no gain or filter, so a ramp is only which hat pads play when. `measure.py` prints each tab's level above 6 kHz
bar by bar.

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

# The nine hat pads, with their level above 6 kHz (dB, one bar, from measure.py --clips) and where their weight sits.
CH_A = ("p1-ch", "p1-ch-a")          # -48, the quiet closed hat, darkest
CH = ("p1-ch", "p1-ch-b")            # -44, the same pad, full
OH = ("p1-oh", "p1-oh-b")            # -42
CH27 = ("p2-ch27", "p2-ch27-a")      # -41, thin and high
RD1 = ("p2-rd1", "p2-rd1-a")         # -41, the airiest pad
OH66 = ("p1-oh66", "p1-oh66-c")      # -40
OH2 = ("p2-oh", "p2-oh-b")           # -39
RD2 = ("p2-rd2", "p2-rd2-a")         # -36
RD = ("p1-rd", "p1-rd-a")            # -35
CH1 = ("p2-ch1", "p2-ch1-a")         # -34, the loudest


def hats(*rows: tuple) -> list[tuple]:
    """(pad, first bar, last bar) -> region rows."""
    return [(*pad, a, b) for pad, a, b in rows]


SHORTS = {
    "8d": ("8d Ramp: from the bottom up", [   # the parent: pads enter in order of pitch, not level, the airiest last
        *BASE,
        *hats((CH_A, 5, 8), (CH, 9, 40), (OH, 13, 40), (OH66, 17, 40), (OH2, 17, 40), (CH1, 21, 40), (RD2, 25, 40),
              (RD, 29, 40), (CH27, 33, 40), (RD1, 37, 40)),
    ]),
    # 8d's variations: the same climb, but the ramp does not open on P1 closed (Anthony, 12 Nov 2026). Each opens on a
    # different pad, one more pad every 4 bars from there; P1 closed comes in at the drop or not at all.
    "8d1": ("8d1 Opens on P1 open", [   # the darkest open hat starts it; P1 closed only joins under the drop
        *BASE,
        *hats((OH, 5, 40), (OH66, 9, 40), (OH2, 13, 40), (CH, 17, 40), (CH1, 21, 40), (RD2, 25, 40), (RD, 29, 40),
              (CH27, 33, 40), (RD1, 37, 40)),
    ]),
    "8d2": ("8d2 Opens on P1 open 2, no P1 closed", [   # the soft open hat with the least above 10 kHz starts it
        *BASE,
        *hats((OH66, 5, 40), (OH, 9, 40), (OH2, 13, 40), (CH27, 17, 40), (CH1, 21, 40), (RD2, 25, 40), (RD, 29, 40),
              (RD1, 37, 40)),
    ]),
    "8d3": ("8d3 Opens on P2 closed 2, no P1 closed", [   # a thin, high tick starts it instead of a dark one
        *BASE,
        *hats((CH27, 5, 40), (OH, 9, 40), (OH66, 13, 40), (OH2, 17, 40), (CH1, 21, 40), (RD2, 25, 40), (RD, 29, 40),
              (RD1, 37, 40)),
    ]),
    "8d4": ("8d4 Opens on P2 ride 1, no P1 closed", [   # the airiest pad, quiet low down, starts it as a shimmer
        *BASE,
        *hats((RD1, 5, 40), (OH, 9, 40), (OH66, 13, 40), (OH2, 17, 40), (CH1, 21, 40), (RD2, 25, 40), (RD, 29, 40),
              (CH27, 37, 40)),
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
    for key in sys.argv[1:] or [k for k in reversed(SHORTS) if k != "8d"]:   # the page lists the newest first
        name, regions = regions_of(key, clips)
        (folder / f"short-{key}.json").write_text(json.dumps({"name": name, "bars": BARS, "regions": regions, "mutes": [], "saved": time.time()}))
        print(f"short-{key}: {name}, {len(regions)} regions")


if __name__ == "__main__":
    main()
