"""A hard industrial techno short: the arrangement, as data (make.py builds it in Live and renders it).

**Key and tempo.** A phrygian (A Bb C D E F G) at 150 BPM. The key comes from the kicks: most of VEC2's clubby kicks
ring at 54-60 Hz, and 060, the body here, at 55 Hz, an A.

**Form**, 24 bars and a bar of tail (40 s at 150): it opens on the kick (never on a lone bar of anything else).
  intro  0-3   kick, rumble, closed hats, the acid low and closed, an 808 rim
  build  4-11  open hats and ride join, the acid opens up, a stab every two bars, the 808 clap from bar 8
  break 12-15  the kick and rumble drop out: long stabs into the reverb, the acid alone, 808 toms down the last bar,
               a half bar of silence before the drop
  drop  16-23  everything: the acid jumps octaves, stabs every 3 sixteenths (3 against 4), clap on 2 and 4
  end   24     one last kick and stab, and their tail

Pads are named, not numbered: make.py reads each Drum Rack's pads by name in Live.
"""
from __future__ import annotations

import random

BPM = 150.0
BARS = 25
BEATS = BARS * 4.0
TAIL = 4.0                                # a bar after the last hit for its boom and reverb to ring out (faded)
LEAD = 8.0                                # the clips start 2 bars in: a real-time take's first ~0.9 s is off the timeline
S = 0.25                                  # a sixteenth, in beats

# the sounds: VEC2's (copied into the project's Samples/Imported) and Live's 808 Core Kit
ACID_SAMPLE = "VEC2 Acid Sounds 009 A.wav"     # a 303 one-shot on A2, bright, 557 ms: long enough to slide
STAB_SAMPLE = "VEC2 Synths 009 A.wav"          # an A minor stab (C E A), 285 ms
RUMBLE_SAMPLE = "VEC2 Bassdrums Clubby 065.wav"
RISER_SAMPLE = "VEC2 Cymbals Reverse 10.wav"   # 2.3 s into the drop
KICK_TOP_SAMPLE = "VEC2 Bassdrums Clubby 117.wav"
KICK_TOP_PAD = 47
# v8: harsh mid layers on HW002's driven kick pads (their COLDFIRE chains stay), high-passed so the sub stays clean
KICK_LAYERS = {"bite": (44, "VEC2 Bassdrums Hard 067.wav", "0 st"),     # most 1-2.5 kHz of VEC2's hard kicks; A1
               "edge": (40, "VEC2 Bassdrums Hard 037.wav", "1 st")}     # most 2.5-6 kHz, little box; G#1, so +1
LAYER_FX = {   # pad: {device index on the pad's chain: values}; HW002 voiced pad 40 as a box (low-pass 325 Hz, -11 dB
               # above 3.9 kHz) and pad 44's COLDFIRE dark (Color 0.16, about -8 dB tilt; 0.5 is flat)
    40: {1: {"4 Filter On A": "Off"}, 2: {"Color": 0.75}, 3: {"8 Filter On A": "Off"}},
    44: {2: {"Color": 0.75}},
}
LAYER_GAIN = {40: 5.0, 44: 5.0}   # dB on each layer pad's chain fader (v8d: edge still ~4 dB under the references)
LAYER_SIMPLER = {"F On": "On", "Filter Type": "Highpass", "Filter Slope": "24 dB", "Filter Freq": "180 Hz"}
SIMPLER_ROOT = 60                              # Simpler plays a sample at its own pitch on C3
PADS = {
    "kick": {"body": 45, "top": KICK_TOP_PAD, "bite": 44, "edge": 40},
    "perc 1": {"CH": 95, "OH": 117, "RD": 83},
    "perc 2": {"RD1": 33, "OH main": 60},
    "808": {"boom": 36, "rim": 37, "clap": 39, "tom lo": 44, "tom mid": 45, "tom hi": 47, "cowbell": 50},
}

