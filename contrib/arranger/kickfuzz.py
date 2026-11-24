"""HW002's kick, with more mid-high fuzz from its own chain, at the same loudness: options rendered in Live.

Anthony (13 Nov 2026): "the most important part is enhancing the kick, specifically adding distortion without changing
the loudness. Every one of the references has a nasty (laudatory) mid high fuzz and ours doesn't. HW002 has the
machinery." Each option changes devices already in HW002's kick chain (HW002_121_pp_loops, never saved with the change:
every value is put back before the set is left), bounces kick + rumble the way bounce.py does and cuts the 4 bars that
are the arranger's `kick-rumble-a`. In the mix set the kick channel's clips are swapped for that loop and the kick
channel is turned by the loop's loudness change, so the kick is as loud as before, and the whole mix is rendered.

    uv run --project hands python contrib/arranger/kickfuzz.py bounce [option ...]   # loops set: the kick loops
    uv run --project hands python contrib/arranger/kickfuzz.py render [option ...]   # mix set: the mixes
    uv run --project ears  python contrib/arranger/kickfuzz.py measure               # fuzz against the references

Files in DATA/kickfuzz: <option>.flac (the kick loop), mix-<option>.flac (the mix), kickfuzz.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import bounce as bouncer
import hw002
import mixset
import spectral

OUT = hw002.DATA / "kickfuzz"
LOOPS_SET = hw002.LOOPS_SET
KICK_CLIP = "kick-rumble-a"
SRC_BAR = 4  # kick-rumble-a is bars 5-8 of the kick-rumble stem (mine.py: its second pass)

# HW002_121_pp_loops, by index (bounce.py's STATES name the same tracks)
KICK_GROUP = "song.tracks[1]"
KICK = "song.tracks[2]"
RUMBLE = "song.tracks[3]"
RACK = f"{KICK}.devices[0]"
INNER = f"{RACK}.chains[0].devices[0]"  # the nested Drum Rack: the 060 body and the 052 layer
ROAR = f"{KICK_GROUP}.devices[1]"
DECAP = f"{RUMBLE}.devices[2]"

UNHIDE = [  # what hides the fuzz HW002 already makes
    (f"{KICK}.devices[1]", "3 Filter On A", "Off"),            # the kick track's -4.3 dB bell at 3.4 kHz
    (f"{RACK}.chains[1].devices[3]", "8 Filter On A", "Off"),  # the offbeat pad's 48 dB low-pass at 325 Hz
]
ROAR_ON = [(ROAR, "Device On", "On"), (ROAR, "Shaper 1 Amt", "0.0 %")]   # multiband: the low band stays clean

OPTIONS = {
    "base": {"title": "As it is", "set": []},
    "a": {"title": "A: unhide", "set": UNHIDE,
          "what": "Kick track's 3.4 kHz cut off, offbeat pad's 325 Hz low-pass off"},
    "b6": {"title": "B: 052 layer +6", "set": UNHIDE + [("chain052", "volume", 6.0)],
           "what": "A, and the 052 layer (high-passed at 958 Hz into COLDFIRE) +6 dB"},
    "b10": {"title": "B: 052 layer +10", "set": UNHIDE + [("chain052", "volume", 6.0), ("util052", "Output", "1.8 dB")],
            "what": "A, and the 052 layer +10 dB (its chain fader at Live's +6 dB limit, its Utility from -2.2 to +1.8 dB)"},
    "c1": {"title": "C: Roar, some", "set": ROAR_ON + [(ROAR, "Shaper 2 Amt", "35 %"), (ROAR, "Shaper 3 Amt", "25 %")],
           "what": "The kick group's Roar on (multiband, 200 Hz / 2 kHz): mid band Noise Injection 35 %, high band Bit Crusher 25 %"},
    "c2": {"title": "C: Roar, lots", "set": ROAR_ON + [(ROAR, "Shaper 2 Amt", "70 %"), (ROAR, "Shaper 3 Amt", "55 %")],
           "what": "The same Roar: mid 70 %, high 55 %"},
    "d2": {"title": "D: rumble, drive N", "set": [(DECAP, "Drive", 0.6), (DECAP, "Style", 0.5), (DECAP, "HighCut", 0.0)],
           "what": "The rumble's Decapitator: drive 0.27 to 0.6, style A to N, high cut at its other end"},
    "d3": {"title": "D: rumble, punish", "set": [(DECAP, "Drive", 0.5), (DECAP, "Punish", 1.0), (DECAP, "HighCut", 0.0)],
           "what": "The rumble's Decapitator: drive 0.5, Punish on, high cut at its other end"},
    "e": {"title": "B + Roar's high band", "set": UNHIDE + [("chain052", "volume", 6.0)] + ROAR_ON
          + [(ROAR, "Shaper 2 Amt", "0.0 %"), (ROAR, "Shaper 3 Amt", "30 %")],
          "what": "B +6, and the kick group's Roar on with only its high band (Bit Crusher above 2 kHz) at 30 %"},
    "d": {"title": "D: punish the rumble", "set": [(DECAP, "Drive", 0.6), (DECAP, "Style", 1.0), (DECAP, "HighCut", 1.0)],
          "what": "The rumble's Decapitator: drive 0.27 to 0.6, style A to P, its high cut opened"},
}




def roar_fuzz(shape: str, amt: str, hp: str, wet: str, comp: str, more: list | None = None) -> list:
    """Fuzz made from the body (kicktexture.py): the kick group's Roar, its low band (under 200 Hz) through a
    clipper and then a high-pass after it, so only what the clipping adds comes through, blended under the clean kick
    by Dry/Wet; the mid and high bands pass clean; Roar's compressor squeezes the result."""
    return [(ROAR, "Device On", "On"), (ROAR, "Shaper 1 On", "On"), (ROAR, "Shaper 1 Type", shape), (ROAR, "Shaper 1 Amt", amt),
            (ROAR, "Flt 1 On", "On"), (ROAR, "Flt 1 Type", "HP"), (ROAR, "Flt 1 Freq", hp), (ROAR, "Flt 1 Pre On", "Off"),
            (ROAR, "Shaper 2 Amt", "0.0 %"), (ROAR, "Shaper 3 Amt", "0.0 %"), (ROAR, "Comp Amt", comp), (ROAR, "Dry/Wet", wet)] + (more or [])


