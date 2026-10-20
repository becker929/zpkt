"""4x4x4's own sounds (anthonybecker.me demo 13), on top of Four by Four's kit, which it plays from R2 as is. Same
layers and roles as Juice Box (make.py); render with `make.py <cmd> 4x4x4`.

Only what the sequel adds:
- fall-1..3: a piece dropping down its column onto the floor below: a felt thump and a low wooden body under a glass
  tick (the floors are glass), a pinch of grit after. Three pitches, walked in turn like the drops.
- morph: Turncoat, a piece becoming what it took: a shaker swish, a wooden clack, and celeste stepping up a fifth to
  an octave, with a music box on top.
- act: the large numeral of a new act: a low bell with its fifth, a soft kick and a long sine under it, paper air,
  one high glint.
"""
from layers import N, S


def sounds() -> dict:
    out = {}
    for k, st in enumerate((-4, -2, 0)):
        out[f"fall-{k + 1}"] = [
            S("thump", "Kick Felt Crack.wav", 0, -8, st - 3), S("wood", "Wood Rough Low.aif", 0, -6, st),
            S("click", "Perc Glass Low.aif", 0, -14, st + 5), S("slap", "Clap Foley.aif", 0.003, -16, st),
            S("air", "Shaker Egg.aif", 0.03, -22, -6), N(31 + k, 0, 0.12, 95),
        ]
    out["morph"] = [
        S("air", "Shaker Egg.aif", 0, -12, 2), S("click", "Wood Insert Cassette.wav", 0.05, -12, 4),
        S("slap", "Perc Snap Tap.wav", 0.05, -16, 3),
        S("shine", "Celeste C6.wav", 0.06, -12, 0), S("shine", "Celeste C6.wav", 0.12, -12, 7),
        S("shine", "Music Box C4.aif", 0.18, -13, 24),
    ]
    out["act"] = [
        S("thump", "Kick Thud.aif", 0, -10, -2), N(26, 0, 0.9, 90),
        S("shine", "Bell Brooklyn C5.aif", 0, -8, -12), S("shine", "Bell Brooklyn C5.aif", 0.02, -12, -5),
        S("air", "Paper LDre.wav", 0.05, -20), S("shine", "Triangle Open.aif", 0.3, -20, 0),
    ]
    return out
