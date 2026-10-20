"""Make Juice Box's sounds (anthonybecker.me demo 12) in Live from acoustic and foley samples: build the set, lay
every sound's layers on the timeline, render it in one export, cut it into one file per sound, encode, upload.

  cd hands && uv run python scripts/juice_box/newset.py          # once: a new Live 12 set, JUICE_sounds
  cd hands && uv run python scripts/juice_box/make.py build      # layer lanes, the Sine track, returns, Main chain
  cd hands && uv run python scripts/juice_box/make.py score      # every sound's clips and notes, one slot each
  cd hands && uv run python scripts/juice_box/make.py render     # one export of the whole timeline
  cd hands && uv run python scripts/juice_box/make.py measure    # per sound: peak, onset, length, band balance
  cd hands && uv run python scripts/juice_box/make.py encode     # cut, trim under -80 dBFS, .m4a named by content
  cd hands && uv run python scripts/juice_box/make.py upload     # -> R2 audio/demos/juice-box/

A second argument picks another demo's kit from the same set and lanes: `make.py score four-by-four` and so on
(chess.py, demo 11's sounds). Run build once per kit too: it adds any lanes the kit needs.

The layers are Core Library one-shots (foley, wood, slaps, glass, coins, mallets, bells), placed as arrangement
audio clips with warp off, so a clip's transpose repitches it the way a sampler would. Each layer plays on a lane of
its role, and a role's lanes share its devices and sends:

- thump: kicks and a floor tom (acoustic lows), through a Compressor that lets the attack through and a Saturator.
  Under every thump an Operator sine with a fast pitch drop (the Sine track) adds the low end a sample lacks.
- slap: hand slaps, claps, box and crack snares, coins: the slappy mids. A fast Compressor (3 ms attack) and a
  Saturator make them snap.
- wood: knocks, blocks, the broken box, rattles: bodies and debris. A gentler Compressor.
- click: very short knocks, scrapes, cracks, ticks: the transients.
- shine: celeste, music box, bells, triangle, jingle bells, glass: the highs. Sent hard to the reverb and the delay.
- air: shakers and paper: hiss and texture, sent to the reverb.

Returns: A-Reverb (1.8 s) and B-Delay (ping-pong, dotted eighth at 120 BPM). Main: Glue Compressor (3 ms attack so
hits keep their transient) and a Limiter at -2 dB, headroom for AAC.

The LOM cannot shorten an arrangement audio clip (crop turns warp back on and the length stays), so every sample
plays until the next clip on its lane starts, which is never before the sample has fallen 60 dB, and each sound's
slot is sized from its samples' -60 dB points plus 2.5 s for the tails.

Audio never goes in git. Renders live in ~/_agent_scratch/juicebox/renders; encode writes the manifest, sounds.json,
into the site repo's demo folder, and upload puts each file in R2, served at /audio/demos/juice-box/<file>.
Each Live step is checked; keep runs short and supervised.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ops  # noqa: E402  - the rig environment first
from ops import L  # noqa: E402

CORE = Path("/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Core Library/Samples")
OUT = ops.SCRATCH / "renders"
DEMOS = Path("~/_agent_scratch/site/demos").expanduser()
SPB = 0.5                                  # seconds per beat at 120 BPM
TAIL = 2.5                                 # seconds after the last layer dies, for reverb and delay

ROLES = {   # devices on each lane, sends in dB (A-Reverb, B-Delay; None is off)
    "thump": (("Compressor", "Saturator"), (None, None)),
    "slap": (("Compressor", "Saturator"), (-16, -24)),
    "wood": (("Compressor",), (-14, -22)),
    "click": ((), (-22, None)),
    "shine": ((), (-6, -10)),
    "air": ((), (-10, -20)),
}
from layers import N, S, SCALE  # noqa: E402


def sounds() -> dict:
    out = {}
    for k in range(8):
        out[f"button-{k + 1}"] = [
            S("thump", "Kick Felt Crack.wav", 0, -8), S("slap", "Perc Slap 2.wav", 0, -2, SCALE[k]),
            S("click", "Wood Resonant Knock.wav", 0, -10, SCALE[k]), N(40, 0, 0.07, 90),
        ] + ([S("shine", "Music Box C4.aif", 0.01, -14 + k, 12 + SCALE[k])] if k >= 2 else [])
    out["button-combo"] = [
        S("thump", "Kick Felt Crack.wav", 0, -3), S("thump", "Tom Floor Stick Center.wav", 0, -8),
        S("slap", "Clap Foley.aif", 0, -4), S("slap", "Perc Slap 3.wav", 0, -4),
        *[S("shine", "Celeste C6.wav", 0.04 + 0.05 * i, -8, st) for i, st in enumerate((-12, -8, -5, 0))],
        S("shine", "Chimes Jingle Bell.aif", 0.05, -10), N(33, 0, 0.45, 127),
    ]
    out["chest-rattle"] = [
        S("click", "Foley Door Lock.wav", 0, -4), S("slap", "Wood Insert Cassette.wav", 0.12, -10),
        *[S("wood", "Perc Knock Rattle.wav", t, db, st) for t, db, st in
          ((0.08, -12, 0), (0.15, -10, 0), (0.21, -8, 2), (0.27, -6, -1), (0.33, -5, 0))],
        S("shine", "Triangle Short.wav", 0.38, -20),
    ]
    out["chest-open"] = [
        S("thump", "Kick Thud.aif", 0, -4), S("wood", "Wood Rough Low.aif", 0, -4, -3),
        S("click", "Wood Clack.wav", 0, -10, -5),
        *[S("slap", "Foley Coin LDre.wav", t, db, st) for t, db, st in
          ((0.05, -6, 0), (0.14, -9, 3), (0.24, -11, -2), (0.36, -13, 5))],
        *[S("shine", "Celeste C6.wav", 0.06 + 0.06 * i, -9, st) for i, st in enumerate((-12, -8, -5, 0, 4))],
        S("shine", "Chimes Jingle Bell.aif", 0.1, -8), N(33, 0, 0.3, 120),
    ]
    for k, st in enumerate((0, 2, 4, 7)):
        out[f"coin-{k + 1}"] = [
            S("shine", "Celeste C6.wav", 0, -12, st - 5), S("shine", "Celeste C6.wav", 0.06, -10, st),
            S("click", "Tamb Metal.wav", 0, -16), S("slap", "Foley Coin LDre.wav", 0, -14, 7),
        ]
    out["gift-charge"] = [
        *[S("air", "Shaker Egg.aif", 0.1 * i, -16 + 2.7 * i, i) for i in range(4)],
        *[S("wood", "Perc Knock Rattle.wav", t, db) for t, db in ((0.05, -16), (0.18, -13), (0.3, -10))],
        S("click", "Wood Scrape.aif", 0.36, -12, 5),
    ]
    out["gift-pop"] = [
        S("thump", "Kick Soap Box Slap.wav", 0, -3), S("slap", "Snare Box Slap.aif", 0, -6),
        S("slap", "Clap Foley.aif", 0.005, -8), S("air", "Paper LDre.wav", 0, -14),
        S("shine", "Chimes Jingle Bell.aif", 0.02, -6), S("shine", "Triangle Short.wav", 0.06, -12),
        S("shine", "Celeste C6.wav", 0.09, -12), S("shine", "Celeste C6.wav", 0.14, -14, 7), N(38, 0, 0.12, 110),
    ]
    out["gem"] = [
        *[S("shine", "Celeste C6.wav", 0.05 * i, -8, st) for i, st in enumerate((-12, -5, 0, 4, 7))],
        S("shine", "Bell Brooklyn C5.aif", 0, -10, 7), S("shine", "Triangle Open.aif", 0.2, -14),
        S("click", "Tamb Metal.wav", 0, -14), N(45, 0, 0.06, 60),
    ]
    for k, (st, db) in enumerate(((-2, 0), (-3, 1))):
        out[f"crate-hit-{k + 1}"] = [
            S("thump", "Kick Felt Crack.wav", 0, -3 + db), S("wood", "Wood Rough Low.aif", 0, -2 + db, st + 2),
            S("slap", "Perc Wood.aif", 0, -6 + db, st), S("click", "Wood Clack.wav", 0, -12), N(38, 0, 0.09, 110),
        ] + ([S("wood", "FX Broken Box.wav", 0.01, -14)] if k else [])
    out["crate-smash"] = [
        S("thump", "Kick Thud.aif", 0, -2), S("thump", "Tom Floor Stick Center.wav", 0, -6),
        S("wood", "FX Broken Box.wav", 0, -2), S("wood", "Wood Rough Low.aif", 0.01, -4, -5),
        S("slap", "Snare Crack It.wav", 0, -6), S("slap", "Clap Foley.aif", 0, -10),
        S("wood", "Wood Block Low.aif", 0.16, -12, -3), S("wood", "Wood Dry Low.aif", 0.25, -12, 2),
        S("wood", "Perc Wood.aif", 0.34, -14, -4), S("click", "Wood Resonant Knock.wav", 0.47, -16, -2),
        S("wood", "Wood Lofi Twig.wav", 0.58, -14), S("click", "Wood Clack.wav", 0.7, -20, -7),
        S("air", "Shaker Egg.aif", 0.1, -18, -7), N(29, 0, 0.7, 127),
    ]
    for k in range(3):
        out[f"egg-tap-{k + 1}"] = [
            S("slap", "Perc Foley Tap.wav", 0, -4, k), S("click", "Hihat Closed Teacup.aif", 0, -16, k),
        ] + ([S("click", "Hihat Foot Crack.wav", 0.02, -12)] if k == 2 else [])
    out["egg-rumble"] = [
        *[S("slap", "Perc Foley Tap.wav", 0.063 * i, -18 + 2 * i, 2 * (i % 2)) for i in range(9)],
        S("wood", "Perc Knock Rattle.wav", 0.3, -12),
    ]
    out["egg-hatch"] = [
        S("click", "Hihat Foot Crack.wav", 0, -4), S("shine", "Broken Glass.wav", 0, -14, 5),
        S("slap", "Snare Crack It.wav", 0, -8, 3), S("thump", "Kick Rounded Impact.wav", 0, -10),
        *[S("shine", "E-Perc Chirpster.aif", t, db, st) for t, db, st in ((0.12, -8, 19), (0.21, -9, 21), (0.28, -8, 24))],
        S("shine", "Celeste C6.wav", 0.1, -14), N(40, 0, 0.1, 80),
    ]
    out["jar-jiggle"] = [S("click", "Perc Glass Low.aif", t, db, st) for t, db, st in
                         ((0, -14, 0), (0.08, -12, 2), (0.15, -10, 1), (0.22, -9, 3), (0.29, -8, 2))]
    out["jar-pop"] = [
        S("slap", "Perc Snap Tap.wav", 0, -3, -2), S("thump", "Kick Slappy.wav", 0, -10),
        S("click", "Wood Scrape.aif", 0, -14, 3), S("shine", "Perc Glass Low.aif", 0.03, -8, 5),
        *[S("shine", "Celeste C6.wav", 0.1 + 0.07 * i, -16 + i * 0.8, st) for i, st in enumerate((0, 4, 7, 11, 12, 16))],
        S("shine", "Triangle Short.wav", 0.2, -16), N(45, 0, 0.05, 70),
    ]
    for k, st in enumerate((0, 3, 5)):
        out[f"firefly-{k + 1}"] = [
            S("shine", "Celeste C6.wav", 0, -10, 7 + st), S("shine", "Triangle Short.wav", 0, -18, st),
            S("click", "Tamb Metal.wav", 0, -18),
        ]
    out["respawn"] = [S("wood", "Wood Block High.aif", 0, -10, 2), S("air", "Shaker Egg.aif", 0, -18)]
    out["firework"] = [
        S("thump", "Impact Gunshot.wav", 0, -6), S("thump", "Kick Thud.aif", 0, -6),
        *[S("slap", "Snare Crackle Basket.wav", t, db, st) for t, db, st in ((0.12, -10, 0), (0.28, -12, 2), (0.45, -14, -2))],
        S("shine", "Broken Glass.wav", 0.1, -16, 7), S("shine", "Chimes Jingle Bell.aif", 0.2, -14), N(31, 0, 0.4, 120),
    ]
    out["finale"] = [
        S("thump", "Kick Thud.aif", 0, -2), S("thump", "Tom Floor Stick Center.wav", 0, -5),
        S("slap", "Clap Foley.aif", 0, -6),
        *[S("shine", "Celeste C6.wav", 0.07 * i, -8, st) for i, st in enumerate((-24, -20, -17, -12, -8, -5, 0))],
        *[S("shine", "Bell Brooklyn C5.aif", 0.5, db, st) for db, st in ((-8, 0), (-10, 4), (-11, 7))],
        S("shine", "Triangle Open.aif", 0.5, -12), S("shine", "Chimes Jingle Bell.aif", 0.5, -8), N(29, 0, 1.0, 127),
    ]
    return out


def kits() -> dict:
    """Each demo's sounds, where its manifest goes and what its files are called. Juice Box kept its first names."""
    from chess import sounds as chess
    return {
        "juice-box": {"sounds": sounds, "site": DEMOS / "12/juice-box", "render": OUT / "juice-all.wav",
                      "slots": ops.SCRATCH / "slots.json", "web": OUT / "web"},
        "four-by-four": {"sounds": chess, "site": DEMOS / "11/four-by-four", "render": OUT / "four-by-four-all.wav",
                         "slots": ops.SCRATCH / "four-by-four-slots.json", "web": OUT / "web-four-by-four"},
    }