# texture round 1: which clipper, how hard
for _sh, _tag in (("Digital Clip", "dc"), ("Diode Clipper", "di"), ("Tube Preamp", "tu"), ("Full Wave Rectifier", "fw")):
    for _amt in ("60", "100"):
        OPTIONS[f"t-{_tag}{_amt}"] = {"title": f"Fuzz: {_sh} {_amt} %", "group": "texture",
                                      "set": roar_fuzz(_sh, f"{_amt} %", "600 Hz", "40 %", "50 %"),
                                      "what": f"Roar's low band through {_sh} at {_amt} %, high-passed at 600 Hz after it, 40 % wet, its compressor at 50 %"}

# texture round 2: the low band driven hard enough to clip for as long as the body lasts
for _id, _sh, _drv, _lvl, _wet, _comp in (("t2a", "Diode Clipper", "12 dB", "6.0 dB", "50 %", "60 %"),
                                          ("t2b", "Diode Clipper", "18 dB", "6.0 dB", "50 %", "60 %"),
                                          ("t2c", "Diode Clipper", "24 dB", "6.0 dB", "50 %", "60 %"),
                                          ("t2d", "Diode Clipper", "18 dB", "12 dB", "60 %", "80 %"),
                                          ("t2e", "Diode Clipper", "24 dB", "12 dB", "70 %", "100 %"),
                                          ("t2f", "Full Wave Rectifier", "18 dB", "12 dB", "60 %", "80 %")):
    OPTIONS[f"t-{_id}"] = {"title": f"Fuzz: {_sh}, drive {_drv}", "group": "texture",
                           "set": roar_fuzz(_sh, "100 %", "600 Hz", _wet, _comp, [(ROAR, "Drive", _drv), (ROAR, "Shaper 1 Level", _lvl)]),
                           "what": f"Roar's low band driven {_drv} into {_sh} at 100 %, +{_lvl} out, high-passed at 600 Hz after it, {_wet} wet, compressor {_comp}"}

