"""Marrow as a cumbia: the arrangement, as data (make.py builds it in Live and renders it).

The riffs, the bass line, the solo and the post-solo's clang are Meshuggah's, read note for note from the transcription
(tab.py; not in this repo). The cumbia is ours: a güiro's long-short-short on every beat, a conga tumbao, maracas,
a bombo, timbales and a cowbell, a combo organ on the off-beats, a chicha guitar, an accordion, trumpets.

**Tempo.** 100 BPM in 4/4, and an eighth of Marrow (150 BPM) is an eighth here: the riffs keep their place in the bar,
two thirds as fast, so their odd groupings (15 + 15 + 2, fives, threes) still run across the cumbia's four.

**The band, from Meshuggah's.** The bass plays Lövgren's line. The chicha guitar plays the riff: its high, slid notes
two octaves up with a hammered grace note under each; the low F pedal as short, muted chops. Haake's kit becomes the
percussion section: his kick (which follows the riff) the bombo, on the riff's F; his snare's accents the timbales,
on the riff's high notes; his china's quarters the cowbell; his hi-hat's eighths the maracas. Under all of it the
güiro and congas keep the cumbia.

**Harmony.** Marrow sits on F, and each riff colours it with its own high notes. The organ's off-beat chords take
their notes from the riff above them: F5 under the main riff's Ab, A and B; F minor under verse 1's Ab; F-Bb-C under
verse 2; Bb over F under "One Evil"'s F and D; D minor over F under verse 3's A, F# and D; F-Bb-Eb in the outro.
The solo is Thordendal's, on a Farfisa, over a plain cumbia bass on F and C and the guitar's off-beat chops on
G#dim7 (his solo is E Phrygian dominant over F). The post-solo's F/F# clang goes to the trumpets.

**Form** (84 bars and a bar of tail, 204 s): the güiro alone (2 bars); intro (Marrow's measures 1-8, guitar and
hand percussion); main riff (9-16, the band); verse 1 (25-32); verse 2 (41-48); "One Evil" (49-56, the accordion
joins in thirds); verse 3 (65-72); solo (97-104); post-solo (113-120); the main riff again (161-168, everything, an
eight-string through an amp under it); outro (178-185); a two-bar ending (a hit, a timbale roll, the last hit).
A crash and a timbale fill mark the seams.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tab  # noqa: E402

BPM = 100.0

# name, bars, Marrow's measures (first, last) or None
SECTIONS = [
    ("guiro", 2, None),
    ("intro", 8, (1, 8)),
    ("main", 8, (9, 16)),
    ("verse1", 8, (25, 32)),
    ("verse2", 8, (41, 48)),
    ("oneevil", 8, (49, 56)),
    ("verse3", 8, (65, 72)),
    ("solo", 8, (97, 104)),
    ("postsolo", 8, (113, 120)),
    ("return", 8, (161, 168)),
    ("outro", 8, (178, 185)),
    ("end", 2, None),
]
START, _b = {}, 0.0
for _name, _bars, _src in SECTIONS:
    START[_name] = _b
    _b += _bars * 4.0
SONG_BEATS = _b                    # 336: 84 bars
BEATS = SONG_BEATS + 4.0           # and a bar for the last hit's tail
BARS = int(BEATS // 4)
SRC = {n: s for n, _, s in SECTIONS}
LEN = {n: b * 4.0 for n, b, _ in SECTIONS}

RIFF = ["intro", "main", "verse1", "verse2", "oneevil", "verse3", "postsolo", "return", "outro"]
FULL = ["main", "verse1", "verse2", "oneevil", "verse3", "postsolo", "return", "outro"]   # the bass and bombo on the riff

# the organ's off-beat chord under each riff (F4 and up, above the bass and the guitar's chops)
CHORD = {
    "main": [65, 72, 77], "return": [65, 72, 77],      # F5: the riff's Ab, A and B colour it
    "verse1": [65, 68, 72, 77],                         # F minor
    "verse2": [65, 70, 72, 77],                         # F sus4
    "oneevil": [65, 70, 74, 77],                        # Bb over F
    "verse3": [65, 69, 74, 77],                         # D minor over F
    "outro": [65, 70, 75, 77],                          # F-Bb-Eb
}
DIM = [56, 59, 62, 65]                                  # G#dim7: Ab B D F, the solo's chord over F


def notes_in(part: int, sec: str) -> list[tuple]:
    """Marrow's part `part` in section `sec`, moved to the section's place in the cover."""
    m0, m1 = SRC[sec]
    m1 = min(m1, m0 + LEN[sec] // 4 - 1)
    return [(START[sec] + b, p, d, f) for b, p, d, f in tab.window(part, m0, m1)]


def is_pedal(p: int) -> bool:
    return p < 38                                       # F1, Bb1 (and F#1-G#1 in the second solo)


# ---- the riff players -----------------------------------------------------------------------------------------------------
def guitar_part(sec: str) -> int:
    return 0 if sec == "intro" else 1


def guitar() -> list[tuple]:
    """The chicha guitar: the riff's high notes two octaves up (a grace note a tone under each, hammered), the low
    pedal as short muted chops an octave or two up; in the solo, off-beat chops on G#dim7; the ending's hits."""
    out = []
    for sec in RIFF:
        if sec == "postsolo":
            continue                                    # the trumpets have it
        ns = notes_in(guitar_part(sec), sec)
        starts = sorted({b for b, *_ in ns})
        for b, p, d, f in ns:
            if is_pedal(p):
                v = 44 if ("dead" in f or "ghost" in f) else (82 if b % 4 == 0 else 70)
                out.append((b, p + 24, 0.12 if v == 44 else min(d, 0.3), v))
            else:
                out.append((b, p + 24, max(0.1, d - 0.03), 98))
                if not any(b - 0.13 < s < b for s in starts):
                    out.append((b - 0.0625, p + 22, 0.06, 64))       # the grace note, hammered on
    for b in _offbeats("solo"):
        out += [(b, p, 0.16, 78) for p in DIM]
    out += _hit(START["end"], [53, 60, 65], 1.6, 104) + _hit(START["end"] + 4, [53, 60, 65], 3.0, 110)
    return out


