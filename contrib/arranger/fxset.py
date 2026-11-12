"""Transition sounds for the HW002 arranger, made in Live: risers, downlifters, reverse reverbs, bass scoops and drum
fills, many of each, for every section change of the canonical arrangement (8d2a2). The transitions page
(static/transitions.html) plays them over the arrangement at a section change so they can be compared and picked; what
it writes is a structure (the picks, with each one's recipe from fx.json), which is then built into the set in Live.

With HW002_121_pp_fx (a Save As of HW002_121_pp_loops) in front in Live:

    uv run --project hands python contrib/arranger/fxset.py build       # tracks and devices
    uv run --project hands python contrib/arranger/fxset.py notes       # MIDI and audio clips, one slot per candidate
    uv run --project hands python contrib/arranger/fxset.py save        # File > Save Live Set
    uv run --project hands python contrib/arranger/fxset.py automate    # the .als plus automation, as HW002_121_pp_fxa.als
    open -a "Ableton Live 12 Suite" ~/_agent_scratch/HW002/HW002_121_pp_fxa.als
    uv run --project hands python contrib/arranger/fxset.py render      # one export per solo state (about 10 minutes)
    uv run --project ears python contrib/arranger/fxset.py cut          # one file per candidate, and fx.json

Everything is made in Live, in HW002_121_pp_fx.als (a copy of HW002_121_pp_loops), through the set's own tracks,
groups and Main. The candidates sit one after another past the end of the song, from beat FX0, each in a slot of
SLOT beats whose section change ("the seam") is SEAM beats into the slot. A scoop or a kick fill is the kick and
rumble's 4-bar pass (the arranger's kick-rumble-a) played again in a slot with the kick group's own chain, an EQ Eight
and a Utility added at its end. A reverse reverb is the set's own hit (the chord at the drop, the horn, a crash, a
splash) where the song plays it, let through a Utility into a Reverb at 100% wet, rendered and then turned around
(what Live's Rev button does). The rule this works under is in contrib/docs/sound.md.
"""
from __future__ import annotations

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path("~/_agent_scratch/arranger").expanduser()
FX = DATA / "fx"
SETS = Path("~/_agent_scratch/HW002").expanduser()
SET = "HW002_121_pp_fx"           # built through the LOM (build, notes, save)
ALS = SETS / f"{SET}.als"
RSET = "HW002_121_pp_fxa"         # the same with the automation written in (automate); rendered from (render)
RALS = SETS / f"{RSET}.als"

FX0 = 1200.0        # first beat of the candidate slots, past the end of the song (1168 beats)
SLOT = 56.0         # 14 bars a slot
SEAM = 32.0         # the section change, 8 bars into the slot
BAR = 4.0

# The set's tracks by index (see bounce.py) and the ones added here, by name.
KICK_GROUP, KICK, RUMBLE, CRASH, PERC1, PERC2, SPLASH, CHORD, HORN = 1, 2, 3, 5, 6, 7, 9, 11, 15
NEW = {"fx noise": "Operator", "fx tone": "Operator", "fx kit": "909 Core Kit.adg"}
RUMBLE_FILE = "(Bounce) [2026-05-17 105034].aif"   # the rumble's looped 16-beat clip

# Drum-rack pads (in_note), read from the set.
KICK1, OFFBEAT = 44, 40                                         # kick rack: the kick, the off-beat 16ths
P2_CH1, P2_CH27, P2_OH, P2_RD1, P2_RD2 = 127, 120, 60, 33, 32  # perc 2
P1_OH66, P1_RD, P1_OH = 120, 83, 117                            # perc 1
K909 = {"kick": 36, "rim": 37, "snare": 38, "clap": 39, "ch": 42, "tom_lo": 43, "oh": 46, "tom_mid": 47, "tom_hi": 50}


@dataclass
class Cand:
    """One transition candidate. Times are beats from the seam (negative before it)."""
    id: str
    kind: str                  # riser | downlifter | reverse | scoop | fill
    title: str
    track: str                 # track key: a NEW name or "kick", "perc1", "perc2", a source for reverse
    start: float               # where its file starts, from the seam
    end: float                 # where its file ends, from the seam
    seams: tuple = (9, 17, 25, 33, 41)
    mode: str = "add"          # add: played over the arrangement; replace: plays instead of `lane` from start to end
    lane: str = ""
    notes: list = field(default_factory=list)      # (beat from seam, pitch, length, velocity)
    auto: dict = field(default_factory=dict)       # param key -> [(beat from seam, value)], ramps between points
    src: dict = field(default_factory=dict)        # reverse: {"beat": song beat of the hit, "reverb": setting}
    slot: int = -1

    @property
    def seam_beat(self) -> float:
        return FX0 + self.slot * SLOT + SEAM


# ---- the candidates ----------------------------------------------------------------------------------------------------

def _exp(a: float, b: float, t0: float, t1: float, n: int = 12) -> list:
    """Points for a sweep from a to b between t0 and t1, even in log (for frequencies)."""
    return [(t0 + (t1 - t0) * k / n, a * (b / a) ** (k / n)) for k in range(n + 1)]


def _lin(a: float, b: float, t0: float, t1: float, n: int = 6) -> list:
    return [(t0 + (t1 - t0) * k / n, a + (b - a) * k / n) for k in range(n + 1)]