# texture round 3: denser shapers at the drive that worked, and heavier compression to lengthen the hold
for _id, _sh, _lvl, _wet, _comp in (("t3tf", "Tri Fold", "6.0 dB", "50 %", "60 %"), ("t3fr", "Fractal", "6.0 dB", "50 %", "60 %"),
                                    ("t3sh", "Shards", "6.0 dB", "50 %", "60 %"), ("t3po", "Polynomial", "6.0 dB", "50 %", "60 %"),
                                    ("t3ni", "Noise Injection", "6.0 dB", "50 %", "60 %"),
                                    ("t3dc", "Diode Clipper", "0.0 dB", "50 %", "100 %"), ("t3tc", "Tri Fold", "0.0 dB", "50 %", "100 %")):
    OPTIONS[f"t-{_id}"] = {"title": f"Fuzz: {_sh}, comp {_comp}", "group": "texture",
                           "set": roar_fuzz(_sh, "100 %", "600 Hz", _wet, _comp, [(ROAR, "Drive", "24 dB"), (ROAR, "Shaper 1 Level", _lvl)]),
                           "what": f"Roar's low band driven 24 dB into {_sh} at 100 %, {_lvl} out, high-passed at 600 Hz after it, {_wet} wet, compressor {_comp}"}



def kick_roar(shape: str, drive: str, wet: str, comp: str, hp: str = "600 Hz", lvl: str = "0.0 dB") -> list:
    """Fuzz on the kick alone (the rumble stays clean): a Roar after the kick's drum rack, its shaper driven, a
    high-pass after the shaper so only what the clipping adds comes through, blended under the clean kick."""
    return [("load", KICK, "Roar"), ("kickroar", "Shaper 1 On", "On"), ("kickroar", "Shaper 1 Type", shape),
            ("kickroar", "Shaper 1 Amt", "100 %"), ("kickroar", "Drive", drive), ("kickroar", "Shaper 1 Level", lvl),
            ("kickroar", "Flt 1 On", "On"), ("kickroar", "Flt 1 Type", "HP"), ("kickroar", "Flt 1 Freq", hp),
            ("kickroar", "Flt 1 Pre On", "Off"), ("kickroar", "Comp Amt", comp), ("kickroar", "Dry/Wet", wet)]


# texture round 4: the fuzz on the kick only
for _sh, _tag in (("Diode Clipper", "di"), ("Tri Fold", "tf"), ("Polynomial", "po")):
    for _drv in ("18", "24"):
        OPTIONS[f"t-k{_tag}{_drv}"] = {"title": f"Kick fuzz: {_sh}, drive {_drv} dB", "group": "texture",
                                       "set": kick_roar(_sh, f"{_drv} dB", "50 %", "60 %"),
                                       "what": f"A Roar on the kick track (not the rumble): {_sh} driven {_drv} dB, high-passed at 600 Hz after it, 50 % wet, compressor 60 %"}

# texture round 5: only the loud part of the hit clips (less drive, no compression to lift the tail)
for _sh, _tag in (("Diode Clipper", "di"), ("Tri Fold", "tf")):
    for _drv in ("9", "12", "15"):
        OPTIONS[f"t-q{_tag}{_drv}"] = {"title": f"Kick fuzz: {_sh}, drive {_drv} dB", "group": "texture",
                                       "set": kick_roar(_sh, f"{_drv} dB", "40 %", "0.0 %"),
                                       "what": f"A Roar on the kick track (not the rumble): {_sh} driven {_drv} dB, high-passed at 600 Hz after it, 40 % wet, no compression"}



def mid_fuzz(shape: str, drive: str, lvl: str) -> list:
    """The kick group's multiband Roar with only its mid band (200 Hz-2 kHz: the kick's punch, which decays faster
    than its sub, and where the rumble has little) through a clipper; the low and high bands pass clean; HW002's
    1.44 kHz low-pass on the mid band off so the fuzz reaches up."""
    return [(ROAR, "Device On", "On"), (ROAR, "Shaper 1 Amt", "0.0 %"), (ROAR, "Shaper 3 Amt", "0.0 %"),
            (ROAR, "Shaper 2 On", "On"), (ROAR, "Shaper 2 Type", shape), (ROAR, "Shaper 2 Amt", "100 %"),
            (ROAR, "Shaper 2 Level", lvl), (ROAR, "Flt 2 On", "Off"), (ROAR, "Drive", drive),
            (ROAR, "Comp Amt", "0.0 %"), (ROAR, "Dry/Wet", "100 %")]


# texture round 6: the fuzz from the kick's punch
for _sh, _tag in (("Diode Clipper", "di"), ("Tri Fold", "tf")):
    for _drv in ("6", "12"):
        OPTIONS[f"t-m{_tag}{_drv}"] = {"title": f"Punch fuzz: {_sh}, drive {_drv} dB", "group": "texture",
                                       "set": mid_fuzz(_sh, f"{_drv} dB", "0.0 dB"),
                                       "what": f"The kick group's multiband Roar: only the mid band (200 Hz-2 kHz, the punch) through {_sh}, drive {_drv} dB, its 1.44 kHz low-pass off; low and high bands clean"}

