"""SH001, the short The Rummage plays: the composition and the sounds, as data (make.py builds and renders it).

118 BPM, 4/4, 32 bars (about 65 s), D minor (dorian colour). An eight-bar cycle, two bars a chord:
Dm9 | G9 | Bbmaj7 | A7sus4 -> A7, three times; the last cycle turns home: Dm9 | G9 | Bbmaj7 | D(add9). The tune
runs A, A, an answer (higher, over the full groove), then A turning home.

Arrangement (the brief's): bars 1-8 the bed alone; 9-16 + drums (9-12 kick and hats, 13-16 the full kit, a fill at
16); 17-28 + bass, the full groove (extra percussion, fills at 24 and 28); 29-32 the outro: one last hit at 29, the
bass holds Bb then D, the bed rings out on D(add9).

Three parts, three options each. An option is one or two tracks; a combo un-mutes exactly its three options' tracks.
Every option plays the same harmony and the same melody contour, so any bed sits with any drums and any bass.

Sounds are Live 12 Suite's Core Library only (no purchased audio, nothing of Anthony's): presets from the browser's
Sounds, three Core Library drum kits (Kitchen Perc, Rattle, Clockwork), and Core Library samples.
"""
from __future__ import annotations

BPM = 118.0
BARS = 32
BEATS = BARS * 4

# ---- harmony -----------------------------------------------------------------------------------------------------------
CYCLE = ["Dm9", "Dm9", "G9", "G9", "Bbmaj7", "Bbmaj7", "A7sus", "A7"]
LAST = ["Dm9", "Dm9", "G9", "G9", "Bbmaj7", "Bbmaj7", "Dadd9", "Dadd9"]
CHORDS = CYCLE * 3 + LAST                     # one per bar

VOICE = {                                      # mid-register voicings, low to high
    "Dm9": [50, 53, 57, 60, 64],               # D3 F3 A3 C4 E4
    "G9": [43, 53, 57, 59, 62],                # G2 F3 A3 B3 D4
    "Bbmaj7": [46, 53, 57, 58, 62],            # Bb2 F3 A3 Bb3 D4
    "A7sus": [45, 52, 55, 57, 62],             # A2 E3 G3 A3 D4
    "A7": [45, 52, 55, 57, 61],                # A2 E3 G3 A3 C#4
    "Dadd9": [50, 53, 57, 62, 64],             # D3 F3 A3 D4 E4
}
# bass: root, fifth, seventh (the chord's own), in the second octave
BASS = {"Dm9": (38, 45, 48), "G9": (43, 38, 41), "Bbmaj7": (34, 41, 45), "A7sus": (33, 40, 43), "A7": (33, 40, 43),
        "Dadd9": (38, 45, 48)}
LOW = {"Dm9": 38, "G9": 31, "Bbmaj7": 34, "A7sus": 33, "A7": 33, "Dadd9": 38}   # D2 G1 Bb1 A1: the sub's roots

# The tune, over one cycle: (beat, pitch, length). All chord tones or colour tones of the chord under them.
MELODY = [
    (0.0, 69, 1.0), (1.0, 74, 0.5), (1.5, 76, 0.5), (2.0, 77, 1.5), (3.5, 76, 0.5),      # Dm9
    (4.0, 72, 1.0), (5.0, 69, 1.0), (6.0, 76, 2.0),
    (8.0, 74, 1.0), (9.0, 71, 0.5), (9.5, 69, 0.5), (10.0, 71, 1.5), (11.5, 74, 0.5),   # G9
    (12.0, 69, 2.0), (14.0, 77, 1.0), (15.0, 76, 1.0),
    (16.0, 74, 1.0), (17.0, 77, 0.5), (17.5, 81, 0.5), (18.0, 77, 1.5), (19.5, 74, 0.5),  # Bbmaj7
    (20.0, 72, 1.0), (21.0, 69, 1.0), (22.0, 74, 2.0),
    (24.0, 76, 1.0), (25.0, 74, 0.5), (25.5, 69, 0.5), (26.0, 67, 1.5), (27.5, 69, 0.5),  # A7sus4
    (28.0, 73, 1.0), (29.0, 76, 1.0), (30.0, 79, 1.0), (31.0, 76, 1.0),                   # A7
]
# The answer, for the third cycle (bars 17-24, the full groove): the same chords, higher and more arched.
ANSWER = [
    (0.0, 81, 1.5), (1.5, 79, 0.5), (2.0, 77, 1.0), (3.0, 76, 0.5), (3.5, 74, 0.5),      # Dm9
    (4.0, 76, 1.5), (5.5, 72, 0.5), (6.0, 69, 2.0),
    (8.0, 79, 1.5), (9.5, 77, 0.5), (10.0, 74, 1.0), (11.0, 71, 1.0),                    # G9
    (12.0, 74, 1.5), (13.5, 76, 0.5), (14.0, 77, 2.0),
    (16.0, 81, 1.5), (17.5, 82, 0.5), (18.0, 81, 1.0), (19.0, 77, 1.0),                  # Bbmaj7
    (20.0, 74, 1.5), (21.5, 72, 0.5), (22.0, 74, 2.0),
    (24.0, 76, 1.0), (25.0, 74, 1.0), (26.0, 69, 1.0), (27.0, 74, 1.0),                  # A7sus4
    (28.0, 73, 1.5), (29.5, 76, 0.5), (30.0, 79, 1.0), (31.0, 81, 1.0),                  # A7, up into the return
]
ENDING = [(24.0, 74, 6.0)]                     # the last cycle's bars 7-8 (bars 31-32): D5, held


