"""The arrangement: hikikomorphism's "property testing with agent swarms" explainer (a Suno voiceover over a Suno
bed, 92.6 s) made into techno with VEC2's kick, drums and offbeat bass.

**What is kept.** The narration stays exactly where it is, so the new audio still lines up with the video. The Suno
bed (an F pedal with C, Db and sometimes E/A above it, about 160 BPM, 92.6 s) stays as texture: high-passed so the
new bass owns the low end, ducked by the kick. demucs (htdemucs_ft) split the post's audio into voice and bed.

**The grid.** The bed pulses at 160 BPM, but the video was cut from takes with different phases. Folding its onsets
on the beat and cross-correlating each scene against the strongest one (23-40 s) gives the shifts in BED_CLIPS. The
grid has a beat at file time 0.110 s and downbeats at 0.86 s + 1.5 s * n, which puts the scene cuts (11.4, 23.4,
39.9, 45.9, 62.4, 65.4, 87.9 s) on bar lines. Song beat = ORIGIN + file seconds * 8 / 3; bar b starts at 8 + 4b.

**The form follows the video.** Section letters are scenes:
  A bars 0-7    the machinery: kick and offbeat hats, the bass from bar 4
  B bars 7-15   same history to both models: claps, sixteenth hats
  C bars 15-26  reference vs production: open hats, ride, the bass moves
  D bars 26-30  "Write one. Read it. Write two. Read again." - one hit per operation, no groove; a clap roll and a
                reversed cymbal into the drop
  E bars 30-41  "the write failed to invalidate the cache": the drop, everything, the bass rolls
  F bars 41-43  "Four operations remain": a bar of air, then four hits
  G bars 43-58  shrink, branch, one PR per bug: the groove back, then the ride and open hats again from bar 51
  H bars 58-61  "Keep property tests running": the groove to bar 60, then one last hit and its tail
"""
from __future__ import annotations

import random

BPM = 160.0
SPB = 60.0 / BPM            # seconds per beat (0.375)
GRID_T0 = 0.110             # a beat of the bed, in file seconds (checked against the rendered kick: listen.py)
DOWN_T0 = GRID_T0 + 2 * SPB  # the first downbeat (0.89 s)
ORIGIN = 8.0 - DOWN_T0 / SPB  # the song beat where the files' 0 s plays (5.6267): bar 0 is beat 8
FILE_S = 92.608             # the voice and the bed
VIDEO_S = 92.7
END = ORIGIN + VIDEO_S / SPB  # the render: ORIGIN .. END, as long as the video

VOICE = "proptest voice.wav"
BED = "proptest bed.wav"
# (file start s, file end s, shift s, clip gain dB): each piece of the bed, cut at a scene change, nudged onto the
# grid (the shift where its 0.8-5 kHz onsets best match the rendered kick's, scanned in 5 ms steps); the last piece
# swells under the closing line, so it comes down
BED_CLIPS = [(0.0, 11.5, -0.025, 0.0), (11.5, 45.6, -0.010, 0.0), (45.6, 64.4, -0.045, 0.0), (64.4, 88.7, -0.070, 0.0),
             (88.7, FILE_S, -0.120, -4.0)]

KICK = "VEC2 Bassdrums Clubby 118.wav"     # F1 + 69 ct, -20 dB in 174 ms (gone before the offbeat at 188 ms)
BASS = "VEC2 Bass 126 F.wav"               # an offbeat bass one-shot on F1 (44.9 Hz), 315 ms
BASS_HI = "VEC2 Bass 129 F.wav"            # F1 too, brighter (centroid 1.5 kHz against 0.7), 431 ms: the drop's layer
HAT = "VEC2 Cymbals HH Closed 03.wav"      # 60 ms
OPEN = "VEC2 Cymbals HH Open 041.wav"      # 160 ms, the darkest of the short opens
CLAP = "VEC2 Claps 042.wav"                # 216 ms
RIDE = "VEC2 Cymbals Ride 18.wav"          # 305 ms
CRASH = "VEC2 Cymbals Crash 06.wav"        # 1.2 s
REV_LONG = "VEC2 Cymbals Reverse 10.wav"   # 2.30 s, into the drop
REV_SHORT = "VEC2 Cymbals Reverse 07.wav"  # 1.59 s, into C and G

ROOT = 60                                   # Simpler plays its sample unpitched on C3
F1, C2, DB2, EB2, F2, C1 = ROOT, ROOT + 7, ROOT + 8, ROOT + 10, ROOT + 12, ROOT - 5


def bar(b: float, beat: float = 0.0) -> float:
    return 8.0 + 4.0 * b + beat


def at(seconds: float) -> float:
    """The song beat of a file time."""
    return ORIGIN + seconds / SPB


def q16(beat: float) -> float:
    return round(beat * 4) / 4


SECTIONS = {"A": (0, 7), "B": (7, 15), "C": (15, 26), "D": (26, 30), "E": (30, 41), "F": (41, 43), "G": (43, 58),
            "H": (58, 61)}
GROOVE = [(0, 25.75), (30, 41), (43, 60)]   # bars with the four-on-the-floor (C stops on beat 3 of bar 25)