KIT = sys.argv[2] if len(sys.argv) > 2 else "juice-box"
K = kits()[KIT]
BUCKET = f"anthonybecker-audio/audio/demos/{KIT}"


# ---- samples ----------------------------------------------------------------------------------------------------------
_FILES: dict[str, Path] = {}


def sample(name: str) -> Path:
    if not _FILES:
        _FILES.update({p.name: p for p in CORE.rglob("*") if p.suffix.lower() in (".wav", ".aif", ".aiff")})
    if name not in _FILES:
        sys.exit(f"STOP: no sample {name}")
    return _FILES[name]


_LIFE: dict[str, float] = {}


def life(name: str) -> float:
    """Seconds until the sample stays under -60 dB of its peak (at its own speed)."""
    if name not in _LIFE:
        import numpy as np
        import soundfile as sf
        y, sr = sf.read(sample(name), always_2d=True)
        a = np.abs(y).max(axis=1)
        _LIFE[name] = (np.where(a > a.max() * 1e-3)[0].max() + 1) / sr
        _LIFE[name + "#len"] = len(a) / sr
    return _LIFE[name]


def length(name: str) -> float:
    life(name)
    return _LIFE[name + "#len"]


def plan() -> tuple[list, dict, float]:
    """Each sound's slot (start, seconds), the clips laid on role lanes, and the timeline's length in beats."""
    lanes: dict[str, list[float]] = {r: [] for r in ROLES}     # per role: each lane's end, in seconds
    clips, notes, slots, at = [], [], {}, 0.0
    for name, layers in K["sounds"]().items():
        end = 0.0
        for layer in layers:
            if layer[0] == "n":
                _, pitch, t, ln, vel = layer
                notes.append((pitch, at + t, ln, vel))
                end = max(end, t + ln + 0.3)
                continue
            _, role, smp, t, db, st = layer
            speed = 2 ** (st / 12)
            busy = life(smp) / speed + 0.05     # a later clip on the lane trims this one, harmless once it has died
            end = max(end, t + life(smp) / speed)
            start = at + t
            free = [i for i, e in enumerate(lanes[role]) if e <= start + 1e-6]
            lane = free[0] if free else len(lanes[role])
            if lane == len(lanes[role]):
                lanes[role].append(0.0)
            lanes[role][lane] = start + busy
            clips.append((role, lane, smp, start, db, st))
        secs = math.ceil((end + TAIL) / SPB / 2) * 2 * SPB          # whole half-bars
        slots[name] = (at, secs)
        at += secs
    return clips, {"notes": notes, "lanes": {r: len(v) for r, v in lanes.items()}, "slots": slots}, at / SPB


