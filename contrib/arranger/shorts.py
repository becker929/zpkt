"""Six one-minute arrangements (40 bars at 160 BPM) for the arranger, in the shape of a Klangkuenstler short:
breakdown first, a build to the drop, at least 16 bars of peak, then 4-16 bars of more peak or an outro.

    python3 contrib/arranger/shorts.py      # writes short-1 ... short-6 into the arranger's arrangements folder

Bars below are 1-based and inclusive, as the page shows them. Clip ids are the ones in loops.json.
"""
from __future__ import annotations

import json
import sys
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
    # In every one the kick group stays out until the drop (Anthony, 11 Nov 2026): a build is hats, chord and break
    # parts, never the scooped kick.
    "1 Song shape": [  # the song's own break, squeezed: 8 break, 4 build, 16 peak, 12 thinning out
        ("break", "break-a", 1, 5), ("break", "break-b", 6, 8),
        ("break", "break-d", 9, 12), ("perc1", "perc1-a", 9, 12),
        *peak(13, 28), ("splash", "splash-c", 21, 24),
        ("kick", "kick-rumble-a", 29, 40), ("chord", "chord-a", 29, 40), ("crash", "crash-b", 29, 29),
        ("perc1", "perc1-d", 29, 32), ("perc2", "perc2-e", 29, 32), ("perc1", "perc1-g", 33, 40),
    ],
    "2 Long horn break": [  # 12 bars of break led by the horn, 4 of build, 16 peak, 8 outro
        ("break-horn", "break-horn-a", 1, 8), ("break-chop", "break-chop-a", 1, 4), ("break-chop", "break-chop-b", 5, 12),
        ("break-stab", "break-stab-b", 5, 16), ("break-horn", "break-horn-b", 9, 14), ("break-beatbox", "break-beatbox-b", 9, 16),
        ("break-horn", "break-horn-c", 15, 16), ("perc1", "perc1-b", 13, 16),
        *peak(17, 32), ("splash", "splash-c", 25, 28),
        ("kick", "kick-rumble-a", 33, 40), ("perc1", "perc1-c", 33, 40), ("chord", "chord-a", 33, 40), ("crash", "crash-b", 33, 33),
    ],
    "3 Short break, long build": [  # 4 break, 8 build (chord in, hats step up, beatbox joins), 16 peak, 12 more
        ("break-stab", "break-stab-a", 1, 2), ("break-stab", "break-stab-b", 3, 12), ("break-chop", "break-chop-a", 1, 4),
        ("break-chop", "break-chop-b", 5, 12), ("chord", "chord-a", 5, 12), ("perc1", "perc1-a", 5, 8), ("perc1", "perc1-b", 9, 12),
        ("break-beatbox", "break-beatbox-b", 9, 12),
        *peak(13, 28),
        *peak(29, 40, perc2="perc2-d", splash="splash-c"),
    ],
    "4 Hat ladder": [  # 8 break, 4 build, then the hats climb every 4 bars under the kick: A, B, C, D
        ("break", "break-a", 1, 5), ("break", "break-b", 6, 8),
        ("break-stab", "break-stab-b", 9, 12), ("break-chop", "break-chop-b", 9, 12),
        ("kick", "kick-rumble-a", 13, 40), ("splash", "splash-d", 13, 16), ("crash", "crash-b", 13, 13),
        ("perc1", "perc1-a", 13, 16), ("perc1", "perc1-b", 17, 20), ("perc1", "perc1-c", 21, 24), ("perc1", "perc1-d", 25, 40),
        ("perc2", "perc2-b", 21, 24), ("perc2", "perc2-e", 25, 40), ("splash", "splash-c", 21, 24), ("chord", "chord-a", 21, 40),
        ("crash", "crash-b", 25, 25),
    ],
    "5 Silent bar, kick alone": [  # 8 break, 3 build, 1 bar of nothing, kick alone for 4, then all of it; rumble outro
        ("break-horn", "break-horn-a", 1, 8), ("break-beatbox", "break-beatbox-a", 1, 5), ("break-beatbox", "break-beatbox-b", 6, 11),
        ("break-stab", "break-stab-b", 9, 10), ("perc1", "perc1-a", 9, 11),
        ("kick", "kick-a", 13, 16), ("perc1", "perc1-c", 13, 16), ("splash", "splash-d", 13, 16), ("crash", "crash-b", 13, 13),
        *peak(17, 32, splash="splash-c"),
        ("kick", "rumble-a", 33, 40), ("chord", "chord-a", 33, 40), ("perc1", "perc1-g", 33, 40),
    ],
    "6 Late drop": [  # 8 break, 8 build that keeps adding (stab, beatbox, hats, chord, horn), 16 peak, 8 out
        ("break-horn", "break-horn-a", 1, 8), ("break-chop", "break-chop-a", 1, 8),
        ("break-stab", "break-stab-b", 9, 16), ("break-beatbox", "break-beatbox-b", 9, 16), ("chord", "chord-a", 9, 16),
        ("perc1", "perc1-a", 9, 12), ("perc1", "perc1-b", 13, 16), ("break-horn", "break-horn-b", 13, 16),
        *peak(17, 32),
        ("kick", "kick-rumble-a", 33, 40), ("perc1", "perc1-g", 33, 40), ("chord", "chord-a", 33, 40),
    ],
    # Maximal variants of "2 Long horn break" (the parent): same 12 / 4 / 16 / 8 shape, every spare sound used.
    "7 Long horn, everything": [
        # break: the parent's horn, chop and stab, plus the game snippets, the hit, the whole beatbox and a quiet closed hat
        ("break-horn", "break-horn-a", 1, 8), ("break-chop", "break-chop-a", 1, 4), ("break-chop", "break-chop-b", 5, 12),
        ("break-stab", "break-stab-a", 1, 2), ("break-stab", "break-stab-b", 5, 16),
        ("break-beatbox", "break-beatbox-a", 1, 5), ("break-beatbox", "break-beatbox-b", 6, 16),
        ("splash", "splash-b", 1, 5), ("splash", "splash-c", 9, 12),   # not the hit: on top of the horn and beatbox it took the sum over full scale
        ("p1-ch", "p1-ch-a", 5, 12), ("chord", "chord-a", 9, 16), ("break-horn", "break-horn-b", 9, 14),
        # build: single hat pads stack up, the last horn phrase
        ("p1-ch", "p1-ch-b", 13, 16), ("p1-oh", "p1-oh-b", 13, 16), ("p2-ch27", "p2-ch27-a", 13, 16),
        ("p2-rd2", "p2-rd2-a", 15, 16), ("p1-rd", "p1-rd-a", 15, 16), ("break-horn", "break-horn-c", 15, 16),
        # peak: everything, then the horn and stab come back over it
        *peak(17, 32), ("crash", "crash-b", 25, 25),
        ("break-horn", "break-horn-b", 25, 32), ("break-stab", "break-stab-b", 25, 32),
        # out: still at peak, chop on top, the song's closing splash
        ("kick", "kick-rumble-a", 33, 40), ("perc1", "perc1-d", 33, 40), ("perc2", "perc2-d", 33, 40), ("chord", "chord-a", 33, 40),
        ("break-chop", "break-chop-b", 33, 40), ("crash", "crash-b", 33, 33), ("splash", "splash-c", 33, 36), ("splash", "splash-e", 37, 40),
    ],
    "8 Long horn, hats by hand": [
        # the hats are built from the nine single pads instead of the two mixed hat tracks: 2 in the break, 5 by the
        # drop, all 9 for the second half of the peak
        ("break-horn", "break-horn-a", 1, 8), ("break-chop", "break-chop-a", 1, 4), ("break-chop", "break-chop-b", 5, 12),
        ("break-stab", "break-stab-b", 5, 16), ("break-horn", "break-horn-b", 9, 14), ("break-beatbox", "break-beatbox-b", 9, 16),
        ("break-horn", "break-horn-c", 15, 16), ("splash", "splash-b", 1, 5), ("splash", "splash-c", 9, 12),
        ("p1-ch", "p1-ch-a", 5, 8), ("p1-ch", "p1-ch-b", 9, 40), ("p2-ch27", "p2-ch27-a", 9, 40),
        ("p1-oh", "p1-oh-b", 13, 40), ("p2-rd2", "p2-rd2-a", 13, 32), ("p1-rd", "p1-rd-a", 15, 32),
        ("kick", "kick-rumble-a", 17, 40), ("chord", "chord-a", 17, 40), ("splash", "splash-d", 17, 20), ("crash", "crash-b", 17, 17),
        ("p1-oh66", "p1-oh66-c", 25, 32), ("p2-oh", "p2-oh-b", 25, 32), ("p2-rd1", "p2-rd1-a", 25, 32), ("p2-ch1", "p2-ch1-a", 25, 32),
        ("splash", "splash-c", 25, 28), ("crash", "crash-b", 25, 25),
        ("break-horn", "break-horn-b", 33, 40), ("crash", "crash-b", 33, 33), ("splash", "splash-e", 37, 40),
    ],
}


def main() -> None:
    clips = {c["id"]: c for c in json.loads((DATA / "loops.json").read_text())["clips"]}
    folder = DATA / "arrangements"
    folder.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])                                               # e.g. "7 8": write just those tabs
    for i, (name, rows) in enumerate(SHORTS.items(), 1):
        if only and str(i) not in only:
            continue
        regions = []
        drop = min(a for _, clip, a, _ in rows if clip == "splash-d")      # the drop is where the long splash lands
        assert all(a >= drop for lane, _, a, _ in rows if lane == "kick"), f"{name}: the kick comes in before the drop"
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