def bass() -> list[tuple]:
    """Lövgren's line in the riff sections (the post-solo's too), its F pedal cut short (at most three quarters of a beat)
    for a cumbia's bounce; a cumbia bass on F and C under the solo; the hits."""
    out = []
    for sec in FULL:
        for b, p, d, f in notes_in(4, sec):
            if "dead" in f:
                out.append((b, p, 0.1, 52))
            elif "ghost" in f:
                out.append((b, p, max(0.1, d - 0.05), 66))
            else:                                       # the pedal short and bouncing, as a cumbia bass plays
                out.append((b, p, max(0.1, (min(d, 0.75) if is_pedal(p) else d) - 0.04), 106 if b % 4 == 0 else 98))
    s = START["solo"]
    for bar in range(8):
        b = s + bar * 4
        out += [(b, 29, 1.4, 106), (b + 2, 36, 0.9, 96), (b + 3, 41, 0.4, 84), (b + 3.5, 36, 0.45, 90)]
    out += [(START["end"], 29, 1.6, 110), (START["end"] + 4, 29, 3.0, 112)]
    return out


def metal() -> list[tuple]:
    """An eight-string through an amp, under the main riff's return and the outro: Thordendal's part as written."""
    out = []
    for sec in ("return", "outro"):
        for b, p, d, f in notes_in(1, sec):
            v = 48 if "dead" in f else (70 if "ghost" in f else 104)
            out.append((b, p, 0.12 if "dead" in f else max(0.1, d - 0.03), v))
    out += _hit(START["end"], [29, 36, 41], 1.6, 110) + _hit(START["end"] + 4, [29, 36, 41], 3.0, 116)
    return out


def _offbeats(sec: str) -> list[float]:
    return [START[sec] + k + 0.5 for k in range(int(LEN[sec]))]


def _hit(b: float, pitches: list[int], d: float, v: int) -> list[tuple]:
    return [(b, p, d, v) for p in pitches]


def organ() -> list[tuple]:
    """The combo organ's off-beat chords, the cumbia's chucu-chucu, in every riff section but the intro, the solo and
    the post-solo; the ending's hits."""
    out = []
    for sec, chord in CHORD.items():
        for k, b in enumerate(_offbeats(sec)):
            out += [(b, p, 0.22, 92 if k % 2 else 84) for p in chord]
    out += _hit(START["end"], [65, 72, 77], 1.6, 100) + _hit(START["end"] + 4, [53, 65, 72, 77], 3.0, 104)
    return out


def lead() -> list[tuple]:
    """Thordendal's solo on the Farfisa, as he plays it (16ths and triplets, E Phrygian dominant over F)."""
    return [(b, p, max(0.08, d - 0.02), 100 if (b * 4) % 2 == 0 else 90) for b, p, d, f in notes_in(6, "solo")]


THIRD_BB = {77: 74, 74: 70, 75: 72, 72: 69}                     # in Bb: F5 over D5, D5 over Bb4 ...
THIRD_F = {68: 65, 69: 65, 71: 68, 75: 72, 74: 70, 65: 62}       # over F: Ab-F, A-F, B-Ab, Eb-C, D-Bb