# ---- the set ----------------------------------------------------------------------------------------------------------
def tracks() -> list[str]:
    return L.run("result = [t.name for t in song.tracks]")


def lane_name(role: str, i: int) -> str:
    return f"{role} {i + 1}"


def build() -> None:
    _, info, beats = plan()
    names = tracks()
    if names[0] not in ("Sine", "1-MIDI", "1-Operator"):
        sys.exit(f"STOP: not the JUICE set: {names}")
    L.run("song.tempo = 120.0\nresult = 'ok'")
    if names[0] != "Sine":
        while len(tracks()) > 1:
            L.run("song.delete_track(len(song.tracks) - 1)\nresult = 'ok'")
        L.run("song.tracks[0].name = 'Sine'\nresult = 'ok'")
        if L.devices("song.tracks[0]") != ["Operator"]:
            sys.exit(f"STOP: Sine has {L.devices('song.tracks[0]')}")
        sine_voice()
        L.load_item("song.tracks[0]", "audio_effects", None, "Saturator")
        L.setp("song.tracks[0].devices[1]", {"Drive": "6 dB", "Type": "Soft Sine", "Output": "-3 dB"})
        L.mixer("song.tracks[0]", -2.0, (None, None))
    have = tracks()
    for role, n in info["lanes"].items():
        fx, sends = ROLES[role]
        for i in range(n):
            if lane_name(role, i) in have:
                continue
            L.run(f"song.create_audio_track(-1)\nsong.tracks[-1].name = {lane_name(role, i)!r}\nresult = 'ok'")
            idx = len(tracks()) - 1
            for d in fx:
                L.load_item(f"song.tracks[{idx}]", "audio_effects", None, d)
            if L.devices(f"song.tracks[{idx}]") != list(fx):
                sys.exit(f"STOP: {lane_name(role, i)} has {L.devices(f'song.tracks[{idx}]')}")
            lane_fx(role, idx)
            L.mixer(f"song.tracks[{idx}]", 0.0, sends)
    for d in ("Glue Compressor", "Limiter"):
        if d not in L.devices("song.master_track"):
            L.load_item("song.master_track", "audio_effects", None, d)
    if L.devices("song.master_track") != ["Glue Compressor", "Limiter"]:
        sys.exit(f"STOP: Main has {L.devices('song.master_track')}")
    L.setp("song.master_track.devices[0]", {"Threshold": "-16 dB", "Ratio": 1, "Attack": 4, "Release": 0,
                                            "Output": "3 dB"})
    L.setp("song.master_track.devices[1]", {"Ceiling": "-2 dB"})
    L.setp("song.return_tracks[0].devices[0]", {"Decay Time": "1.8 s", "Predelay": "15 ms", "Dry/Wet": "100 %"})
    L.setp("song.return_tracks[1].devices[0]", {"Ping Pong": "On", "Link": "On", "L 16th": "3", "Feedback": "30 %",
                                                "Filter On": "On", "Filter Freq": "3 kHz", "Dry/Wet": "100 %"})
    print("lanes:", info["lanes"], f"timeline {beats:.0f} beats ({beats * SPB:.0f} s)")