# texture round 7: COLDFIRE on the 052 layer fed its short body, not only its click (its high-pass before COLDFIRE lowered)
for _hp in ("150", "300", "500"):
    OPTIONS[f"t-h{_hp}"] = {"title": f"052 body into COLDFIRE, {_hp} Hz", "group": "texture",
                            "set": UNHIDE + [("chain052", "volume", 6.0), ("eq052", "4 Frequency A", f"{_hp} Hz")],
                            "what": f"Unhidden, the 052 layer +6 dB, and its high-pass before COLDFIRE lowered from 958 to {_hp} Hz, so COLDFIRE clips 052's short body, not only its click"}

# texture round 8: the 052 body driven harder into COLDFIRE (the EQ's output up before it, the Utility after it down)
for _hp in ("150", "250"):
    for _up in (6, 12):
        OPTIONS[f"t-d{_hp}-{_up}"] = {"title": f"052 body driven +{_up} dB, {_hp} Hz", "group": "texture",
                                      "set": UNHIDE + [("chain052", "volume", 6.0), ("eq052", "4 Frequency A", f"{_hp} Hz"),
                                                       ("eq052", "Output", f"{_up}.0 dB"), ("util052", "Output", f"{-2.2 - _up:.1f} dB")],
                                      "what": f"Unhidden, the 052 layer +6 dB, its high-pass before COLDFIRE at {_hp} Hz, and {_up} dB more into COLDFIRE (the EQ's output up, the Utility after it down as much)"}

# texture round 9: the 052 body at 250 Hz driven +6 dB, 3 dB louder; grain from a Roar on the kick track
_BODY = UNHIDE + [("chain052", "volume", 6.0), ("eq052", "4 Frequency A", "250 Hz"), ("eq052", "Output", "6.0 dB"),
                  ("util052", "Output", "-5.2 dB")]
for _id, _extra, _w in (("n1", [], "nothing more"),
                        ("n2", kick_roar("Noise Injection", "6.0 dB", "20 %", "0.0 %", hp="1000 Hz"), "Roar's Noise Injection on the kick track, 20 % wet, high-passed at 1 kHz"),
                        ("n3", kick_roar("Noise Injection", "6.0 dB", "35 %", "0.0 %", hp="1000 Hz"), "Roar's Noise Injection on the kick track, 35 % wet, high-passed at 1 kHz"),
                        ("n4", kick_roar("Bit Crusher", "6.0 dB", "25 %", "0.0 %", hp="1000 Hz"), "Roar's Bit Crusher on the kick track, 25 % wet, high-passed at 1 kHz")):
    OPTIONS[f"t-{_id}"] = {"title": "052 body fuzz" + ("" if _id == "n1" else " + " + _w.split(" on ")[0].replace("Roar's ", "")), "group": "texture",
                           "set": _BODY + _extra,
                           "what": "Unhidden; the 052 layer +6 dB with its high-pass before COLDFIRE at 250 Hz, so COLDFIRE clips its short body, driven 6 dB harder; and " + _w}

# texture round 10: round 3's Tri Fold at KSMS's level, and with the punch band folded too
_TF = roar_fuzz("Tri Fold", "100 %", "600 Hz", "50 %", "60 %", [(ROAR, "Drive", "24 dB"), (ROAR, "Shaper 1 Level", "6.0 dB")])
OPTIONS["t-f1"] = {"title": "Body fuzz, Tri Fold, 35 % wet", "group": "texture",
                   "set": roar_fuzz("Tri Fold", "100 %", "600 Hz", "35 %", "60 %", [(ROAR, "Drive", "24 dB"), (ROAR, "Shaper 1 Level", "6.0 dB")]),
                   "what": "The kick group's Roar: its low band driven 24 dB into Tri Fold, high-passed at 600 Hz after it, 35 % wet, compressor 60 %"}
OPTIONS["t-f2"] = {"title": "Body fuzz, Tri Fold, 3 dB down", "group": "texture",
                   "set": roar_fuzz("Tri Fold", "100 %", "600 Hz", "50 %", "60 %", [(ROAR, "Drive", "24 dB"), (ROAR, "Shaper 1 Level", "3.0 dB")]),
                   "what": "The kick group's Roar: its low band driven 24 dB into Tri Fold (+3 dB out), high-passed at 600 Hz after it, 50 % wet, compressor 60 %"}