def _roll(t0: float, t1: float, pitch: int, v0: float, v1: float, rates=(0.5, 0.25, 0.125)) -> list:
    """An accelerating roll from t0 to t1: the span in equal parts, each at the next rate (8ths, 16ths, 32nds), the
    velocity rising from v0 to v1."""
    notes, part = [], (t1 - t0) / len(rates)
    for k, step in enumerate(rates):
        t = t0 + k * part
        while t < t0 + (k + 1) * part - 1e-6:
            notes.append((t, pitch, step * 0.9, v0 + (v1 - v0) * (t - t0) / (t1 - t0)))
            t += step
    return notes


def _even(t0: float, t1: float, step: float, pitch: int, v0: float, v1: float, length: float | None = None) -> list:
    n = round((t1 - t0) / step)
    return [(t0 + k * step, pitch, length or step * 0.9, v0 + (v1 - v0) * k / max(1, n - 1)) for k in range(n)]


SOURCES = {   # reverse-reverb sources: the set's own hit where the song plays it (song beat), and the seams it leads into
    "horn-b": (HORN, 360.0, (9, 33)), "horn-a": (HORN, 320.0, (41,)), "chord": (CHORD, 64.0, (17,)),
    "crash": (CRASH, 256.0, (17, 25, 33)), "splash-c": (SPLASH, 104.0, (9, 25)), "splash-d": (SPLASH, 384.0, (17,)),
    "splash-b": (SPLASH, 72.0, (41,)),
}
REVERBS = {   # Reverb settings, one render each
    "room": {"Decay Time": "1.20 s", "Room Size": 40.0, "Diffusion": "60 %"},
    "hall": {"Decay Time": "4.00 s", "Room Size": 100.0, "Diffusion": "80 %"},
    "huge": {"Decay Time": "12.0 s", "Room Size": 200.0, "Diffusion": "100 %"},
}
KICK_SEAMS = (25, 33, 41)      # the kick plays in the bars before these
KICK_IN_SEAMS = (17, 25, 33)   # and in the bars after these