def melody(*, lift_third_cycle: bool = False) -> list[tuple]:
    """The tune over 32 bars as (beat, pitch, length, velocity): A, A, the answer, A turning home."""
    out = []
    for c in range(4):
        base = 32.0 * c
        cycle = {2: ANSWER, 3: [n for n in MELODY if n[0] < 24.0] + ENDING}.get(c, MELODY)
        for b, p, d in cycle:
            v = 96 if b % 2 == 0 else 84
            out.append((base + b, p, d, v))
            if lift_third_cycle and c == 2 and d >= 1.0:          # a chord tone under the long notes: a lift
                under = [x + 12 * k for x in VOICE[CHORDS[int((base + b) // 4)]] for k in range(4)]
                out.append((base + b, max(x for x in under if x <= p - 3), d, v - 22))
    return out


def chord_at(beat: float) -> str:
    return CHORDS[int(beat // 4)]


# ---- beds ---------------------------------------------------------------------------------------------------------------
def music_box() -> list[tuple]:
    """Bed 1: the tune on a music box over an eighth-note arpeggio of the chord, an octave up."""
    notes = melody(lift_third_cycle=True)
    for bar in range(BARS):
        ch = CHORDS[bar]
        v = VOICE[ch]
        tones = [x + 12 for x in v[1:]]                          # F4 A4 C5 E5 for Dm9
        order = [0, 1, 2, 3, 2, 1, 0, 1] if bar % 2 == 0 else [1, 2, 3, 2, 1, 0, 1, 2]
        if bar >= 30:                                            # the ending: one slow roll, then let it ring
            if bar == 30:
                for i, t in enumerate(tones):
                    notes.append((bar * 4 + i * 0.5, t, 6.0 - i * 0.5, 62))
                notes.append((bar * 4, v[0], 7.0, 70))
            continue
        for i, k in enumerate(order):
            notes.append((bar * 4 + i * 0.5, tones[k], 0.45, 58 if i % 2 else 66))
        if bar % 2 == 0:
            notes.append((bar * 4, v[0], 3.5, 72))              # the chord's root, low, on the change
    return notes


def hiss() -> list[tuple]:
    """Bed 1's tape hiss: one held note, the sample looping, for the whole short."""
    return [(0.0, 60, 120.0, 100)]                               # its 3 s release: the tape runs out by bar 32


COMP = [(0.0, 1.4, 92), (1.5, 0.4, 72), (2.5, 1.0, 84),            # bar A of the parlour comp: (beat, length, vel)
        (4.0, 0.4, 88), (4.5, 1.0, 76), (6.0, 1.4, 86), (7.5, 0.4, 70)]


def parlour_piano() -> list[tuple]:
    """Bed 2: the old upright plays the chords in a lopsided, syncopated comp, its left hand on the root."""
    notes = []
    for cell in range(BARS // 2):
        ch = CHORDS[cell * 2]
        v = VOICE[ch]
        base = cell * 8.0
        if cell == 15:                                           # the last chord: struck once, held
            notes += [(base, p, 3.0, 80) for p in v[1:]] + [(base, v[0], 3.0, 74)]   # let go in time to ring out
            continue
        for b, d, vel in COMP:
            ch2 = chord_at(base + b)
            for p in VOICE[ch2][1:]:
                notes.append((base + b, p, d, vel))
        notes.append((base, VOICE[ch][0], 1.8, 78))
        notes.append((base + 4.0, VOICE[chord_at(base + 4)][0], 1.8, 70))
    return notes


def toy_piano() -> list[tuple]:
    """Bed 2's toy piano: the tune, slightly detuned by its chorus."""
    return [(b, p, min(d, 1.0), v - 6) for b, p, d, v in melody()]


def branches_pad() -> list[tuple]:
    """Bed 3: a pad of rustling branches holds each chord for its two bars."""
    notes = []
    for cell in range(BARS // 2):
        base = cell * 8.0
        ch = CHORDS[cell * 2]
        d = 8.0 if cell < 15 else 2.0                           # the last chord: struck, released, its tail inside bar 32
        notes += [(base, p, d - 0.05, 86) for p in VOICE[ch]]
        if CHORDS[cell * 2 + 1] != ch:                           # A7sus4 -> A7: move the one note that changes
            for p in set(VOICE[CHORDS[cell * 2 + 1]]) - set(VOICE[ch]):
                notes.append((base + 4.0, p, 3.95, 86))
    return notes


def tin_bowl() -> list[tuple]:
    """Bed 3's tin bowl: the tune at half speed, its notes on the half bar."""
    notes = []
    for b, p, d, v in melody():
        if b % 2 == 0 and b < 120:
            notes.append((b, p, 1.9, v))
    notes.append((120.0, 74, 4.0, 90))
    return notes


# ---- drums --------------------------------------------------------------------------------------------------------------
# A pattern is {pad: "16 steps per bar, bars split by |"}: x accent, o normal, g ghost, . rest. A drum option has: intro
# (bars 9-12), main (13-28), extra (layered on 17-28), fill (one bar, at 16, 24 and 28), end (hits on bar 29's
# downbeat). Steps are 16ths, or triplet eighths when the option says grid=12.
VEL = {"x": 112, "o": 88, "g": 52}

DRUMS = {
    1: {  # Rattle Kit: tin, slaps and a wooden box, a broken beat
        "grid": 16, "late": 0.03,
        "intro": {44: "x.....x...x.....|x..x......x.....", 43: "..o...o.g.o...o.|..o.g.o...o...og"},
        "main": {44: "x.....x...x.....|x..x......x.....", 38: "....x.......x...|....x.......x..g",
                 43: "..o...o.g.o...o.|..o.g.o...o...og", 39: ".........g......|.......g.....g..",
                 48: "................|.......o........", 50: "..............g.|................"},
        "extra": {51: "....o.......o...|....o.......o...", 46: "......o.........|..............o.",
                  40: "...g............|...........g...."},
        "fill": {44: "x.....x...x.x...", 38: "....x.....o.x.ox", 43: "..o...o.........", 48: "..........o....o"},
        "end": {44: "x", 48: "x", 46: "o"},
    },
    2: {  # Clockwork Kit: a steady four, a clanking off-beat, a ticking clock
        "grid": 16, "late": 0.0,
        "intro": {36: "x...x...x...x...|x...x...x...x...", 46: "g.g.g.g.g.g.g.g.|g.g.g.g.g.g.g.g.",
                  42: "..o...o...o...o.|..o...o...o...o."},
        "main": {36: "x...x...x...x...|x...x...x...x...", 38: "....x.......x...|....x.......x...",
                 42: "..o...o...o...o.|..o...o...o...o.", 46: "g.g.g.g.g.g.g.g.|g.g.g.g.g.g.g.g.",
                 41: "...o.......o....|...o.......o..o.", 39: "..........o.....|......o.........",
                 40: "................|..............o."},
        "extra": {45: ".......o........|.......o........", 44: "..........o.....|................",
                  47: "................|............g..."},
        "fill": {36: "x...x...x...x.x.", 38: "....x...o.o.x.xx", 41: "..o.o...o...o..."},
        "end": {36: "x", 44: "x", 40: "o"},
    },
    3: {  # Kitchen Perc Kit: spoons, knives, pans and glass, shuffled (triplet eighths, 12 a bar)
        "grid": 12, "late": 0.0,
        "intro": {35: "x.....x....o|x....ox.....", 46: "g.og.og.og.o|g.og.og.og.o"},
        "main": {35: "x.....x....o|x....ox.....", 36: "...x.....x..|...x.....x..",
                 46: "g.og.og.og.o|g.og.og.og.o", 42: "........o...|........o...",
                 37: "..........o.|....o.......", 48: "............|.........o.."},
        "extra": {44: "......o.....|............", 50: "...........o|............", 38: "............|..o........."},
        "fill": {35: "x.....x.....", 36: "...x..x..xox", 38: "......o..o.o", 46: "g.og.og.og.o"},
        "end": {35: "x", 51: "x", 49: "o"},
    },
}


def drums(n: int) -> list[tuple]:
    o = DRUMS[n]
    grid, late = o["grid"], o["late"]
    step = 4.0 / grid
    notes = []

    def put(pattern: dict, bar0: int, bars: int):
        for pad, s in pattern.items():
            cells = s.split("|")
            for k in range(bars):
                row = cells[k % len(cells)]
                for i, ch in enumerate(row):
                    if ch in VEL:
                        b = (bar0 + k) * 4 + i * step + (late if grid == 16 and i % 2 else 0.0)
                        notes.append((b, pad, 0.2, VEL[ch]))

    put(o["intro"], 8, 4)                     # bars 9-12
    put(o["main"], 12, 3)                     # 13-15
    put(o["fill"], 15, 1)                     # 16
    put(o["main"], 16, 7)                     # 17-23
    put(o["extra"], 16, 7)
    put(o["fill"], 23, 1)                     # 24
    put(o["main"], 24, 3)                     # 25-27
    put(o["extra"], 24, 3)
    put(o["fill"], 27, 1)                     # 28
    for pad, s in o["end"].items():           # 29: the last hit
        notes.append((28 * 4.0, pad, 0.5, VEL[s]))
    return notes


# ---- bass ---------------------------------------------------------------------------------------------------------------
def bass(n: int) -> list[tuple]:
    """Bars 17-28, then the outro's Bb (29-30) and D (31). n: 1 round sub, 2 rubber pluck, 3 bowed."""
    notes = []
    for cell in range(8, 14):                                    # bars 17-28, two bars a cell
        base = cell * 8.0
        ch = CHORDS[cell * 2]
        ch2 = CHORDS[cell * 2 + 1]
        r, f, s = BASS[ch]
        lo = LOW[ch]
        if n == 1:
            notes += [(base, lo, 1.9, 104), (base + 2.0, lo, 1.4, 96), (base + 3.5, lo, 0.4, 80),
                      (base + 4.0, LOW[ch2], 1.9, 100), (base + 6.0, LOW[ch2] + 12, 0.9, 90),
                      (base + 7.0, LOW[ch2] + 7, 0.9, 88)]
        elif n == 2:
            r2, f2, s2 = BASS[ch2]
            notes += [(base, r, 0.45, 112), (base + 0.75, r, 0.2, 72), (base + 1.5, r + 12, 0.4, 96),
                      (base + 2.5, r, 0.4, 102), (base + 3.0, f, 0.3, 86), (base + 3.5, s, 0.4, 92),
                      (base + 4.0, r2, 0.45, 112), (base + 5.0, f2, 0.4, 86), (base + 5.5, r2 + 12, 0.3, 92),
                      (base + 6.5, r2, 0.4, 102), (base + 7.25, s2, 0.2, 72), (base + 7.5, f2, 0.4, 90)]
        else:
            step = {"Dm9": 36, "G9": 33, "Bbmaj7": 31, "A7sus": 37}[ch]   # a passing note into the next chord
            notes += [(base, lo, 4.05, 100), (base + 4.0, LOW[ch2], 2.05, 92), (base + 6.0, step, 2.0, 92)]
    # outro: Bb for bars 29-30, D for bar 31 (left to ring into 32)
    notes += [(112.0, 34, 7.8, 100), (120.0, 38, 4.0, 96)]
    return notes


# ---- the shared track: found sounds at the seams, the same in every combo --------------------------------------------------
# Core Library samples on the pads of an empty Drum Rack. Gate mode where a note's length should cut the sample.
GATE = {"Trigger Mode": "Gate"}
FX_PADS = {
    36: ("Wood Insert Cassette.wav", {}),                                            # the tape goes in
    37: ("Radio Station Search.wav", {**GATE, "Ve Attack": "3000 ms", "Ve Release": "250 ms", "Volume": "-8 dB"}),
    38: ("Riser White Noise.wav", {}),                                               # into bar 17
    39: ("FX Broken Box.wav", {}),                                                   # bar 17: the bass arrives
    40: ("Crackle Vinyl Pop.wav", {**GATE, "Ve Attack": "1500 ms", "Ve Release": "2500 ms", "Volume": "0 dB"}),
    41: ("Foley Drop LDre.wav", {}),                                                 # bar 29: the drums stop
}


def seams() -> list[tuple]:
    return [(0.0, 36, 0.25, 96), (24.0, 37, 7.9, 100), (64.0 - 3.81 * BPM / 60, 38, 0.25, 90), (64.0, 39, 0.25, 104),
            (112.0, 40, 10.0, 100), (112.0, 41, 0.25, 96)]


def arc(notes: list[tuple]) -> list[tuple]:
    """The beds' swell: the first four bars come in softer (most presets darken with velocity), as automation would;
    the LOM cannot write automation into arrangement clips."""
    def k(b):
        return 0.7 + 0.3 * min(1.0, b / 16.0)
    return [(b, p, d, max(1, round(v * k(b)))) for b, p, d, v in notes]


def humanize(notes: list[tuple], seed: int, vel: int = 6, beats: float = 0.006) -> list[tuple]:
    """Small, fixed (seeded) wobbles in velocity and timing, so repeats are not identical. Downbeats stay put."""
    import random
    rng = random.Random(seed)
    out = []
    for b, p, d, v in notes:
        db = 0.0 if b % 1 == 0 else rng.uniform(-beats, beats)
        out.append((max(0.0, b + db), p, d, max(1, min(127, v + rng.randint(-vel, vel)))))
    return out


# ---- options ------------------------------------------------------------------------------------------------------------
# Each track: (browser root, folder, item) for its instrument, extra audio effects (device names), a starting volume
# (dB) and sends to A (reverb) and B (delay) in dB (None: off). make.py loads, sets and writes them.
TRACKS = [
    # bed
    {"name": "bed1 music box", "part": "bed", "opt": 1, "src": ("sounds", "Piano & Keys", "Music Box.adg"),
     "notes": lambda: humanize(arc(music_box()), 1), "fx": ["Chorus-Ensemble", "Utility"], "vol": -1.3, "sends": (-14, -22),
     "set": {2: {"Output": "14 dB"}}},          # the Music Box rack plays about 15 dB under the other beds
    {"name": "bed1 hiss", "part": "bed", "opt": 1, "src": ("samples", None, "Noise Tape Floor.wav"),
     "notes": hiss, "fx": [], "vol": -5.0, "sends": (None, None), "simpler_loop": True,
     "set": {0: {"Snap": "Off", "S Loop On": "On", "S Loop Fade": "30 %", "Ve Attack": "1500 ms",
                 "Ve Release": "3000 ms", "Vol < Vel": "0 %", "Volume": "0 dB"}}},
    {"name": "bed2 upright", "part": "bed", "opt": 2, "src": ("sounds", "Piano & Keys", "Childhood Home Piano.adg"),
     "notes": lambda: humanize(arc(parlour_piano()), 2), "fx": [], "vol": 0.6, "sends": (-16, None)},
    {"name": "bed2 toy", "part": "bed", "opt": 2, "src": ("sounds", "Piano & Keys", "Toy Piano Bells.adv"),
     "notes": lambda: humanize(arc(toy_piano()), 3), "fx": ["Chorus-Ensemble"], "vol": -0.4, "sends": (-14, -20)},
    {"name": "bed3 branches", "part": "bed", "opt": 3, "src": ("sounds", "Pad", "Tree Branches.adg"),
     "notes": lambda: humanize(arc(branches_pad()), 4, beats=0.0), "fx": [], "vol": -4.6, "sends": (-15, None)},
    {"name": "bed3 tin bowl", "part": "bed", "opt": 3, "src": ("sounds", "Mallets", "Tin Bowl.adv"),
     "notes": lambda: humanize(arc(tin_bowl()), 5), "fx": [], "vol": -2.6, "sends": (-12, -18)},
    # drums
    {"name": "drums1 tin", "part": "drums", "opt": 1, "src": ("drums", None, "Rattle Kit.adg"),
     "notes": lambda: humanize(drums(1), 6, vel=5, beats=0.004), "fx": [], "vol": -1.0, "sends": (-20, None)},
    {"name": "drums2 clockwork", "part": "drums", "opt": 2, "src": ("drums", None, "Clockwork Kit.adg"),
     "notes": lambda: humanize(drums(2), 7, vel=5, beats=0.004), "fx": [], "vol": -3.0, "sends": (-22, None)},
    {"name": "drums3 cutlery", "part": "drums", "opt": 3, "src": ("drums", None, "Perc Kitchen Kit.adg"),
     "notes": lambda: humanize(drums(3), 8, vel=5, beats=0.004), "fx": [], "vol": -2.7, "sends": (-18, None),
     "rack": "devices[0].chains[0].devices[0]", "pads": {35: ("Kick Wood.wav", {})}},   # the kitchen has no kick
    # bass
    {"name": "bass1 sub", "part": "bass", "opt": 1, "src": ("sounds", "Bass", "Sub Mellow.adg"),
     "notes": lambda: humanize(bass(1), 9, vel=4, beats=0.0), "fx": ["Saturator"], "vol": -8.5, "sends": (None, None),
     "set": {1: {"Type": "Bass Shaper", "Drive": "10 dB", "Output": "-7 dB"}}},
    {"name": "bass2 rubber", "part": "bass", "opt": 2, "src": ("sounds", "Bass", "Tension Rubber Bass.adv"),
     "notes": lambda: humanize(bass(2), 10, vel=5, beats=0.004), "fx": [], "vol": 0.6, "sends": (-28, None)},
    {"name": "bass3 bowed", "part": "bass", "opt": 3, "src": ("sounds", "Bass", "Cat Gut Bass.adv"),
     "notes": lambda: humanize(bass(3), 11, vel=4, beats=0.0), "fx": ["Saturator"], "vol": -3.6, "sends": (-26, None),
     "set": {1: {"Type": "Hard Curve", "Drive": "16 dB", "Output": "-10 dB", "Dry/Wet": "75 %"}}},
    # shared: plays in every combo
    {"name": "seams", "part": "shared", "opt": 0, "src": ("instruments", None, "Drum Rack"),
     "notes": seams, "fx": [], "vol": -9.0, "sends": (-16, -22), "pads": FX_PADS},
]

# Returns (Live's default new set: A Reverb, B Delay) and Main (EQ Eight high-pass, Glue Compressor, Limiter).
# Glue's Ratio, Attack and Release are indices:
# Ratio 0/1/2 = 2/4/10, Attack 0..6 = .01 .1 .3 1 3 10 30 ms, Release 0..6 = .1 .2 .4 .6 .8 1.2 s, Auto.
RETURNS = {
    0: {"Decay Time": "2200 ms", "Predelay": "18 ms", "Dry/Wet": "100 %"},
    1: {"Ping Pong": "On", "L 16th": "3", "R 16th": "3", "Feedback": "32 %", "Filter On": "On",
        "Filter Freq": "1500 Hz", "Filter Width": "6"},
}
MASTER = {
    0: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "32 Hz", "1 Filter On A": "On"},
    1: {"Threshold": "-12 dB", "Ratio": 0, "Attack": 5, "Release": 6, "Output": "1.5 dB", "Dry/Wet": 1.0},
    2: {"Mode": "True Peak", "Ceiling": "-1.8 dB", "Lookahead": "3 ms", "Auto": "On", "Input Gain": "6 dB"},
}

OPTIONS = {
    "bed": [
        {"id": 1, "name": "Music box & hiss", "about": "A wind-up music box picks out the tune over its own arpeggio, through tape hiss."},
        {"id": 2, "name": "Parlour upright", "about": "An old upright plays lopsided chords; a detuned toy piano carries the tune."},
        {"id": 3, "name": "Branches & tin bowl", "about": "A pad of rustling branches holds the chords; a struck tin bowl sings the tune slowly."},
    ],
    "drums": [
        {"id": 1, "name": "Tin-can break", "about": "A broken beat on slaps, a wooden box, buzzing tin and a cracked cowbell."},
        {"id": 2, "name": "Clockwork four", "about": "A steady four-on-the-floor with a clanking off-beat and a ticking clock."},
        {"id": 3, "name": "Cutlery shuffle", "about": "Spoons, knives, pans and glass in a lazy triplet shuffle over a wooden kick."},
    ],
    "bass": [
        {"id": 1, "name": "Round sub", "about": "A warm, rounded sub that sits under the kick and holds the roots."},
        {"id": 2, "name": "Rubber band", "about": "A plucked, bouncy rubber-string bass that skips around the beat."},
        {"id": 3, "name": "Bowed gut", "about": "A bowed gut-string bass, roughened, gliding through the changes."},
    ],
}


def tracks_of(part: str, opt: int) -> list[str]:
    return [t["name"] for t in TRACKS if t["part"] == part and t["opt"] == opt]


def combos() -> list[tuple[int, int, int]]:
    return [(b, d, s) for b in (1, 2, 3) for d in (1, 2, 3) for s in (1, 2, 3)]