def accordion() -> list[tuple]:
    """The accordion doubles the riff's high notes in thirds, held until the next one: "One Evil" (two octaves and a
    bit up, in Bb) and the main riff's return (in the guitar's octave, thirds over F)."""
    out = []
    for sec, shift, thirds in (("oneevil", 36, THIRD_BB), ("return", 24, THIRD_F)):
        highs = [(b, p + shift) for b, p, d, f in notes_in(1, sec) if not is_pedal(p)]
        for k, (b, p) in enumerate(highs):
            nxt = highs[k + 1][0] if k + 1 < len(highs) else START[sec] + LEN[sec]
            d = min(2.0, nxt - b) - 0.06
            out.append((b, p, d, 96))
            if p in thirds:
                out.append((b, thirds[p], d, 84))
    return out


def brass() -> list[tuple]:
    """The post-solo's F/F# clang (Hagström's F4 and F#4 over the pedal) as trumpet stabs; the last hit."""
    out = [(b, p, min(d, 0.45) - 0.03, 108 if b % 1 == 0 else 98) for b, p, d, f in notes_in(3, "postsolo")
           if not is_pedal(p)]
    out += _hit(START["end"] + 4, [65, 66, 77, 78], 1.2, 112)
    return out


# ---- the percussion -------------------------------------------------------------------------------------------------------
def guiro() -> list[tuple]:
    """Long, short, short on every beat (pads: 36 the long scrape, 37 and 38 two short ones), from the first bar
    through the ending's roll."""
    out = []
    for k in range(int(START["end"] + 4)):
        b = float(k)
        acc = 104 if k % 2 == 0 else 94
        out += [(b, 36, 0.42, acc), (b + 0.5, 37, 0.2, 80), (b + 0.75, 38, 0.2, 86)]
    return out


CONGA = {  # two bars, 16 steps each: 36 tumba (low, open), 37 conga open, 38 slap, 39 muted
    39: "o.g.....o.g.....|o.g.....o.g.....",
    38: "....x...........|....x.......x...",
    37: "............o...|..........o.....",
    36: "..............o.|......o.......o.",
}
VEL = {"x": 108, "o": 88, "g": 54}


def _steps(pattern: dict, b0: float, bars: int, grid: int = 16) -> list[tuple]:
    out = []
    for pad, s in pattern.items():
        cells = s.split("|")
        for k in range(bars):
            for i, ch in enumerate(cells[k % len(cells)]):
                if ch in VEL:
                    out.append((b0 + k * 4 + i * 4.0 / grid, pad, 0.2, VEL[ch]))
    return out