def candidates() -> list[Cand]:
    C: list[Cand] = []
    B = BAR
    # noise risers, ending on the seam: a filter opening, the level rising 30 dB
    for bars in (1, 2, 4, 8):
        C.append(Cand(f"nr-lp-{bars}", "riser", f"Noise riser, low-pass opening, {bars} bar{'s' * (bars > 1)}", "fx noise",
                      -bars * B, 0.0, notes=[(-bars * B, 60, bars * B, 100)],
                      auto={"type": [(-bars * B, "Low-pass")], "res": [(-bars * B, 20.0)],
                            "freq": _exp(200, 16000, -bars * B, 0.0), "gain": _lin(-30, 0, -bars * B, 0.0)}))
    for bars in (2, 4, 8):
        C.append(Cand(f"nr-hp-{bars}", "riser", f"Noise riser, high-pass thinning, {bars} bars", "fx noise",
                      -bars * B, 0.0, notes=[(-bars * B, 60, bars * B, 100)],
                      auto={"type": [(-bars * B, "High-pass")], "res": [(-bars * B, 10.0)],
                            "freq": _exp(40, 8000, -bars * B, 0.0), "gain": _lin(-24, 0, -bars * B, 0.0)}))
        C.append(Cand(f"nr-bp-{bars}", "riser", f"Noise riser, resonant band sweeping up, {bars} bars", "fx noise",
                      -bars * B, 0.0, notes=[(-bars * B, 60, bars * B, 100)],
                      auto={"type": [(-bars * B, "Band-pass")], "res": [(-bars * B, 60.0)],
                            "freq": _exp(300, 9000, -bars * B, 0.0), "gain": _lin(-24, 0, -bars * B, 0.0)}))
    for bars in (2, 4):   # chopped: 8ths for the first half, 16ths for the second
        n = bars * B
        mute = [(-n + 0.25 * j, j % 2 == 1) for j in range(int(n * 2))]            # first half: a pulse every 8th
        mute += [(-n / 2 + 0.125 * j, j % 2 == 1) for j in range(int(n * 4))]      # second half: every 16th
        mute = [(t, m) for t, m in mute if t < 0] + [(0.0, False)]
        mute = sorted({t: m for t, m in mute}.items())
        C.append(Cand(f"nr-gate-{bars}", "riser", f"Noise riser, chopped in 8ths then 16ths, {bars} bars", "fx noise",
                      -n, 0.0, notes=[(-n, 60, n, 100)],
                      auto={"type": [(-n, "Low-pass")], "res": [(-n, 20.0)], "freq": _exp(300, 16000, -n, 0.0),
                            "gain": _lin(-24, 0, -n, 0.0), "mute": mute}))
    for beats in (1, 2):
        C.append(Cand(f"nr-swell-{beats}b", "riser", f"Noise swell, {beats} beat{'s' * (beats > 1)}", "fx noise",
                      -beats, 0.0, notes=[(-beats, 60, beats, 100)],
                      auto={"type": [(-beats, "Low-pass")], "res": [(-beats, 15.0)],
                            "freq": _exp(1000, 16000, -beats, 0.0, 6), "gain": _lin(-20, 0, -beats, 0.0, 4)}))
    # pitched risers: Operator's pitch envelope climbs over the whole length
    for wave, top, lens in (("saw", 24, (2, 4, 8)), ("sine", 36, (4, 8))):
        for bars in lens:
            C.append(Cand(f"pr-{wave}-{bars}", "riser", f"Pitch riser, {wave}, up {top // 12} octaves, {bars} bars", "fx tone",
                          -bars * B, 0.0, notes=[(-bars * B, 48, bars * B, 100)],
                          auto={"wave": [(-bars * B, "Saw D" if wave == "saw" else "Sine")],
                                "pe_peak": [(-bars * B, float(top))], "pe_attack": [(-bars * B, bars * B * 375.0)],
                                "pe_decay": [(-bars * B, 50.0)], "pe_sustain": [(-bars * B, float(top))],
                                "type": [(-bars * B, "Low-pass")], "res": [(-bars * B, 10.0)],
                                "freq": _exp(400, 12000, -bars * B, 0.0), "gain": _lin(-24, -3, -bars * B, 0.0)}))
    # downlifters, from the seam
    for bars in (1, 2, 4):
        C.append(Cand(f"dl-lp-{bars}", "downlifter", f"Noise downlifter, low-pass closing, {bars} bar{'s' * (bars > 1)}",
                      "fx noise", 0.0, bars * B, notes=[(0.0, 60, bars * B, 100)],
                      auto={"type": [(0.0, "Low-pass")], "res": [(0.0, 20.0)], "freq": _exp(16000, 150, 0.0, bars * B),
                            "gain": _lin(0, -36, 0.0, bars * B)}))
    for bars in (1, 2):
        C.append(Cand(f"dl-bp-{bars}", "downlifter", f"Noise downlifter, resonant band falling, {bars} bar{'s' * (bars > 1)}",
                      "fx noise", 0.0, bars * B, notes=[(0.0, 60, bars * B, 100)],
                      auto={"type": [(0.0, "Band-pass")], "res": [(0.0, 60.0)], "freq": _exp(9000, 200, 0.0, bars * B),
                            "gain": _lin(0, -30, 0.0, bars * B)}))
    for wave, bars in (("sine", 1), ("sine", 2), ("saw", 1)):
        C.append(Cand(f"dl-{'sub' if wave == 'sine' else 'saw'}-{bars}", "downlifter",
                      f"{'Sub drop, sine' if wave == 'sine' else 'Saw drop'}, down 2 octaves, {bars} bar{'s' * (bars > 1)}",
                      "fx tone", 0.0, bars * B, notes=[(0.0, 48, bars * B, 100)],
                      auto={"wave": [(0.0, "Sine" if wave == "sine" else "Saw D")], "pe_peak": [(0.0, 0.0)],
                            "pe_attack": [(0.0, 0.0)], "pe_decay": [(0.0, bars * B * 375.0)], "pe_sustain": [(0.0, -24.0)],
                            "type": [(0.0, "Low-pass")], "res": [(0.0, 10.0)],
                            "freq": _exp(8000 if wave == "saw" else 16000, 300 if wave == "saw" else 16000, 0.0, bars * B),
                            "gain": _lin(0, -12, 0.0, bars * B)}))
    # reverse reverbs: the incoming section's own first hit, its reverb tail turned around to end on the seam
    for src, (_, hit, seams) in SOURCES.items():
        for verb in REVERBS:
            for beats in (2, 4, 8):
                C.append(Cand(f"rv-{src}-{verb}-{beats}", "reverse",
                              f"Reverse reverb of the {src.replace('-', ' ')}, {verb}, {beats // 4 or beats} "
                              f"{'beats' if beats < 4 else 'bar' + 's' * (beats > 4)}",
                              src, -float(beats), 0.0, seams=seams, src={"beat": hit, "reverb": verb}))
    # bass scoops on the kick and rumble: a 4-bar pass of the kick that replaces the lane's bars
    hp = lambda t0, t1: _exp(10, 250, t0, t1, 8)   # noqa: E731 - the high-pass climbing into the seam
    pre = [("sc-hp-1b", "High-pass sweep, last beat", {"hp": [(-16.0, 10.0)] + hp(-1.0, 0.0)}),
           ("sc-hp-2b", "High-pass sweep, last 2 beats", {"hp": [(-16.0, 10.0)] + hp(-2.0, 0.0)}),
           ("sc-hp-1bar", "High-pass sweep, last bar", {"hp": [(-16.0, 10.0)] + hp(-4.0, 0.0)}),
           ("sc-hp-2bar", "High-pass sweep, last 2 bars", {"hp": [(-16.0, 10.0)] + hp(-8.0, 0.0)}),
           ("sc-cut-1b", "Low end cut at 300 Hz, last beat", {"hp": [(-16.0, 10.0), (-1.0, 10.0), (-1.0, 300.0)]}),
           ("sc-cut-2b", "Low end cut at 300 Hz, last 2 beats", {"hp": [(-16.0, 10.0), (-2.0, 10.0), (-2.0, 300.0)]}),
           ("sc-shelf-1bar", "Low shelf down 15 dB, last bar", {"shelf": [(-16.0, 0.0)] + _lin(0, -15, -4.0, 0.0, 4)}),
           ("sc-mute-half", "Kick and rumble out, last half beat", {"kmute": [(-16.0, False), (-0.5, True)]}),
           ("sc-mute-1b", "Kick and rumble out, last beat", {"kmute": [(-16.0, False), (-1.0, True)]})]
    for cid, title, auto in pre:
        C.append(Cand(cid, "scoop", title, "kick", -16.0, 0.0, seams=KICK_SEAMS, mode="replace", lane="kick", auto=auto))
    for bars in (1, 2, 4):
        C.append(Cand(f"sc-in-{bars}", "scoop", f"Kick comes in high-passed, opening over {bars} bar{'s' * (bars > 1)}",
                      "kick", 0.0, 16.0, seams=KICK_IN_SEAMS, mode="replace", lane="kick",
                      auto={"hp": _exp(300, 10, 0.0, bars * B, 8)}))
    # kick fills: the pass's last bar changed
    kick = lambda t0, t1, step, v0=90, v1=127: [n for p in (KICK1, 50) for n in _even(t0, t1, step, p, v0, v1, 0.2)]  # noqa: E731
    fills = [("kf-16th-1b", "Kick 16ths on the last beat", (-1.0, 0.0), kick(-1.0, 0.0, 0.25)),
             ("kf-16th-2b", "Kick 16ths on the last 2 beats", (-2.0, 0.0), kick(-2.0, 0.0, 0.25)),
             ("kf-8ths-1bar", "Kick 8ths through the last bar", (-4.0, 0.0), kick(-4.0, 0.0, 0.5)),
             ("kf-trip-1b", "Kick triplets on the last beat", (-1.0, 0.0), kick(-1.0, 0.0, 1 / 3)),
             ("kf-roll-1bar", "Kick roll, 8ths to 16ths to 32nds, last bar", (-4.0, 0.0),
              [n for p in (KICK1, 50) for n in _roll(-4.0, 0.0, p, 70, 127, (0.5, 0.25, 0.125))]),
             ("kf-gap-1b", "No kick on the last beat", (-1.0, 0.0), [])]
    for cid, title, span, extra in fills:
        C.append(Cand(cid, "fill", title, "kick", -16.0, 0.0, seams=KICK_SEAMS, mode="replace", lane="kick",
                      notes=extra, src={"clear": span}))
    C.append(Cand("kick-plain", "check", "The kick pass with nothing changed (checks the slot against the loop)", "kick",
                  -16.0, 0.0, seams=(), mode="replace", lane="kick"))
    # hat fills on the set's own hat racks, over the arrangement
    hats = [("hf-ch1-32-1b", "P2 closed 1 in 32nds, last beat", "perc2", _even(-1.0, 0.0, 0.125, P2_CH1, 60, 127)),
            ("hf-ch1-roll-1bar", "P2 closed 1 roll, 16ths to 32nds, last bar", "perc2",
             _roll(-4.0, 0.0, P2_CH1, 50, 127, (0.25, 0.125))),
            ("hf-ch27-trip-2b", "P2 closed 2 in 16th triplets, last 2 beats", "perc2", _even(-2.0, 0.0, 1 / 6, P2_CH27, 60, 127)),
            ("hf-oh-8ths-1bar", "P2 open on every 8th, last bar", "perc2", _even(-4.0, 0.0, 0.5, P2_OH, 70, 127)),
            ("hf-rd1-16-1bar", "P2 ride 1 16ths rising, last bar", "perc2", _even(-4.0, 0.0, 0.25, P2_RD1, 40, 127)),
            ("hf-oh66-16-2b", "P1 open 2 in 16ths, last 2 beats", "perc1", _even(-2.0, 0.0, 0.25, P1_OH66, 60, 127))]
    for cid, title, track, notes in hats:
        C.append(Cand(cid, "fill", title, track, notes[0][0], 0.0, notes=notes))
    # fills on Live's 909 Core Kit (not the set's sounds)
    kit = [("kit-snare-roll-2", "909 snare roll, 8ths to 32nds, 2 bars", _roll(-8.0, 0.0, K909["snare"], 40, 127)),
           ("kit-snare-roll-4", "909 snare roll, 8ths to 32nds, 4 bars", _roll(-16.0, 0.0, K909["snare"], 30, 127)),
           ("kit-snare-roll-8", "909 snare roll, 8ths to 32nds, 8 bars", _roll(-32.0, 0.0, K909["snare"], 25, 127)),
           ("kit-clap-roll-2", "909 clap roll, 16ths to 32nds, 2 bars", _roll(-8.0, 0.0, K909["clap"], 50, 127, (0.25, 0.125))),
           ("kit-toms-1bar", "909 toms down in 16ths, last bar",
            [(-4.0 + 0.25 * k, (K909["tom_hi"], K909["tom_mid"], K909["tom_lo"])[k * 3 // 16], 0.2, 90 + 2 * k) for k in range(16)]),
           ("kit-toms-2b", "909 toms down in 16ths, last 2 beats",
            [(-2.0 + 0.25 * k, (K909["tom_hi"], K909["tom_mid"], K909["tom_lo"])[k * 3 // 8], 0.2, 100 + 3 * k) for k in range(8)]),
           ("kit-snare-32-1b", "909 snare in 32nds, last beat", _even(-1.0, 0.0, 0.125, K909["snare"], 70, 127))]
    for cid, title, notes in kit:
        C.append(Cand(cid, "fill", title, "fx kit", notes[0][0], 0.0, notes=notes))
    # each track's candidates get slots 0, 1, 2 ... in order (each track is rendered on its own)
    count: dict = {}
    for c in C:
        key = c.src.get("reverb") and "reverse" or c.track
        if c.kind != "reverse":
            c.slot = count.get(key, 0)
            count[key] = c.slot + 1
    return C


def env(path: str = "") -> None:
    os.environ["ZPKT_SETS_DIR"] = str(SETS)
    os.environ["ZPKT_SET_PREFIXES"] = "HW002_121_pp_"
    os.environ["ZPKT_DATA_DIR"] = str(FX / "data")
    os.environ["ZPKT_RENDERS_DIR"] = str(FX / "raw")
    sys.path.insert(0, str(ROOT / "hands" / "scripts" / "rummage"))


def lo():
    env()
    import liveops
    liveops.EXPORT_DIR = DATA / "raw"   # a folder the Save panel already knows; export() moves the file to its target
    return liveops


def track_index(L, name: str) -> int:
    names = L.run("result = [t.name for t in song.tracks]")
    if name not in names:
        sys.exit(f"STOP: no track {name!r}")
    return names.index(name)


# ---- build: tracks and devices -----------------------------------------------------------------------------------------

def build() -> None:
    L = lo()
    if L.guard("fx build") != SET:
        sys.exit(f"STOP: {SET} is not in front")
    L.run("for t in song.tracks:\n    if t.is_foldable:\n        t.fold_state = False\nresult = 'ok'")   # a folded group hides its tracks
    names = L.run("result = [t.name for t in song.tracks]")
    for name, instrument in NEW.items():
        if name in names:
            continue
        L.run(f"t = song.create_midi_track(-1)\nt.name = {name!r}\nresult = 'ok'")
        time.sleep(0.5)
        t = f"song.tracks[{track_index(L, name)}]"
        if instrument.endswith(".adg"):
            L.load_item(t, "drums", None, instrument)
        else:
            L.load_item(t, "instruments", None, instrument)
            L.load_item(t, "audio_effects", None, "Auto Filter")
        L.load_item(t, "audio_effects", None, "Utility")
        print(name, L.devices(t), flush=True)
    # the kick group gets an EQ Eight for the scoops and a Utility for the drop-outs, at the end of its chain
    kg = f"song.tracks[{KICK_GROUP}]"
    if L.run(f"result = [d.class_name for d in {kg}.devices][-2:]") != ["Eq8", "StereoGain"]:
        L.load_item(kg, "audio_effects", None, "EQ Eight")
        L.load_item(kg, "audio_effects", None, "Utility")
    print("kick group", L.devices(kg), flush=True)
    # each reverse-reverb source: a Utility (the gate, muted except on the hit) and a Reverb, at the end of its chain
    for i in (CRASH, SPLASH, CHORD, HORN):
        t = f"song.tracks[{i}]"
        if L.run(f"result = [d.class_name for d in {t}.devices][-2:]") != ["StereoGain", "Reverb"]:
            L.load_item(t, "audio_effects", None, "Utility")
            L.load_item(t, "audio_effects", None, "Reverb")
        print(i, L.devices(t), flush=True)


# ---- notes: static settings and the clips in the slots ----------------------------------------------------------------

STATIC = {   # device settings that do not move (the moving ones are automated in the .als)
    ("fx noise", 0): {"Osc-A Wave": "Noise White", "Filter On": "Off", "Ae Attack": "0.00 ms", "Ae Decay": "20.0 s",
                      "Ae Sustain": "0.0 dB", "Ae Release": "20.0 ms", "Osc-A Lev < Vel": "0 %", "Volume": "-12 dB"},
    ("fx tone", 0): {"Osc-A Wave": "Saw D", "Filter On": "Off", "Ae Attack": "0.00 ms", "Ae Decay": "20.0 s",
                     "Ae Sustain": "0.0 dB", "Ae Release": "30.0 ms", "Osc-A Lev < Vel": "0 %", "Volume": "-12 dB",
                     "Pe On": "On", "Osc-A < Pe": "On", "Pe Init": "0 st", "Pe Amount": "100 %", "Pe Release": "0.00 ms",
                     "Pe Mode": "None"},
}


def clip_notes(L, track: str, start: float, length: float, notes: list) -> None:
    """A MIDI clip at `start` (song beats) holding `notes` (beats from the clip start, pitch, length, velocity)."""
    best: dict = {}
    for b, p, d, v in notes:   # Live merges two notes on one pitch and start: keep the louder
        key = (int(p), round(float(b), 4))
        if key not in best or v > best[key][3]:
            best[key] = (b, p, d, v)
    spec = [(int(p), round(float(b), 4), round(float(d), 4), float(min(127, max(1, v)))) for b, p, d, v in sorted(best.values())]
    L.run(f"""import Live
t = {track}
c = t.create_midi_clip({float(start)}, {float(length)})
c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v) for p, s, d, v in {spec!r}))
result = 'ok'""")


def kick_pattern(L) -> list:
    """The kick rack's one-bar pattern as the song loops it."""
    return L.run(f"""c = song.tracks[{KICK}].arrangement_clips[0]
result = sorted((round(n.start_time, 4), n.pitch, round(n.duration, 4), n.velocity) for n in c.get_notes_extended(0, 128, 0.0, 4.0))""")


def notes() -> None:
    L = lo()
    if L.guard("fx notes") != SET:
        sys.exit(f"STOP: {SET} is not in front")
    idx = {name: track_index(L, name) for name in NEW}
    for (name, dev), params in STATIC.items():
        L.setp(f"song.tracks[{idx[name]}].devices[{dev}]", params)
    L.setp(f"song.tracks[{KICK_GROUP}].devices[-2]", {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "10.0 Hz",
                                                     "1 Filter On A": "On", "2 Filter Type A": "Low Shelf",
                                                     "2 Frequency A": "120 Hz", "2 Gain A": "0.00 dB", "2 Filter On A": "On"})
    for i in (CRASH, SPLASH, CHORD, HORN):
        L.setp(f"song.tracks[{i}].devices[-1]", {"Dry/Wet": "100 %", "Predelay": "0.00 ms", "In Hi Cut On": "Off",
                                                "In Lo Cut On": "Off", **REVERBS["room"]})
    paths = {"fx noise": f"song.tracks[{idx['fx noise']}]", "fx tone": f"song.tracks[{idx['fx tone']}]",
             "fx kit": f"song.tracks[{idx['fx kit']}]", "kick": f"song.tracks[{KICK}]",
             "perc1": f"song.tracks[{PERC1}]", "perc2": f"song.tracks[{PERC2}]"}
    for name, path in paths.items():   # clear what an earlier run left past the song
        L.run(f"t = {path}\nfor c in list(t.arrangement_clips):\n    if c.start_time >= {FX0}:\n        t.delete_clip(c)\nresult = 'ok'")
    L.run(f"t = song.tracks[{RUMBLE}]\nfor c in list(t.arrangement_clips):\n    if c.start_time >= {FX0}:\n        t.delete_clip(c)\nresult = 'ok'")
    rumble, rumble_gain = L.run(f"c = song.tracks[{RUMBLE}].arrangement_clips[0]\nresult = [c.file_path, c.gain]")
    pattern = kick_pattern(L)
    for c in candidates():
        if c.kind == "reverse":
            continue
        seam = c.seam_beat
        if c.track == "kick":
            t0 = seam + c.start                       # the 4-bar pass
            lo_, hi_ = c.src.get("clear", (0.0, 0.0))
            bars = [(b * 4.0 + s, p, d, v) for b in range(4) for s, p, d, v in pattern]
            bars = [n for n in bars if not (n[1] in (KICK1, 50) and lo_ <= n[0] + c.start < hi_)]   # the fill's span
            bars += [(t - c.start, p, d, v) for t, p, d, v in c.notes]
            clip_notes(L, paths["kick"], t0, 16.0, bars)
            L.run(f"t = song.tracks[{RUMBLE}]\nc = t.create_audio_clip({rumble!r}, {t0})\nc.gain = {rumble_gain!r}\nresult = 'ok'")   # the song's clip gain
        else:
            t0 = seam + min(n[0] for n in c.notes)
            clip_notes(L, paths[c.track], t0, max(n[0] + n[2] for n in c.notes) - (t0 - seam),
                       [(t - (t0 - seam), p, d, v) for t, p, d, v in c.notes])
        print(f"{c.id:22s} slot {c.slot:2d} at beat {seam:7.1f}", flush=True)
    got = L.run(f"""t = song.tracks[{RUMBLE}]
result = [(c.start_time, c.end_time, c.warping, c.looping) for c in t.arrangement_clips if c.start_time >= {FX0}][:3]""")
    print("rumble clips", got)


# ---- automate: the moving parameters, written into a copy of the .als -------------------------------------------------

TYPES = {"Low-pass": 0, "High-pass": 1, "Band-pass": 2}
WAVES = {"Sine": 0, "Saw D": 10}
# key -> (track, device tag, which of that tag on the track, .als parameter, convert, default)
PARAMS = {
    "type": ("{t}", "AutoFilter2", 0, "Filter_Type", TYPES.get, "Low-pass"),
    "res": ("{t}", "AutoFilter2", 0, "Filter_Resonance", lambda v: v / 100, 20.0),
    "freq": ("{t}", "AutoFilter2", 0, "Filter_Frequency", lambda v: min(19999.0, max(20.0, v)), 16000.0),
    "gain": ("{t}", "StereoGain", -1, "Gain", lambda db: 10 ** (db / 20), 0.0),
    "mute": ("{t}", "StereoGain", -1, "Mute", bool, False),
    "wave": ("{t}", "Operator", 0, "Operator.0/WaveForm", WAVES.get, "Saw D"),
    "pe_peak": ("{t}", "Operator", 0, "PitchEnv/PitchEnv/DecayLevel", float, 0.0),
    "pe_attack": ("{t}", "Operator", 0, "PitchEnv/PitchEnv/AttackTime", lambda ms: max(0.1, ms), 0.1),
    "pe_decay": ("{t}", "Operator", 0, "PitchEnv/PitchEnv/DecayTime", lambda ms: max(1.0, ms), 50.0),
    "pe_sustain": ("{t}", "Operator", 0, "PitchEnv/PitchEnv/SustainLevel", float, 0.0),
    "hp": ("kick group", "Eq8", -1, "Bands.0/ParameterA/Freq", float, 10.0),
    "shelf": ("kick group", "Eq8", -1, "Bands.1/ParameterA/Gain", float, 0.0),
    "kmute": ("kick group", "StereoGain", -1, "Mute", bool, False),
}
TRACK_NAMES = {"kick": "kick", "perc1": "perc 1", "perc2": "perc 2"}


def automate() -> None:
    from hands import als
    tree = als.load(ALS)
    names = [als.track_name(t) for t in als.all_tracks(tree)]

    def dev(track_name: str, tag: str, which: int):
        tr = als.find_track(tree, track_name)
        return tr, [d for d in als.devices(tr) if d.tag == tag][which]

    C = [c for c in candidates() if c.kind != "reverse"]
    # 1. synth tracks and the kick group: every key a track uses is written for every candidate on it, so one
    #    candidate's setting never carries into the next. Each candidate's values are set a beat before its slot.
    for track in ("fx noise", "fx tone", "kick"):
        cs = sorted((c for c in C if c.track == track), key=lambda c: c.slot)
        keys = sorted({k for c in cs for k in c.auto} | ({"type", "res", "freq", "gain"} if track != "kick" else set()))
        for key in keys:
            tname, tag, which, pname, conv, default = PARAMS[key]
            tr, d = dev(tname.format(t=track), tag, which)
            pts, prev = [], None
            for c in cs:
                seam, setup = c.seam_beat, c.seam_beat - SEAM - 1.0
                own = [(seam + t, v) for t, v in c.auto.get(key, [(c.start, default)])]
                if prev is not None:
                    pts.append((setup, prev))
                pts += [(setup, own[0][1])] + own
                prev = own[-1][1]
            als.add_points(tree, tr, d, pname, [(t, conv(v)) for t, v in pts])
        print(f"{track}: {', '.join(keys)} over {len(cs)} slots", flush=True)
    # 2. the song's own automation on the kick and rumble (the kick's EQ and the track switched on and off through
    #    the song) set as it is at the bars the arranger's kick loop was cut from (song beat 16)
    for name, (tr, env, events) in als.envelopes(tree).items():
        if als.track_name(tr) not in ("kick", "rumble", "kick group"):
            continue
        evs = sorted(events, key=lambda e: (float(e.get("Time")), int(e.get("Id"))))
        if float(evs[-1].get("Time")) >= FX0 - 2.0:
            continue
        v = [e.get("Value") for e in evs if float(e.get("Time")) <= 16.0][-1]
        kind = evs[-1].tag
        holder = env.find("Automation/Events")
        ET.SubElement(holder, kind, Id=str(len(holder)), Time=als._num(FX0 - 2.0), Value=v)
        print(f"{name}: held at {v} from beat {FX0 - 2.0}", flush=True)
    # 3. reverse-reverb gates: each source's Utility mutes the track except for one beat at each of its hits
    by_track: dict = {}
    for src, (ti, hit, _) in SOURCES.items():
        by_track.setdefault(ti, []).append(hit)
    for ti, hits in by_track.items():
        tr = als.all_tracks(tree)[ti]
        d = [x for x in als.devices(tr) if x.tag == "StereoGain"][-1]
        steps = [(0.0, True)]
        for h in sorted(hits):
            steps += [(h, False), (h + 1.0, True)]
        als.set_steps(tree, tr, d, "Mute", steps)
        print(f"{als.track_name(tr)}: open at {sorted(hits)}", flush=True)
    print(als.save(tree, RALS, overwrite=True))


# ---- render: one export per solo state ----------------------------------------------------------------------------------

def solo(L, indices: tuple) -> None:
    L.run(f"for i, t in enumerate(song.tracks):\n    t.solo = i in {tuple(indices)!r}\nresult = 'ok'")
    time.sleep(0.3)
    got = tuple(L.run("result = [i for i, t in enumerate(song.tracks) if t.solo]"))
    if got != tuple(indices):
        sys.exit(f"STOP: soloed {got}, wanted {indices}")


def states(L) -> dict:
    """state -> (soloed track indices, start beat, length in beats, reverb setting or None)."""
    C = candidates()
    out = {}
    for key, tracks in (("fx noise", None), ("fx tone", None), ("fx kit", None), ("perc1", (PERC1,)),
                        ("perc2", (PERC2,)), ("kick", (KICK, RUMBLE))):
        n = 1 + max(c.slot for c in C if c.track == key and c.kind != "reverse")
        out[key.replace(" ", "-")] = (tracks or (track_index(L, key),), FX0 - 4.0, n * SLOT + 8.0, None)
    for ti in sorted({ti for ti, _, _ in SOURCES.values()}):
        hits = [h for t, h, _ in SOURCES.values() if t == ti]
        for verb in REVERBS:
            out[f"rv-{ti}-{verb}"] = ((ti,), min(hits), max(hits) - min(hits) + 40.0, verb)
    return out


def render(only: list[str]) -> None:
    L = lo()
    if L.guard("fx render") != RSET:
        sys.exit(f"STOP: {RSET} is not in front")
    for name, (tracks, start, length, verb) in states(L).items():
        if only and name not in only:
            continue
        out = FX / "raw" / f"{name}.wav"
        if out.exists():
            print(f"{name}: already there", flush=True)
            continue
        if verb:
            L.setp(f"song.tracks[{tracks[0]}].devices[-1]", REVERBS[verb])
        solo(L, tracks)
        t0 = time.time()
        L.export(out, float(start), float(length), bits=24, timeout_s=900)
        print(f"{name}: {out.stat().st_size / 1e6:.1f} MB in {time.time() - t0:.0f} s", flush=True)
    solo(L, ())


# ---- cut: the renders into one file per candidate, and fx.json ---------------------------------------------------------

def recipe(c: Cand) -> dict:
    """How Live made a candidate, for the arrangement structure the transitions page writes: enough to build the
    chosen ones into the set. Beats are from the section change; automation values are in the units of `auto`."""
    if c.kind == "reverse":
        ti, hit, _ = SOURCES[c.track]
        return {"in": RSET, "track": ti, "source": c.track, "hitBeat": hit, "gateBeats": 1.0,
                "devices": ["Utility (gate)", "Reverb"], "reverb": {"Dry/Wet": "100 %", **REVERBS[c.src["reverb"]]},
                "reversed": True, "beats": -c.start}
    track = {"kick": "kick + rumble (kick group: EQ Eight, Utility added)", "perc1": "perc 1", "perc2": "perc 2"}.get(c.track, c.track)
    out = {"in": RSET, "track": track, "notes": [list(n) for n in c.notes], "automation": {k: [list(p) for p in v] for k, v in c.auto.items()}}
    if c.track in ("fx noise", "fx tone"):
        out["devices"] = ["Operator", "Auto Filter", "Utility"]
        out["operator"] = STATIC[(c.track, 0)]
    elif c.track == "fx kit":
        out["devices"] = ["909 Core Kit", "Utility"]
    if c.kind in ("scoop", "fill") and c.track == "kick":
        out["pass"] = "kick-rumble-a, 4 bars"
        if "clear" in c.src:
            out["kickRemoved"] = list(c.src["clear"])
    return out

def cut() -> None:
    import numpy as np
    import soundfile as sf
    rate, beat = 44100, 44100 * 60 / 160
    raw = {}

    def take(state: str, b0: float, b1: float, start: float) -> np.ndarray:
        if state not in raw:
            raw[state] = sf.read(FX / "raw" / f"{state}.wav", dtype="float32", always_2d=True)[0]
        x = raw[state]
        return x[round((b0 - start) * beat):round((b1 - start) * beat)]

    L = None
    st = {}
    for name in ["fx-noise", "fx-tone", "fx-kit", "perc1", "perc2", "kick"]:
        st[name] = FX0 - 4.0
    rv_start = {}
    for ti in sorted({ti for ti, _, _ in SOURCES.values()}):
        rv_start[ti] = min(h for t, h, _ in SOURCES.values() if t == ti)
    out_dir = FX / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in candidates():
        if c.kind == "reverse":
            ti, hit, _ = SOURCES[c.track]
            x = take(f"rv-{ti}-{c.src['reverb']}", hit, hit - c.start, rv_start[ti])[::-1].copy()
        else:
            state = c.track.replace(" ", "-")
            tail = 0.0 if c.mode == "replace" else 8.0     # what rings past the end, for a sound laid over the music
            x = take(state, c.seam_beat + c.start, c.seam_beat + c.end + tail, st[state])
            if tail:
                quiet = np.abs(x).max(1) < 10 ** (-70 / 20)
                keep = len(x) - int(np.argmax(~quiet[::-1])) if (~quiet).any() else 0
                x = x[:max(keep, round((c.end - c.start) * beat))]
        peak = float(np.abs(x).max()) if len(x) else 0.0
        f = f"{c.id}.flac"
        sf.write(out_dir / f, x, rate, subtype="PCM_16")
        rows.append({"id": c.id, "kind": c.kind, "title": c.title, "file": f, "start": c.start, "end": c.end,
                     "mode": c.mode, "lane": c.lane, "seams": list(c.seams), "peakDb": round(20 * np.log10(peak + 1e-9), 1),
                     "seconds": round(len(x) / rate, 2), "recipe": recipe(c)})
    # the check: the plain kick pass against the arranger's kick loop, band by band. (Not sample by sample: the set's
    # own passes differ that way too, bar 4-6 against 8-10 of the bounced stem by -1.5 dB of residual.)
    loops = json.loads((DATA / "loops.json").read_text())
    ref = sf.read(DATA / "audio" / [c for c in loops["clips"] if c["id"] == "kick-rumble-a"][0]["file"], dtype="float32", always_2d=True)[0]
    got = sf.read(out_dir / "kick-plain.flac", dtype="float32", always_2d=True)[0]

    def band_db(y, lo_hz, hi_hz):
        p = np.abs(np.fft.rfft(y.mean(1))) ** 2
        f = np.fft.rfftfreq(len(y), 1 / rate)
        return 10 * np.log10(p[(f >= lo_hz) & (f < hi_hz)].sum() / len(y) ** 2 + 1e-12)
    n = min(len(ref), len(got))
    diffs = [band_db(got[:n], a_, b_) - band_db(ref[:n], a_, b_) for a_, b_ in ((20, 60), (60, 120), (120, 500), (500, 2000), (2000, 8000), (8000, 20000))]
    check = ("The kick pass made in the slots against the arranger's kick loop, level by band (20 Hz to 20 kHz in six bands): "
             + ", ".join(f"{d:+.1f}" for d in diffs) + " dB.")
    print(check)
    (FX / "fx.json").write_text(json.dumps({"made": time.time(), "set": RSET, "check": check,
                                            "candidates": [r for r in rows if r["kind"] != "check"]}, indent=1))
    print(f"{len(rows)} candidates written to {out_dir}")


def save() -> None:
    L = lo()
    from hands.live import ui
    if L.guard("fx save") != SET:
        sys.exit(f"STOP: {SET} is not in front")
    if ui.menu_enabled("File", "Save Live Set"):
        ui.menu("File", "Save Live Set")
        time.sleep(2.0)
    print("saved", time.ctime(ALS.stat().st_mtime))


if __name__ == "__main__":
    if sys.argv[1] == "render":
        render(sys.argv[2:])
    else:
        {"build": build, "notes": notes, "save": save, "automate": automate, "cut": cut}[sys.argv[1]]()
