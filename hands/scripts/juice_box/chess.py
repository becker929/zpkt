"""Four by Four's sounds (anthonybecker.me demo 11): toy wooden pieces on a wooden board. Same layers and roles as
Juice Box (make.py); render with `make.py <cmd> four-by-four`.

A capture is two sounds, because the page plays them at two moments: the hop as the piece leaves its square, and the
landing, which knocks the other piece off. Landings climb with the combo: the thump and the knock stay, and a music
box note rises another step each capture in a row, with jingle bells from the fourth on.
"""
from layers import N, S, SCALE


def sounds() -> dict:
    out = {
        "pick": [S("wood", "Perc Wood.aif", 0, -14, 5), S("click", "Wood Insert Cassette.wav", 0, -16, 2)],
        "nope": [S("wood", "Wood Dry Low.aif", 0, -10, -7), S("wood", "Wood Block Low.aif", 0.09, -16, -14)],
        "hop": [S("air", "Shaker Egg.aif", 0, -14, -3), S("click", "Wood Scrape.aif", 0, -18, 5)],
        "hop-knight": [S("air", "Shaker Egg.aif", 0, -14, -3), S("air", "Shaker Egg.aif", 0.12, -15, 2),
                       S("click", "Wood Scrape.aif", 0, -18, 5)],
    }
    for k in range(6):
        out[f"capture-{k + 1}"] = [
            S("thump", "Kick Felt Crack.wav", 0, -6), S("wood", "Wood Rough Low.aif", 0, -4),
            S("click", "Wood Clack.wav", 0, -6, k), S("slap", "Perc Slap 3.wav", 0, -8, k),
            S("slap", "Clap Foley.aif", 0.004, -12), N(38, 0, 0.08, 100),
        ] + ([S("shine", "Music Box C4.aif", 0.02, -13 + k, 12 + SCALE[k])] if k >= 1 else []) \
          + ([S("shine", "Chimes Jingle Bell.aif", 0.03, -16 + k)] if k >= 3 else [])
    for k, st in enumerate((-3, -1, 1)):
        out[f"drop-{k + 1}"] = [S("wood", "Perc Wood.aif", 0, -10, st), S("thump", "Kick Felt Crack.wav", 0, -20),
                                S("click", "Wood Clog Medium.wav", 0, -18, st)]
    out["solved"] = [
        S("thump", "Kick Thud.aif", 0, -6), S("slap", "Clap Foley.aif", 0, -8), S("air", "Paper LDre.wav", 0.1, -14),
        *[S("shine", "Celeste C6.wav", 0.08 * i, -8, st) for i, st in enumerate((-12, -5, 0, 4, 7, 12))],
        *[S("shine", "Bell Brooklyn C5.aif", 0.55, db, st) for db, st in ((-10, 0), (-12, 4), (-13, 7))],
        S("shine", "Chimes Jingle Bell.aif", 0.5, -8), S("shine", "Triangle Open.aif", 0.55, -14), N(33, 0, 0.3, 110),
    ]
    out["stuck"] = [
        *[S("wood", "Wood Block Low.aif", t, -8, st) for t, st in ((0, 0), (0.16, -3), (0.32, -7))],
        S("shine", "Bell Tin.wav", 0.32, -16, -12), N(36, 0.32, 0.2, 70),
    ]
    out["undo"] = [S("click", "Wood Scrape.aif", 0, -10, -3), S("wood", "Perc Wood.aif", 0.06, -12, -5),
                   S("air", "Shaker Egg.aif", 0, -18, -8)]
    out["hint"] = [S("shine", "Triangle Short.wav", 0, -12), S("shine", "Celeste C6.wav", 0, -12, 7),
                   S("shine", "Celeste C6.wav", 0.1, -12, 12), S("click", "Perc Glass Low.aif", 0, -16, 5)]
    out["click"] = [S("click", "Wood Insert Cassette.wav", 0, -10, 2), S("slap", "Perc Snap Tap.wav", 0, -18, 5)]
    return out