OPTIONS["t-f3"] = {"title": "Body + punch fuzz, Tri Fold", "group": "texture",
                   "set": roar_fuzz("Tri Fold", "100 %", "600 Hz", "40 %", "60 %", [(ROAR, "Drive", "24 dB"), (ROAR, "Shaper 1 Level", "3.0 dB"),
                                                                                  (ROAR, "Shaper 2 Type", "Tri Fold"), (ROAR, "Shaper 2 Amt", "50 %"), (ROAR, "Flt 2 On", "Off")]),
                   "what": "The kick group's Roar: its low band driven 24 dB into Tri Fold, high-passed at 600 Hz after it, and the mid band (the punch) folded at 50 %, 40 % wet, compressor 60 %"}


# the deep sub HW002 cut: its kick group EQ's low shelf (-14.8 dB at 30 Hz) and the rumble's (-14.3 dB at 31 Hz) eased
OPTIONS["t-f1s"] = {"title": "Body fuzz, sub back", "group": "texture",
                    "set": OPTIONS["t-f1"]["set"] + [(f"{KICK_GROUP}.devices[0]", "1 Gain A", "-6.0 dB"), (f"{RUMBLE}.devices[3]", "1 Gain A", "-6.0 dB")],
                    "what": OPTIONS["t-f1"]["what"] + "; and HW002's deep-sub cuts eased: the kick group's and the rumble's low shelves at 30 Hz from -15 to -6 dB"}
TEXTURE_KEEP_EXTRA = ("t-f1s",)

# the texture rounds' finalists, shown on the pages (the rest stay as files and in kickdesign/texture.json)
TEXTURE_KEEP = ("t-f1", "t-t3tf", "t-mtf12", "t-t3tc", "t-f1s")


# ---- in the loops set -----------------------------------------------------------------------------------------------

def chain052(L: Any) -> str:
    names = L.run(f"result = [c.name for c in {INNER}.chains]")
    k = [i for i, n in enumerate(names) if "052" in n]
    if len(k) != 1:
        sys.exit(f"STOP: no single 052 chain in {names}")
    return f"{INNER}.chains[{k[0]}]"


def param(L: Any, dev: str, name: str) -> str:
    """The LOM path of one parameter, checked to exist once."""
    n = L.run(f"result = [i for i, p in enumerate({dev}.parameters) if p.name == {name!r}]")
    if len(n) != 1:
        sys.exit(f"STOP: {dev} has {len(n)} parameters named {name!r}")
    return f"{dev}.parameters[{n[0]}]"


def apply(L: Any, changes: list) -> list[tuple[str, float]]:
    """Set the option's values; return every touched parameter's raw value before, to put back."""
    undo = []
    for dev, name, want in changes:
        if dev == "load":                     # ("load", track, device name): added at the end of the track's chain
            n = len(L.devices(name))
            L.load_item(name, "audio_effects", None, want)
            if len(L.devices(name)) != n + 1:
                sys.exit(f"STOP: {want} did not load on {name}")
            undo.append(("delete", name, n))
            continue
        if dev == "kickroar":   # a device loaded for this bounce: deleted afterwards, so its values need no undo
            L.setp(f"{KICK}.devices[{len(L.devices(KICK)) - 1}]", {name: want})
            continue
        if dev == "eq052":
            dev = f"{chain052(L)}.devices[1]"
        if dev == "util052":
            dev = f"{chain052(L)}.devices[4]"
        if dev == "chain052":
            p = f"{chain052(L)}.mixer_device.volume"
            undo.append((p, L.run(f"result = {p}.value")))
            L.mixer(chain052(L), want)
            continue
        p = param(L, dev, name)
        undo.append((p, L.run(f"result = {p}.value")))
        if isinstance(want, float):
            L.run(f"p = {p}\np.value = max(p.min, min(p.max, {want}))\nresult = 'ok'")
        else:
            L.setp(dev, {name: want})
    return undo