def sine_voice() -> None:
    """A sine with a fast pitch drop and a sine an octave up that dies in 80 ms; sustain, so length is boom."""
    op = "song.tracks[0].devices[0]"
    L.setp(op, {"Algorithm": "Alg. 11", "Osc-B On": "On", "Osc-C On": "Off", "Osc-D On": "Off",
                "Ae Attack": "0 ms", "Ae Init": 0.0, "Ae Peak": 1.0, "Osc-A Lev < Vel": 0.8, "Osc-A Wave": "Sine",
                "Ae Decay": "220 ms", "Ae Sustain": 0.35, "Ae Release": "200 ms", "B Coarse": 2,
                "Osc-B Wave": "Sine", "Osc-B Level": "-10 dB", "Be Attack": "0 ms", "Be Decay": "80 ms",
                "Be Sustain": 0.0, "Be Release": "40 ms"})
    L.setp(op, {"Pe On": "On", "Pe Init": 30, "Pe Peak": 30, "Pe Attack": "0 ms", "Pe Decay": "55 ms",
                "Pe Sustain": 0.0, "Pe End": 0, "Pe Amount": 1.0, "Filter On": "On", "Filter Type": "Lowpass",
                "Filter Freq": "2 kHz", "Filt < Key": 0.0})


def lane_fx(role: str, idx: int) -> None:
    # Compressor Ratio is raw 1 - 1/ratio (0.75 is 4:1); its display reads "inf" at the top, which the search cannot use
    t = f"song.tracks[{idx}]"
    if role == "thump":
        L.setp(f"{t}.devices[0]", {"Threshold": "-18 dB", "Ratio": 0.75, "Attack": "10 ms", "Release": "120 ms",
                                   "Output": "3 dB"})
        L.setp(f"{t}.devices[1]", {"Drive": "4 dB", "Type": "Soft Sine", "Output": "-2 dB"})
    elif role == "slap":
        L.setp(f"{t}.devices[0]", {"Threshold": "-24 dB", "Ratio": 0.8, "Attack": "3 ms", "Release": "50 ms",
                                   "Output": "6 dB"})
        L.setp(f"{t}.devices[1]", {"Drive": "5 dB", "Type": "Analog Clip", "Output": "-2 dB"})
    elif role == "wood":
        L.setp(f"{t}.devices[0]", {"Threshold": "-18 dB", "Ratio": 0.6667, "Attack": "5 ms", "Release": "80 ms",
                                   "Output": "3 dB"})