RUMBLE_REVERB = {"Dry/Wet": "100 %", "Decay Time": "4.00 s", "Predelay": "0.50 ms", "Room Size": "50.0"}
EIGHT_VERB_MIX = 0.22                          # the beatbox chain's Supermassive was at 0.50

# per track: {device index: {parameter: value}}; strings are display units, numbers raw (the plugins show no units)
SOUNDS = {
    "acid": {
        0: {"Glide Mode": "Glide", "Glide Time": "60.0 ms", "Filter Type": "Lowpass", "Filter Circuit - LP/HP": "MS2",
            "Filter Slope": "24 dB", "Filter Freq": "700 Hz", "Filter Res": "55.0 %", "Filter Drive": "6.00 dB",
            "Fe < Env": 48.0, "Fe Decay": "180 ms", "Fe Sustain": "0.0 %", "Filt < Vel": "70.0 %",
            "Ve Release": "30.0 ms", "Volume": "-6.0 dB"},
        1: {"Style": 0.5, "Drive": 0.55, "Punish": 0.0, "LowCut": 0.15, "Tone": 0.6, "HighCut": 0.85, "Mix": 1.0,
            "AutoGain": 1.0},                                         # Decapitator after the filter
        2: {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "120 Hz", "1 Filter On A": "On"},
        3: {"Mix": 0.30, "Feedback": 0.45, "LowCut": 0.3},            # Supermassive (v8: wetter, was 0.14)
    },
    "stabs": {0: {"Ve Release": "80.0 ms", "F On": "Off", "Volume": "-6.0 dB"}},
    "riser": {0: {"Volume": "-6.0 dB"}},
}
MONO = ["acid"]                                # Simpler with one voice: the glide needs it

# the mix (v1, from v0's stems: kick -15.7, rumble -17.5, acid -16.2, 808 -24, hats -26.4, stabs -28.1 LUFS; the kick
# had no sub under HW002's kick-group EQ, which was voiced for HW002's own kick)
# (a source feeding an HW002 track is taken before its fader: its gain goes on the HW002 track)
# v3 (-7.1 LUFS) against the references' loudest 16 bars: the drop's mids 6-10 dB high, air 6 dB, sub 3-7 dB low;
# v4 moves about half way; v6: hats -2.5 (air 5 dB over); v5: the 808 (clap, cowbell through the beatbox COLDFIRE chain) carried the most mid energy
VOLUMES = {"rumble": 6.5, "acid": -7.0, "stabs": 0.0, "2022-06-02-001": 1.0, "perc 1": -2.5, "perc 2": -2.5, "beatbox": -4.0}
CHAINS = {   # track: {device index: {parameter: value}} on HW002's devices
    "kick group": {
        0: {"1 Frequency A": "22.0 Hz", "2 Frequency A": "55.0 Hz", "2 Gain A": "8.00 dB", "3 Gain A": "2.00 dB"},
        3: {"3 Gain A": "1.50 dB"},
    },
    # v8: wetter synths (Anthony: "more wet in the synths is a good idea")
    "2022-06-02-001": {2: {"Mix": 0.70}},                        # the stabs' Supermassive, was 0.50
    "SFX group": {2: {"Dry/Wet": "65 %"}},                       # Hybrid Reverb on the stabs' bus, was 50 %
}
MASTER_FX = ["Glue Compressor", "StandardCLIP", "Limiter"]   # after Main's own rack and Utility (bass mono)
MASTER = {   # Main's device index: values (Glue's attack, ratio and release show raw values: 10 ms, 2:1, 0.6 s)
    1: {"Bass Mono": "On", "Bass Freq": "120 Hz"},
    2: {"Threshold": "-10.0 dB", "Output": "1.00 dB"},
    3: {"Device On": "Off"},     # StandardCLIP: at its defaults it took ~6 dB off (v1), and it shows no units
    4: {"Mode": "True Peak", "Ceiling": "-1.0 dB", "Lookahead": "3 ms", "Input Gain": "9.0 dB", "Auto": "On"},
}

INTRO, BUILD, BREAK, DROP, END = (0, 4), (4, 12), (12, 16), (16, 24), (24, 25)