def restore(L: Any, undo: list) -> None:
    for u in reversed(undo):
        if u[0] == "delete":
            L.run(f"{u[1]}.delete_device({u[2]})\nresult = 'ok'")
        else:
            L.run(f"{u[0]}.value = {u[1]!r}\nresult = 'ok'")
    for u in undo:
        if u[0] == "delete":
            if len(L.devices(u[1])) != u[2]:
                sys.exit(f"STOP: {u[1]} still has {L.devices(u[1])}")
            continue
        p, v = u
        got = L.run(f"result = {p}.value")
        if abs(got - v) > 1e-6:
            sys.exit(f"STOP: {p} is {got}, could not put back {v}")


def bounce(names: list[str]) -> None:
    """Bounce kick + rumble with each option set, put back after each, and cut the loop (the loops set in front)."""
    L = mixset.lo()
    hw002.stop_unless_front(L, "kickfuzz bounce", LOOPS_SET)
    OUT.mkdir(parents=True, exist_ok=True)
    bouncer.solo(L, (2, 3))
    try:
        for name in names or [n for n in OPTIONS if not n.startswith("t-")]:
            undo = apply(L, OPTIONS[name]["set"])
            try:
                wav = OUT / f"{name}-stem.wav"
                if wav.exists():
                    wav.unlink()
                L.export(wav, 0.0, (SRC_BAR + 4) * hw002.BEATS_PER_BAR, bits=24, timeout_s=300)
            finally:
                restore(L, undo)
            cut(wav, OUT / f"{name}.flac")
            print(name, "bounced", flush=True)
    finally:
        bouncer.solo(L, ())


def cut(wav: Path, flac: Path) -> None:
    """Bars 5-8 of the stem, as mine.py cut kick-rumble-a: a cut on the bar, 16-bit, no gain (in ears' environment)."""
    a, b = SRC_BAR * hw002.BAR_SAMPLES, (SRC_BAR + 4) * hw002.BAR_SAMPLES
    code = (
        f"import soundfile as sf, sys\nx, r = sf.read(sys.argv[1], always_2d=True)\nassert r == {hw002.RATE}, r\n"
        f"sf.write(sys.argv[2], x[{a}:{b}], r, subtype='PCM_16')"
    )
    subprocess.run(["uv", "run", "--project", str(mixset.ROOT / "ears"), "python", "-c", code, str(wav), str(flac)], check=True)
    wav.unlink()


# ---- in the mix set -------------------------------------------------------------------------------------------------

def swap_kick(L: Any, idx: dict[str, int], path: str) -> None:
    """The kick channel's passes of kick-rumble-a, pointed at another file (same places, same length), checked."""
    mixset.swap_clips(L, f"song.tracks[{idx['kick']}]", path, check=True)


def lufs_of(path: Path) -> float:
    return mixset.lufs(path)


def render(names: list[str]) -> None:
    L = mixset.lo()
    mixset.guard(L)
    loops, _, arr = mixset.load()
    arr.pop("kickFuzz", None)   # a kick option already kept is not where these renders start
    chans = mixset.channels(loops, arr)
    clip = next(c for c in loops["clips"] if c["id"] == KICK_CLIP)
    orig = str(hw002.DATA / "audio" / clip["file"])
    base = lufs_of(OUT / "base.flac")
    info = json.loads((OUT / "kickfuzz.json").read_text()) if (OUT / "kickfuzz.json").exists() else {}
    idx = mixset.tracks(L)
    try:
        for name in names or [n for n in OPTIONS if n != "base" and not n.startswith("t-")]:
            loop = OUT / f"{name}.flac"
            d = lufs_of(loop) - base
            swap_kick(L, idx, str(loop))
            # the kick turned by its loop's loudness change, so the kick is as loud as before
            spectral.state(L, arr, chans, [{"target": "kick", "device": "gain", "values": {"dB": -d}}])
            mixset.render(L, OUT / f"mix-{name}.flac", spectral.BARS)
            info[name] = {"loopLufsChange": round(d, 2), "kickTurnedDb": round(-d, 2)}
            (OUT / "kickfuzz.json").write_text(json.dumps(info, indent=1))
            print(name, f"loop {d:+.2f} LU, kick turned {-d:+.2f} dB", flush=True)
    finally:
        swap_kick(L, idx, orig)
        spectral.state(L, arr, chans, [])


eq_values = mixset.bell_eq_values