GAIN = r'''
def _gain(c, db):
    lo, hi = 0.001, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        c.gain = mid
        v = float(c.gain_display_string.split()[0].replace('-inf', '-999'))
        if v < db: lo = mid
        else: hi = mid
    c.gain = hi
'''


def score() -> None:
    clips, info, beats = plan()
    idx = {n: i for i, n in enumerate(tracks())}
    for role, n in info["lanes"].items():
        for i in range(n):
            if lane_name(role, i) not in idx:
                sys.exit(f"STOP: no lane {lane_name(role, i)}; run build")
    # clear what a previous score left
    L.run("for t in song.tracks:\n    for c in list(t.arrangement_clips):\n        t.delete_clip(c)\nresult = 'ok'")
    for k in range(0, len(clips), 8):
        code = GAIN
        for role, lane, smp, start, db, st in clips[k:k + 8]:
            code += (f"t = song.tracks[{idx[lane_name(role, lane)]}]\n"
                     f"c = t.create_audio_clip({str(sample(smp))!r}, {start / SPB!r})\n"
                     f"c.warping = False\nc.pitch_coarse = {st}\n_gain(c, {db})\n")
        L.run(code + "result = 'ok'")
    L.run(f"song.tracks[0].create_midi_clip(0.0, {math.ceil(beats)}.0)\nresult = 'ok'")
    specs = ",".join(f"Live.Clip.MidiNoteSpecification(pitch={p}, start_time={t / SPB!r}, duration={ln / SPB!r}, "
                     f"velocity={float(v)})" for p, t, ln, v in info["notes"])
    L.run(f"import Live\nc = song.tracks[0].arrangement_clips[0]\nc.add_new_notes(({specs},))\nresult = 'ok'")
    got = L.run("result = [(t.name, len(t.arrangement_clips), [c.warping for c in t.arrangement_clips].count(True)) "
                "for t in song.tracks if t.has_audio_input]")
    placed, warped = sum(n for _, n, _ in got), sum(w for _, _, w in got)
    if placed != len(clips) or warped:
        sys.exit(f"STOP: placed {placed} of {len(clips)} clips, {warped} still warped: {got}")
    print(f"{len(clips)} clips, {len(info['notes'])} sine notes, {len(info['slots'])} sounds, {beats:.0f} beats")
    K["slots"].write_text(json.dumps(info["slots"], indent=1))