def bars(a: float, b: float):
    for k in range(int(a), int(b + 0.999)):
        yield k


def in_groove(beat: float) -> bool:
    return any(bar(a) <= beat < bar(b) for a, b in GROOVE)


# the operations in D, from the transcript (parakeet's sentence times), on the nearest sixteenth
OPS = {"write 1": q16(at(39.68)), "read 1": q16(at(40.32)), "write 2": q16(at(41.44)), "read 2": q16(at(42.72))}
DROP = bar(30)
FOUR = [bar(42, k) for k in range(4)]       # "Four operations remain"
LAST = bar(60)


# the kick's velocity per section (downbeat, other beats): the form rises to the drop, falls, and rises again
KICK_VEL = {"A": (86, 78), "B": (96, 88), "C": (106, 98), "E": (122, 114), "G": (108, 100), "G2": (116, 108),
            "H": (116, 108)}


def section(b: float) -> str:
    s = next((k for k, (a, z) in SECTIONS.items() if a <= b < z), "H")
    return "G2" if s == "G" and b >= 51 else s


def kick() -> list[tuple]:
    out = []
    for b in range(0, 61):
        for k in range(4):
            beat = bar(b, k)
            if in_groove(beat):
                v1, v = KICK_VEL[section(b)]
                out.append((beat, ROOT, 0.25, v1 if k == 0 else v))
    out += [(OPS["write 1"], ROOT, 0.25, 112), (OPS["write 2"], ROOT, 0.25, 116)]
    out += [(x, ROOT, 0.25, 104 + 4 * i) for i, x in enumerate(FOUR)]
    out.append((LAST, ROOT, 0.25, 122))
    return out