def congas() -> list[tuple]:
    """The tumbao from the intro's fifth bar to the ending's first hit; the solo with a busier second bar."""
    out = _steps(CONGA, START["intro"] + 16, int((START["end"] - START["intro"] - 16) // 4))
    out += _steps({37: "x...............", 36: "x..............."}, START["end"] + 4, 1)
    return [(b, p, d, v) for b, p, d, v in out if b < START["end"] + 1 or b >= START["end"] + 4]


def maracas() -> list[tuple]:
    """Eighths, the off-beats louder (Haake's hi-hat), from the intro's first bar; quieter in the intro."""
    out = []
    for k in range(int((START["end"] - START["intro"]) * 2)):
        b = START["intro"] + k * 0.5
        quiet = b < START["main"]
        v = (62 if k % 2 else 44) if quiet else (82 if k % 2 else 58)
        out.append((b, 36 if k % 2 else 37, 0.2, v))
    return out


def bombo() -> list[tuple]:
    """On the riff's F wherever the bass plays it (Haake's kick follows the riff); one and three in the intro's second
    half and under the solo; the ending's hits."""
    out = []
    for sec in FULL:
        for b, p, d, f in notes_in(4, sec):
            if p == 29 and "dead" not in f and "ghost" not in f:
                out.append((b, 36, 0.2, 108 if b % 4 == 0 else 96))
    for sec, b0, bars in (("intro", START["intro"] + 16, 4), ("solo", START["solo"], 8)):
        for k in range(bars * 2):
            out.append((b0 + k * 2, 36, 0.2, 84 if sec == "intro" else 100))
    out += [(START["end"], 37, 0.2, 112), (START["end"] + 4, 37, 0.2, 120)]
    return out


def timbales() -> list[tuple]:
    """Pads: 36 low, 37 high (open), 38 rim (cáscara), 39 stick slap, 40 crash soft, 41 crash hard. The riff's high
    notes get a timbale (Haake's snare accents); a cáscara on the rim under the solo; a fill into each new section
    with a crash on its first beat; the ending's roll and hits."""
    out = []
    for sec in ("main", "verse1", "verse2", "oneevil", "verse3", "return", "outro"):
        for b, p, d, f in notes_in(1, sec):
            if not is_pedal(p) and "dead" not in f and "ghost" not in f:
                out.append((b, 37 if p >= 44 else 36, 0.2, 92))
    for b, p, d, f in notes_in(3, "postsolo"):
        if not is_pedal(p):
            out.append((b, 39, 0.2, 100))
    cascara = "x.x.xx.x.x.xx.x."          # the cáscara on the rim, two bars' worth of one
    for bar in range(8):
        for i, ch in enumerate(cascara):
            if ch == "x":
                out.append((START["solo"] + bar * 4 + i * 0.25, 38, 0.2, 86 if i % 4 == 0 else 70))
    for sec in ("main", "oneevil", "solo", "postsolo", "return", "outro"):
        s = START[sec]
        for i in range(8):                                    # the fill: the last two beats before the section
            out.append((s - 2 + i * 0.25, 37 if i % 2 == 0 else 36, 0.2, 64 + i * 6))
        out.append((s, 41 if sec in ("main", "return") else 40, 0.5, 104))
        out.append((s, 36, 0.2, 100))
    e = START["end"]
    out += [(e, 40, 0.5, 108), (e, 36, 0.2, 108)]
    for i in range(12):                                       # the roll into the last hit: beats 2-4, louder
        out.append((e + 1 + i * 0.25, 37 if i % 2 == 0 else 36, 0.2, 60 + i * 5))
    out += [(e + 4, 41, 0.5, 120), (e + 4, 36, 0.2, 116), (e + 4, 37, 0.2, 110)]
    return out


def cowbell() -> list[tuple]:
    """Quarters (Haake's china), the downbeats louder: under the main riff and its return, "One Evil", the solo and
    the outro; the last hit."""
    out = []
    for sec in ("main", "oneevil", "solo", "return", "outro"):
        for k in range(int(LEN[sec])):
            out.append((START[sec] + k, 36, 0.2, 100 if k % 2 == 0 else 82))
    out.append((START["end"] + 4, 36, 0.2, 110))
    return out


def humanize(notes: list[tuple], seed: int, vel: int = 5, beats: float = 0.006) -> list[tuple]:
    """Small, fixed (seeded) wobbles in velocity and timing. Downbeats stay put."""
    rng = random.Random(seed)
    out = []
    for b, p, d, v in notes:
        db = 0.0 if b % 1 == 0 else rng.uniform(-beats, beats)
        out.append((max(0.0, b + db), p, d, max(1, min(127, v + rng.randint(-vel, vel)))))
    return out


# ---- the tracks ----------------------------------------------------------------------------------------------------------
# (browser root, folder, item), extra audio effects, volume (dB), sends to A (reverb) and B (delay) in dB (None: off),
# Drum Rack pads {note: (sample, Simpler settings)}, device settings {device index: {parameter: value}}.
GUIRO = "Guiro 110 bpm.aif"          # two bars of a real güiro at 110 BPM; its long scrape and two short ones, cut
GATE = {"Trigger Mode": "Gate", "Ve Release": "40 ms"}
TRACKS = [
    {"name": "guiro", "src": ("instruments", None, "Drum Rack"), "notes": lambda: humanize(guiro(), 1, beats=0.004),
     "fx": [], "vol": 5.0, "sends": (-24, None), "pads": {
         36: (GUIRO, {**GATE, "S Start": "0 %", "S Length": "9.2 %"}),
         37: (GUIRO, {**GATE, "S Start": "13.6 %", "S Length": "2.6 %"}),
         38: (GUIRO, {**GATE, "S Start": "19.4 %", "S Length": "1.8 %"})}},
    {"name": "congas", "src": ("instruments", None, "Drum Rack"), "notes": lambda: humanize(congas(), 2),
     "fx": ["EQ Eight"], "vol": -4.0, "sends": (-22, None), "pads": {
         36: ("Tumba Low.aif", {}), 37: ("Conga Open Hard.aif", {}), 38: ("Conga Hi Slap.aif", {}),
         39: ("Conga Hi Muted.aif", {})},
     "set": {1: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "100 Hz", "1 Filter On A": "On"}}},
    {"name": "maracas", "src": ("instruments", None, "Drum Rack"), "notes": lambda: humanize(maracas(), 3),
     "fx": [], "vol": -4.0, "sends": (-26, None), "pads": {
         36: ("Shake Maracas Hard.aif", {}), 37: ("Shake Maracas Soft.aif", {})}},
    {"name": "bombo", "src": ("instruments", None, "Drum Rack"), "notes": lambda: humanize(bombo(), 4, beats=0.0),
     "fx": [], "vol": 0.0, "sends": (None, None), "pads": {
         36: ("Kick Felt Soft Dry Session.aif", {}), 37: ("Kick Felt Hard Dry Session.aif", {})}},
    {"name": "timbales", "src": ("instruments", None, "Drum Rack"), "notes": lambda: humanize(timbales(), 5),
     "fx": ["EQ Eight"], "vol": -4.5, "sends": (-18, None), "pads": {
         36: ("Timbales Low Open Hard.aif", {}), 37: ("Timbales High Open Hard.aif", {}),
         38: ("Timbale Rim Thumb.wav", {}), 39: ("Timbale Stick Slap.wav", {}),
         40: ("Crash Dry Session Soft 1.aif", {}), 41: ("Crash Dry Session Hard 1.aif", {})},
     "set": {1: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "80 Hz", "1 Filter On A": "On"}}},
    {"name": "cowbell", "src": ("instruments", None, "Drum Rack"), "notes": lambda: humanize(cowbell(), 6),
     "fx": [], "vol": -2.0, "sends": (-24, None), "pads": {36: ("Cowbell Latin Ting.wav", {})}},
    {"name": "bass", "src": ("sounds", "Bass", "Electric Bass Soft.adg"), "notes": lambda: humanize(bass(), 7, beats=0.003),
     "fx": [], "vol": -2.0, "sends": (None, None)},
    {"name": "guitar", "src": ("sounds", "Guitar & Plucked", "Single Coil Guitar.adv"),
     "notes": lambda: humanize(guitar(), 8), "fx": ["Phaser-Flanger", "EQ Eight"], "vol": -2.5, "sends": (-14, -20),
     "set": {1: {"Dry/Wet": "50 %"}, 2: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "140 Hz", "1 Filter On A": "On"}}},
    {"name": "organ", "src": ("sounds", "Piano & Keys", "Organ Transistor Series.adg"), "notes": lambda: humanize(organ(), 9),
     "fx": ["EQ Eight"], "vol": -9.0, "sends": (-18, None),
     "set": {1: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "200 Hz", "1 Filter On A": "On"}}},
    {"name": "lead", "src": ("sounds", "Bass", "Mad Farfisa.adv"), "notes": lambda: humanize(lead(), 10, beats=0.003),
     "fx": ["EQ Eight"], "vol": -7.5, "sends": (-16, -22),
     "set": {1: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "160 Hz", "1 Filter On A": "On"}}},
    {"name": "accordion", "src": ("sounds", "Synth Lead", "Musette Lead.adg"), "notes": lambda: humanize(accordion(), 11),
     "fx": ["EQ Eight"], "vol": -3.5, "sends": (-16, None),
     "set": {1: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "180 Hz", "1 Filter On A": "On"}}},
    {"name": "brass", "src": ("sounds", "Brass", "Some Trumpets.adg"), "notes": lambda: humanize(brass(), 12),
     "fx": ["EQ Eight"], "vol": -4.0, "sends": (-16, None),
     "set": {1: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "160 Hz", "1 Filter On A": "On"}}},
    {"name": "metal", "src": ("sounds", "Guitar & Plucked", "Hard Picked Guitar.adv"),
     "notes": lambda: humanize(metal(), 13, beats=0.002), "fx": ["Amp", "Cabinet"], "vol": -9.5, "sends": (None, None),
     "set": {1: {"Amp Type": "Heavy", "Input Gain": 0.75, "Volume": 0.5}, 2: {"Cabinet Type": "4x12"}}},
]

RETURNS = {
    0: {"Decay Time": "1600 ms", "Predelay": "12 ms", "Dry/Wet": "100 %"},
    1: {"Ping Pong": "Off", "L 16th": "3", "R 16th": "3", "Feedback": "25 %", "Filter On": "On",
        "Filter Freq": "1800 Hz", "Filter Width": "6"},
}
MASTER = {
    0: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "30 Hz", "1 Filter On A": "On"},
    1: {"Threshold": "-14 dB", "Ratio": 0, "Attack": 5, "Release": 6, "Output": "1.5 dB", "Dry/Wet": 1.0},
    2: {"Mode": "True Peak", "Ceiling": "-2.0 dB", "Lookahead": "3 ms", "Auto": "On", "Input Gain": "9 dB"},
}