def render() -> None:
    _, info, beats = plan()
    OUT.mkdir(parents=True, exist_ok=True)
    r = K["render"]
    if r.exists():
        r.rename(r.with_name(f"{r.stem}-{int(r.stat().st_mtime)}.wav"))
    print(L.export(r, 0, math.ceil(beats), bits=24))


def cut():
    import numpy as np
    import soundfile as sf
    y, sr = sf.read(K["render"], always_2d=True)
    slots = json.loads(K["slots"].read_text())
    for name, (at, secs) in slots.items():
        seg = y[int(round(at * sr)):int(round((at + secs) * sr))]
        a = np.abs(seg).max(axis=1)
        last = np.where(a > 10 ** (-80 / 20))[0]
        yield name, seg[:(last.max() + int(0.01 * sr)) if len(last) else 0], sr


def measure() -> None:
    import numpy as np
    for name, seg, sr in cut():
        m = seg.mean(axis=1)
        a = np.abs(m)
        pk = a.max()
        on = int(np.argmax(a > pk * 0.1))
        S = np.abs(np.fft.rfft(m[:int(0.5 * sr)] * np.hanning(min(len(m), int(0.5 * sr))))) ** 2
        f = np.fft.rfftfreq(min(len(m), int(0.5 * sr)), 1 / sr)
        tot = S.sum() + 1e-12
        band = lambda lo, hi: S[(f >= lo) & (f < hi)].sum() / tot
        tail = m[int(0.5 * sr):]
        wet = 20 * np.log10(np.sqrt((tail ** 2).mean()) / np.sqrt((m[:int(0.5 * sr)] ** 2).mean()) + 1e-9) if len(tail) else -99
        print(f"{name:14s} peak {20 * np.log10(pk + 1e-12):5.1f} dBFS onset {on / sr * 1000:4.1f} ms len {len(m) / sr:4.2f} s "
              f"low {band(0, 150):4.0%} mid {band(150, 2000):4.0%} hi {band(4000, 22050):4.0%} tail/head {wet:5.1f} dB")