def bars(span):
    return range(*span)


def beat(bar: int, step: int = 0) -> float:
    return bar * 4.0 + step * S


# ---- the acid line ---------------------------------------------------------------------------------------------------
# (step, note, accent, slide); A2 = 45. Slides overlap the next note (the synth glides in legato).
A2 = 45
ACID_A = [(0, 0, 1, 0), (1, 0, 0, 0), (2, 12, 0, 1), (3, 0, 0, 0), (5, 3, 1, 0), (6, 0, 0, 0), (7, 1, 0, 1),
          (8, 0, 0, 0), (9, 12, 1, 0), (10, -2, 0, 0), (11, 0, 0, 1), (13, 7, 1, 0), (14, -4, 0, 0), (15, 0, 0, 0)]
ACID_B = [(0, 0, 1, 0), (2, 0, 0, 1), (3, 1, 0, 0), (4, 0, 1, 0), (6, 12, 0, 1), (7, 13, 1, 0), (8, 0, 0, 0),
          (10, 0, 1, 0), (11, 3, 0, 1), (12, 5, 0, 0), (13, 0, 1, 0), (14, 12, 0, 1), (15, 10, 0, 0)]


def acid() -> list[tuple]:
    out = []
    for bar in range(0, 24):
        if bar == 15:                                    # the break's last bar: the line stops after beat 2
            pat = [s for s in ACID_A if s[0] < 8]
        elif bar >= 16:
            pat = ACID_B if bar % 2 else ACID_A
        else:
            pat = ACID_A
        shift = 12 if bar >= 16 and bar % 4 == 3 else 0  # the drop's every fourth bar an octave up
        for k, (step, n, acc, slide) in enumerate(pat):
            nxt = pat[k + 1][0] if k + 1 < len(pat) else 16
            dur = (nxt - step) * S + 0.06 if slide else 0.55 * S
            # the intro closed and soft (velocity drives the filter), opening through the build
            if bar < 4:
                v = 70 + 20 * acc
            elif bar < 12:
                v = 82 + 4 * (bar - 4) // 2 + 30 * acc
            else:
                v = 96 + 31 * acc
            out.append((beat(bar, step), SIMPLER_ROOT + n + shift, dur, min(127, v)))   # the sample is A2
    return out


# ---- stabs -----------------------------------------------------------------------------------------------------------
AM = [SIMPLER_ROOT]                       # the sample is an A minor chord: one note per hit
BB = [SIMPLER_ROOT + 1]                   # B-flat minor: phrygian's half step, for the turns


def stabs() -> list[tuple]:
    out = []
    for bar in range(4, 12, 2):              # build: one on the "and" of 4, every two bars
        ch = BB if bar == 10 else AM
        out += [(beat(bar, 14), p, 0.2, 110) for p in ch]
    for bar in bars(BREAK):                   # break: long chords on the one, into the reverb
        if bar == 15:
            out += [(beat(bar), p, 1.5, 100) for p in BB]
        else:
            out += [(beat(bar), p, 3.0, 96) for p in AM]
    for two in range(16, 24, 2):              # drop: every 3 sixteenths across two bars (3 against 4)
        for step in range(0, 32, 3):
            ch = BB if (two == 22 and step >= 24) else AM
            vel = 120 if step % 12 == 0 else 100
            out += [(beat(two, step), p, 0.18, vel) for p in ch]
    out += [(beat(24), p, 0.5, 124) for p in AM]
    return out


# ---- drums -----------------------------------------------------------------------------------------------------------
KICK_LAYER_VEL = 127


