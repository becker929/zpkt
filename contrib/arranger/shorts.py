"""Six one-minute arrangements (40 bars at 160 BPM) for the arranger, in the shape of a Klangkuenstler short:
breakdown first, a build to the drop, at least 16 bars of peak, then 4-16 bars of more peak or an outro.

    python3 contrib/arranger/shorts.py      # writes short-1 ... short-6 into the arranger's arrangements folder

Bars below are 1-based and inclusive, as the page shows them. Clip ids are the ones in loops.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

DATA = Path("~/_agent_scratch/arranger").expanduser()
BARS = 40


def peak(a: int, b: int, *, perc1: str = "perc1-d", perc2: str | None = "perc2-e", chord: bool = True, splash: str | None = "splash-d",
         kick: str = "kick-rumble-a") -> list[tuple]:
    out = [("kick", kick, a, b), ("perc1", perc1, a, b)]
    if perc2:
        out.append(("perc2", perc2, a, b))
    if chord:
        out.append(("chord", "chord-a", a, b))
    if splash:
        out += [("splash", splash, a, a + 3), ("crash", "crash-b", a, a)]
    return out


SHORTS = {
    "1 Song shape": [  # the song's own break and scoop, squeezed: 8 break, 4 build, 16 peak, 12 thinning out
        ("break", "break-a", 1, 5), ("break", "break-b", 6, 8),
        ("break", "break-d", 9, 10), ("kick", "kick-rumble-b", 9, 12), ("perc1", "perc1-a", 9, 12),   # the break thins before the drop
        *peak(13, 28), ("splash", "splash-c", 21, 24),
        ("kick", "kick-rumble-a", 29, 40), ("chord", "chord-a", 29, 40), ("crash", "crash-b", 29, 29),
        ("perc1", "perc1-d", 29, 32), ("perc2", "perc2-e", 29, 32), ("perc1", "perc1-g", 33, 40),
    ],
    "2 Long horn break": [  # 12 bars of break led by the horn, 4 of build, 16 peak, 8 outro
        ("break-horn", "break-horn-a", 1, 8), ("break-chop", "break-chop-a", 1, 4), ("break-chop", "break-chop-b", 5, 12),
        ("break-stab", "break-stab-b", 5, 12), ("break-horn", "break-horn-b", 9, 12), ("break-beatbox", "break-beatbox-b", 9, 12),
        ("kick", "kick-b", 13, 16), ("break-horn", "break-horn-c", 15, 16), ("perc1", "perc1-b", 13, 16),
        *peak(17, 32), ("splash", "splash-c", 25, 28),
        ("kick", "kick-rumble-a", 33, 40), ("perc1", "perc1-c", 33, 40), ("chord", "chord-a", 33, 40), ("crash", "crash-b", 33, 33),
    ],
    "3 Short break, long build": [  # 4 break, 8 build (kick alone scooped, then with rumble; hats step up), 16 peak, 12 more
        ("break-stab", "break-stab-a", 1, 2), ("break-stab", "break-stab-b", 3, 4), ("break-chop", "break-chop-a", 1, 4),
        ("kick", "kick-b", 5, 8), ("kick", "kick-rumble-b", 9, 12), ("perc1", "perc1-a", 5, 8), ("perc1", "perc1-b", 9, 12),
        ("break-beatbox", "break-beatbox-b", 9, 12),
        *peak(13, 28),
        *peak(29, 40, perc2="perc2-d", splash="splash-c"),
    ],
    "4 Hat ladder": [  # 8 break, 4 scoop, then the hats climb every 4 bars under the kick: A, B, C, D
        ("break", "break-a", 1, 5), ("break", "break-b", 6, 8),
        ("kick", "kick-rumble-b", 9, 12), ("break-stab", "break-stab-b", 9, 10),
        ("kick", "kick-rumble-a", 13, 40), ("splash", "splash-d", 13, 16), ("crash", "crash-b", 13, 13),
        ("perc1", "perc1-a", 13, 16), ("perc1", "perc1-b", 17, 20), ("perc1", "perc1-c", 21, 24), ("perc1", "perc1-d", 25, 40),
        ("perc2", "perc2-b", 21, 24), ("perc2", "perc2-e", 25, 40), ("splash", "splash-c", 21, 24), ("chord", "chord-a", 21, 40),
        ("crash", "crash-b", 25, 25),
    ],
    "5 Silent bar, kick alone": [  # 8 break, 3 build, 1 bar of nothing, kick alone for 4, then all of it; rumble outro
        ("break-horn", "break-horn-a", 1, 8), ("break-beatbox", "break-beatbox-a", 1, 5), ("break-beatbox", "break-beatbox-b", 6, 8),
        ("kick", "kick-rumble-b", 9, 11), ("break-stab", "break-stab-b", 9, 10),
        ("kick", "kick-a", 13, 16), ("perc1", "perc1-c", 13, 16), ("splash", "splash-d", 13, 16), ("crash", "crash-b", 13, 13),
        *peak(17, 32, splash="splash-c"),
        ("kick", "rumble-a", 33, 40), ("chord", "chord-a", 33, 40), ("perc1", "perc1-g", 33, 40),
    ],
    "6 Fake drop": [  # 4 break, 4 build, 8 of a lighter peak, 4 back in the break, then 16 of full peak and 4 out
        ("break-stab", "break-stab-a", 1, 2), ("break-stab", "break-stab-b", 3, 4), ("break-chop", "break-chop-a", 1, 4),
        ("kick", "kick-rumble-b", 5, 8), ("perc1", "perc1-a", 5, 8),
        *peak(9, 16, perc1="perc1-c", perc2="perc2-b", chord=False, splash="splash-c"),
        ("break", "break-d", 17, 20), ("kick", "kick-rumble-b", 19, 20), ("chord", "chord-a", 17, 20),
        *peak(21, 36),
        ("kick", "kick-rumble-a", 37, 40), ("perc1", "perc1-g", 37, 40), ("chord", "chord-a", 37, 40),
    ],
}


def main() -> None:
    clips = {c["id"]: c for c in json.loads((DATA / "loops.json").read_text())["clips"]}
    folder = DATA / "arrangements"
    folder.mkdir(parents=True, exist_ok=True)
    for i, (name, rows) in enumerate(SHORTS.items(), 1):
        regions = []
        for lane, clip, a, b in rows:
            c = clips[clip]
            assert c["lane"] == lane and 1 <= a <= b <= BARS, (name, lane, clip, a, b)
            for r in regions:   # one clip at a time on a lane
                assert r["lane"] != lane or r["start"] + r["len"] <= a - 1 or r["start"] >= b, (name, lane, clip, a, b)
            regions.append({"lane": lane, "clip": clip, "start": a - 1, "len": b - a + 1, "off": 0})
        (folder / f"short-{i}.json").write_text(json.dumps({"name": name, "bars": BARS, "regions": regions, "mutes": [], "saved": time.time()}))
        print(f"short-{i}: {name}, {len(regions)} regions")


if __name__ == "__main__":
    main()