def solo_lufs(L: Any, idx: dict[str, int], out: Path) -> float:
    """The kick channel and its bus soloed, bars 17-20: the kick's loudness in the mix set, as Live plays it."""
    keep = {idx["kick"], idx[mixset.BUSES["kick"]]}
    L.run(f"for i, t in enumerate(song.tracks):\n    t.solo = i in {keep!r}\nresult = 'ok'")
    try:
        mixset.render(L, out, (17, 20))
    finally:
        L.run("for t in song.tracks:\n    t.solo = False\nresult = 'ok'")
    return mixset.lufs(out)


def match(names: list[str]) -> None:
    """The kick spectrally matched to the references' isolated kicks (kickiso.py match): an EQ Eight on the kick
    channel, fitted from the kick as it is (m0, EQ alone) or from option B +6 (mb6). Loudness matched in Live: the
    kick soloed with and without the change, and the kick channel turned by the difference."""
    L = mixset.lo()
    mixset.guard(L)
    loops, _, arr = mixset.load()
    arr.pop("kickFuzz", None)
    chans = mixset.channels(loops, arr)
    clip = next(c for c in loops["clips"] if c["id"] == KICK_CLIP)
    orig = str(hw002.DATA / "audio" / clip["file"])
    plan = json.loads((hw002.DATA / "kickiso" / "match.json").read_text())
    info = json.loads((OUT / "kickfuzz.json").read_text()) if (OUT / "kickfuzz.json").exists() else {}
    idx = mixset.tracks(L)
    try:
        swap_kick(L, idx, orig)
        spectral.state(L, arr, chans, [])
        ref = solo_lufs(L, idx, OUT / "solo-base.flac")
        for name in names or list(plan):
            p = plan[name]
            swap_kick(L, idx, str(OUT / f"{p['from']}.flac"))
            eq = {"target": "kick", "device": "EQ Eight", "values": eq_values(p["bells"])}
            spectral.state(L, arr, chans, [eq])
            d = solo_lufs(L, idx, OUT / f"solo-{name}.flac") - ref
            spectral.state(L, arr, chans, [eq, {"target": "kick", "device": "gain", "values": {"dB": -d}}])
            mixset.render(L, OUT / f"mix-{name}.flac", spectral.BARS)
            info[name] = {"kickTurnedDb": round(-d, 2), "from": p["from"], "bells": p["bells"]}
            (OUT / "kickfuzz.json").write_text(json.dumps(info, indent=1))
            print(name, f"kick {d:+.2f} LU with the EQ, turned {-d:+.2f} dB", flush=True)
    finally:
        swap_kick(L, idx, orig)
        spectral.state(L, arr, chans, [])


# ---- measuring (ears) -----------------------------------------------------------------------------------------------

GROUPS = [("sub", 25, 63), ("body", 63, 160), ("box", 160, 400), ("mid", 400, 1000), ("bite", 1000, 2500),
          ("edge", 2500, 6000), ("fizz", 6000, 20000)]