def bass() -> list[tuple]:
    """The offbeat bass: one note on each beat's "and", F1 nearly always; each four-bar phrase turns at its end
    (octave, then the fifth and the minor sixth leading back). From the drop on it rolls (the "a" too)."""
    out = []
    for b in range(4, 60):
        sec = next(s for s, (a, z) in SECTIONS.items() if a <= b < z) if b < 61 else "H"
        if sec in ("D", "F"):
            continue
        if b == 25:
            beats = (0, 1)                   # stops with the kick; the ops take over
        else:
            beats = (0, 1, 2, 3)
        phrase = b % 4
        for k in beats:
            p = F1
            if phrase == 2 and k == 3:
                p = F2
            if phrase == 3 and k == 2:
                p = C2 if (b // 4) % 2 == 0 else EB2
            if phrase == 3 and k == 3:
                p = DB2 if (b // 4) % 2 == 0 else C2
            vel = 100 if sec in ("A", "B") else 112
            out.append((bar(b, k + 0.5), p, 0.42, vel))
            if sec == "E" or (sec == "G" and b >= 51) or sec == "H":
                out.append((bar(b, k + 0.75), F1 if p == F1 else p, 0.2, vel - 22))
    out += [(OPS["write 1"], F1, 0.4, 112), (OPS["write 2"], F2, 0.4, 116)]
    out += [(x + 0.0, [F1, F1, C2, DB2][i], 0.4, 110) for i, x in enumerate(FOUR)]
    out.append((LAST, F1, 6.0, 120))
    return out


def bass_hi() -> list[tuple]:
    """The bright layer: the bass's notes in the drop and G's second half (H stays lighter, under the last line)."""
    return [(b, p, d, v - 10) for b, p, d, v in bass() if section((b - 8) / 4) in ("E", "G2")]


def hats() -> list[tuple]:
    """Closed hats: offbeats in A, sixteenths from B (55/40/110/45 over a beat), none where the open hat plays."""
    out = []
    for b in range(0, 60):
        sec = next(s for s, (a, z) in SECTIONS.items() if a <= b < z)
        if sec in ("D", "F"):
            continue
        for k in range(4):
            if not in_groove(bar(b, k)):
                continue
            if sec == "A":
                out.append((bar(b, k + 0.5), ROOT, 0.1, 82))
                continue
            for s, v in ((0.0, 55), (0.25, 40), (0.5, 110), (0.75, 45)):
                if s == 0.5 and open_on(b):
                    continue
                out.append((bar(b, k + s), ROOT, 0.1, v))
    out += [(OPS["read 1"], ROOT, 0.1, 110), (OPS["read 2"], ROOT, 0.1, 110)]
    out += [(bar(41, k + 0.5), ROOT, 0.1, 60) for k in range(4)]    # the bar of air keeps time, quietly
    return out


def open_on(b: int) -> bool:
    return 15 <= b < 25 or 30 <= b < 41 or 51 <= b < 58


def opens() -> list[tuple]:
    return [(bar(b, k + 0.5), ROOT, 0.2, 92 if b >= 30 else 84)
            for b in range(0, 60) if open_on(b) for k in range(4) if in_groove(bar(b, k))]


def clap() -> list[tuple]:
    out = [(bar(b, k), ROOT, 0.2, 104) for b in range(7, 60) for k in (1, 3) if in_groove(bar(b, k))]
    out += [(OPS["read 1"], ROOT, 0.2, 96), (OPS["read 2"], ROOT, 0.2, 100)]
    # the roll into the drop: eighths, then sixteenths, louder all the way
    roll = [bar(28, 2 + 0.5 * i) for i in range(4)] + [bar(29, 0.25 * i) for i in range(16)]
    out += [(x, ROOT, 0.15, int(48 + 72 * i / (len(roll) - 1))) for i, x in enumerate(roll)]
    # fills: the last two beats before G's second half and before F
    out += [(bar(50, 2 + 0.25 * i), ROOT, 0.15, 70 + 4 * i) for i in range(8)]
    out += [(bar(40, 3 + 0.25 * i), ROOT, 0.15, 80 + 8 * i) for i in range(4)]
    return out


def ride() -> list[tuple]:
    return [(bar(b, k + 0.5), ROOT, 0.3, 70) for b in list(range(30, 41)) + list(range(51, 58)) for k in range(4)
            if in_groove(bar(b, k))] + [(bar(b, k), ROOT, 0.3, 56) for b in range(15, 25) for k in range(4)]


def crash() -> list[tuple]:
    return [(x, ROOT, 1.0, v) for x, v in ((bar(15), 90), (DROP, 120), (bar(43), 108), (bar(51), 96), (LAST, 116))]


def rev_long() -> list[tuple]:
    return [(DROP - 2.30 / SPB, ROOT, 2.30 / SPB, 110)]


def rev_short() -> list[tuple]:
    return [(x - 1.59 / SPB, ROOT, 1.59 / SPB, 96) for x in (bar(15), bar(43))]


def humanize(notes: list[tuple], seed: int, t: float = 0.008, v: int = 6) -> list[tuple]:
    """Seeded jitter for the hats: up to +-3 ms and +-6 velocity; the downbeats stay put."""
    rnd = random.Random(seed)
    out = []
    for b, p, d, vel in notes:
        jt = 0.0 if abs(b - round(b)) < 1e-6 else rnd.uniform(-t, t)
        out.append((b + jt, p, d, max(1, min(127, vel + rnd.randint(-v, v)))))
    return out


def simpler(sample: str, mode: str, voices: int = 0, **params) -> dict:
    """A Simpler: its sample, playback mode, voice count (0: leave) and parameters in display units (velocity reaches
    the volume at 60 % unless given: the hats' accents and the clap roll need it)."""
    return {"sample": sample, "mode": mode, "voices": voices, "params": {"Vol < Vel": "60 %", **params}}


# Each track: an audio track (clips) or a MIDI track with one Simpler, then effects; vol in dB, sends to A (reverb)
# and B (delay) in dB (None: off).
TRACKS = [
    {"name": "voice", "audio": "voice", "fx": ["EQ Eight", "Compressor"], "vol": 1.5, "sends": (-24.0, None)},
    {"name": "bed", "audio": "bed", "fx": ["EQ Eight", "Compressor"], "vol": -2.0, "sends": (None, None)},
    {"name": "kick", "simpler": simpler(KICK, "One-Shot", Transpose="-1 st", Detune="31 ct", **{"Vol < Vel": "55 %"}), "fx": ["Saturator"],
     "notes": kick, "vol": -4.0, "sends": (None, None)},
    {"name": "bass", "simpler": simpler(BASS, "Classic", voices=1, **{"Ve Release": "30.0 ms", "Vol < Vel": "40 %"}), "fx": ["Saturator"],
     "notes": bass, "vol": -6.0, "sends": (None, None)},
    {"name": "hat", "simpler": simpler(HAT, "One-Shot"), "fx": ["EQ Eight"], "notes": lambda: humanize(hats(), 1),
     "vol": -14.0, "sends": (None, None)},
    {"name": "open", "simpler": simpler(OPEN, "One-Shot"), "fx": ["EQ Eight"], "notes": lambda: humanize(opens(), 2),
     "vol": -16.0, "sends": (-20.0, None)},
    {"name": "clap", "simpler": simpler(CLAP, "One-Shot"), "fx": [], "notes": clap, "vol": -13.0,
     "sends": (-8.0, None)},
    {"name": "ride", "simpler": simpler(RIDE, "One-Shot"), "fx": ["EQ Eight"], "notes": lambda: humanize(ride(), 3),
     "vol": -20.0, "sends": (-22.0, None)},
    {"name": "crash", "simpler": simpler(CRASH, "One-Shot"), "fx": [], "notes": crash, "vol": -14.0,
     "sends": (-14.0, None)},
    {"name": "rev long", "simpler": simpler(REV_LONG, "One-Shot"), "fx": [], "notes": rev_long, "vol": -12.0,
     "sends": (-12.0, None)},
    {"name": "rev short", "simpler": simpler(REV_SHORT, "One-Shot"), "fx": [], "notes": rev_short, "vol": -14.0,
     "sends": (-12.0, None)},
    {"name": "bass hi", "simpler": simpler(BASS_HI, "Classic", voices=1, **{"Ve Release": "30.0 ms", "Vol < Vel": "40 %"}),
     "fx": [], "notes": bass_hi, "vol": -12.0, "sends": (None, None)},
]