def encode() -> None:
    import soundfile as sf
    web = K["web"]
    web.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, seg, sr in cut():
        wav, m4a = web / f"{name}.wav", web / f"{name}.m4a"
        sf.write(wav, seg, sr, subtype="PCM_16")
        m4a.unlink(missing_ok=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "160000", str(wav), str(m4a)], check=True)
        named = web / f"{name}-{hashlib.sha256(m4a.read_bytes()).hexdigest()[:8]}.m4a"
        m4a.replace(named)
        manifest[name] = named.name
        print(named.name, f"{len(seg) / sr:.2f} s", f"{named.stat().st_size // 1024} KB")
    (K["site"] / "sounds.json").write_text(json.dumps(manifest, indent=1) + "\n")


def upload() -> None:
    web = K["web"]
    for file in json.loads((K["site"] / "sounds.json").read_text()).values():
        subprocess.run(["npx", "--yes", "wrangler", "r2", "object", "put", f"{BUCKET}/{file}", "--file", str(web / file),
                        "--content-type", "audio/mp4", "--cache-control", "public, max-age=31536000, immutable",
                        "--remote"], check=True)


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["help"])[0]
    {"build": build, "score": score, "render": render, "measure": measure, "encode": encode, "upload": upload,
     "plan": lambda: print(json.dumps(plan()[1]["lanes"]), f"{plan()[2]:.0f} beats")}.get(cmd, lambda: print(__doc__))()