def measure(_names: list[str]) -> None:
    """Each kick loop's shape (third-octave energy per group, dB of its total) against the references' kick-alone
    bars (kickshape.py); and each mix's drop for the page."""
    import kickshape
    import numpy as np

    def shape(x, sr):
        lin = 10 ** (kickshape.third_octaves(x, sr) / 10)
        return {g: round(float(10 * np.log10(sum(e for c, e in zip(kickshape.THIRDS, lin) if lo <= c < hi) + 1e-12)), 1)
                for g, lo, hi in GROUPS}
    refs = []
    for ref in sorted(kickshape.REFS.glob("*.wav")):
        r, rsr = kickshape.mono(ref)
        seg, t = kickshape.kick_alone(r, rsr)
        refs.append({"title": ref.stem, "at": round(t, 1), "shape": shape(seg, rsr)})
    import kickiso
    iso = json.loads((hw002.DATA / "kickiso" / "kickiso.json").read_text())
    mean, th = np.array(iso["refMean"]), np.array(kickiso.THIRDS)
    clean = (th >= 40) & (th <= 4100)
    info = json.loads((OUT / "kickfuzz.json").read_text())
    plan = json.loads((hw002.DATA / "kickiso" / "match.json").read_text()) if (hw002.DATA / "kickiso" / "match.json").exists() else {}
    titles = {"m0": ("M: matched by EQ alone", "No distortion: an EQ Eight on the kick channel fitted to the references' isolated kicks"),
              "mb6": ("M: B +6, then matched", "Option B +6, then an EQ Eight on the kick channel fitted to what is left of the gap")}
    for k, v in plan.items():   # the EQ as it was rendered, if it was
        if k in info and info[k].get("bells"):
            v["bells"] = info[k]["bells"]
    titles.update({"mf1": ("Body fuzz, matched to KSMS", "The Tri Fold body fuzz (35 % wet), then an EQ Eight on the kick channel fitted to KSMS's isolated kick"),
                   "mmtf12": ("Punch fuzz, matched to KSMS", "The punch-band Tri Fold fuzz, then an EQ Eight on the kick channel fitted to KSMS's isolated kick"),
                   "mf1s": ("Body fuzz, sub back, matched to KSMS", "Body fuzz with HW002's deep-sub cuts eased, then an EQ Eight fitted to KSMS's isolated kick (it did not bring the sub back)")})
    every = {**{k: v for k, v in OPTIONS.items() if not k.startswith("t-") or k in TEXTURE_KEEP},
             **{k: {"title": titles[k][0], "what": titles[k][1] + ": " + ", ".join(
                 f"{f:g} Hz {g:+.1f} dB" for f, g, _ in v["bells"])} for k, v in plan.items() if (OUT / f"solo-{k}.flac").exists()}}
    def grouped(t):   # third-octave dB (of total) into the chart's groups
        lin = 10 ** (np.array(t) / 10)
        return {g: round(float(10 * np.log10(sum(e for c, e in zip(th, lin) if lo <= c < hi) + 1e-12)), 1) for g, lo, hi in GROUPS}
    refs = [{"title": iso["titles"][k], "shape": grouped(v)} for k, v in iso["refs"].items()]   # isolated by the beat
    opts = []
    for name, o in every.items():
        loop = OUT / (f"solo-{name}.flac" if name in plan else f"{name}.flac")
        if not loop.exists():
            continue
        x, sr = kickshape.mono(loop)
        row = {"id": name, "title": o["title"], "what": o.get("what", "HW002's kick chain as it is"),
               "loop": loop.name, "recipeLoop": f"{plan[name]['from']}.flac" if name in plan else loop.name,
               "bells": plan[name]["bells"] if name in plan else None, "shape": shape(x, sr), "loopLufs": round(lufs_of(loop), 2), **info.get(name, {})}
        if name.startswith("t-") and "kickTurnedDb" not in row:   # a texture loop: turned as the options were, by its loudness change
            row["kickTurnedDb"] = round(-(row["loopLufs"] - lufs_of(OUT / "base.flac")), 2)
        src = plan[name]["from"] if name in plan else name
        if src in OPTIONS:   # the recipe, for Live: what changed in HW002's kick chain (a matched kick: the kick it started from)
            row["changes"] = [[str(c) for c in ch] for ch in OPTIONS[src]["set"]]
        if name.startswith("d"):
            row["note"] = "No mix rendered: driving the rumble adds low end, so the kick came out darker, not fuzzier."
        mix = OUT / f"mix-{name}.flac"
        if name == "base":
            mix = spectral.OUT / "before.flac"
        if mix.exists():
            m = spectral.measure_file(mix, hw002.DROP_SECONDS, hw002.BAR_SECONDS)
            row.update(mix=("../spectral/before.flac" if name == "base" else f"mix-{name}.flac"), drop=m["drop"])
            # the check that counts: the kick isolated from this mix (kickiso.py's method) against the references'
            k, _ = kickiso.shape_of(mix, hw002.DROP_SECONDS, hw002.TEMPO_BPM)
            row["isoDistance"] = round(float(np.sqrt(np.mean((k - mean)[clean] ** 2))), 2)
            row["isoGap2to4k"] = round(float(np.mean((k - mean)[(th >= 2000) & (th <= 4100)])), 1)
            row["shapeLoop"], row["shape"] = row["shape"], grouped(k)
        opts.append(row)
    (OUT / "renders.json").write_text(json.dumps({"groups": [g for g, _, _ in GROUPS], "refs": refs, "options": opts}))
    for o in opts:
        print(f"{o['id']:5s}", " ".join(f"{g} {o['shape'][g]:6.1f}" for g, _, _ in GROUPS), "turned", o.get("kickTurnedDb", ""),
              "iso", o.get("isoDistance", ""), o.get("isoGap2to4k", ""))
    print(OUT / "renders.json")


COMMANDS = {"bounce": bounce, "render": render, "match": match, "measure": measure}


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in COMMANDS:
        sys.exit(f"usage: kickfuzz.py {{{'|'.join(COMMANDS)}}} [option ...]")
    COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