def kick() -> list[tuple]:
    out = []
    for bar in list(bars(INTRO)) + list(bars(BUILD)) + list(bars(DROP)):
        for b in range(4):
            out += [(beat(bar, 4 * b), "body", 0.5, 127), (beat(bar, 4 * b), "top", 0.25, 110),
                    (beat(bar, 4 * b), "bite", 0.4, KICK_LAYER_VEL), (beat(bar, 4 * b), "edge", 0.4, KICK_LAYER_VEL)]
        if bar in (7, 11, 19, 23):                       # a pickup kick on the last sixteenth of the phrase
            out.append((beat(bar, 15), "body", 0.25, 96))
    out += [(beat(24), "body", 0.5, 127), (beat(24), "top", 0.25, 110), (beat(24), "bite", 0.4, KICK_LAYER_VEL),
            (beat(24), "edge", 0.4, KICK_LAYER_VEL)]
    return out


def rumble() -> list[tuple]:
    """The rumble's source: the same kick into a long reverb (make.py), on every beat the kick plays."""
    return [(b, SIMPLER_ROOT, 0.5, v) for b, p, _, v in kick() if p == "body" and b < beat(24)]


def hats() -> list[tuple]:
    """perc 1: closed 16ths (accents on the off-beat eighths), open hats on the off-beats from the build."""
    out = []
    for bar in list(bars(INTRO)) + list(bars(BUILD)) + list(bars(DROP)):
        for step in range(16):
            if bar < 2 and step % 2:                     # the first two bars on eighths only
                continue
            vel = (55, 40, 110, 45)[step % 4]            # the off-beat eighth loud, every fourth hit low
            out.append((beat(bar, step), "CH", 0.2, vel))
        if bar >= 4:
            for b in range(4):
                out.append((beat(bar, 4 * b + 2), "OH", 0.4, 104 if bar >= 16 else 92))
    for bar in bars(BREAK):                              # the break keeps a thin tick
        if bar < 15:
            for b in range(4):
                out.append((beat(bar, 4 * b + 2), "CH", 0.2, 80))
    return out


def ride() -> list[tuple]:
    """perc 2: a ride on the quarters through the drop, an open-hat layer on the drop's off-beats."""
    out = []
    for bar in list(range(8, 12)) + list(bars(DROP)):
        for b in range(4):
            out.append((beat(bar, 4 * b), "RD1", 0.5, 100 if b % 2 == 0 else 86))
        if bar >= 16:
            for b in range(4):
                out.append((beat(bar, 4 * b + 2), "OH main", 0.4, 90))
    return out


def eight() -> list[tuple]:
    """The 808: rim in 3-sixteenth knocks, clap on 2 and 4 from bar 8, a long boom at the break and the drop,
    toms falling through the break's last bar, cowbell flicks in the drop."""
    out = []
    for bar in range(0, 12):
        for step in (3, 6, 11, 14):
            out.append((beat(bar, step), "rim", 0.2, 76 + (step == 14) * 20))
    for bar in list(range(8, 12)) + list(bars(DROP)):
        out += [(beat(bar, 4), "clap", 0.3, 120), (beat(bar, 12), "clap", 0.3, 120)]
    for b in (beat(12), beat(16), beat(24)):
        out.append((b, "boom", 2.0, 127))
    toms = ["tom hi", "tom hi", "tom mid", "tom mid", "tom lo", "tom lo"]
    for k, step in enumerate(range(0, 6)):                # bar 15, from beat 1: sixteenths falling, then silence
        out.append((beat(15, step), toms[k], 0.25, 100 + 4 * k))
    for bar in bars(DROP):
        for step in (7, 15):
            if bar % 2:
                out.append((beat(bar, step), "cowbell", 0.2, 84))
    return out


def humanize(notes: list[tuple], seed: int, vel: int = 4) -> list[tuple]:
    """Velocity only: industrial techno sits dead on the grid."""
    r = random.Random(seed)
    return [(b, p, d, max(1, min(127, v + r.randint(-vel, vel)))) for b, p, d, v in notes]


def riser() -> list[tuple]:
    """The reversed cymbal, timed to end on the drop's one (2.3 s at 150 BPM is 5.75 beats)."""
    return [(beat(16) - 5.75, SIMPLER_ROOT, 5.75, 110)]


def boom_hits() -> list[float]:
    return [beat(12), beat(16), beat(24)]
