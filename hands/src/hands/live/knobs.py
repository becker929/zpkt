"""Knobs: one name for a parameter in the .als and in the running set, and setting them over the LOM.

A Knob is (track, device, param) as the .als names it (hands.als.resolve):

    device  "Mixer" | ("plugin", <plugin name>) | (<device tag>, <index among that tag>)
    param   the XML path in the device ("Bands.1/ParameterA/Gain"), or a plugin parameter's name

Its id is "track/device/param", the device written "Mixer", "plugin:<name>" or "<tag>#<index>":
"S01 kick group/Compressor2#0/Ratio", "Break group/plugin:Dist COLDFIRE/Color". Values are in the
.als's units (the parameter's Manual), as in hands.probe_kit steps and plan files.

The LOM shows the same parameter under another name and often in other units: EQ Eight's
frequency is 0-1 on a log scale, Utility's gain is dB/35, its width the square root of the .als
fraction. UNITS holds the conversions measured on HW002: the rumble chain's .als values against a
LOM dump of the same devices (ears/soundfunction/results/live_rumble_bypass_v1, 12 Sep) and the
kick-group compressor's (knobmap_hw002_kickgroup_v1). A knob without a measured conversion is
refused rather than written with a guess; add one after reading both values in Live.

set_many writes in one LOM call and read_many reads in another: reading a value in the call that
wrote it crashes Live (ableton-guide rule 1). apply does both and checks the read-back. Automated
parameters are refused: a manual write would override their arrangement automation.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from hands import steps
from hands.live.transport import McpTransport

MAX_PER_DEVICE = 20  # parameters of one device per call (ableton-guide rule 2)


class KnobError(RuntimeError):
    """Live refused a knob write or read back something else; nothing was written on a refusal."""


@dataclass(frozen=True)
class Knob:
    track: str
    device: object  # "Mixer" | ("plugin", name) | (tag, index); a bare tag means the last one
    param: str

    def __post_init__(self) -> None:
        device = self.device
        if isinstance(device, str) and device != "Mixer":
            device = (device, -1)
        if isinstance(device, list):
            device = tuple(device)
        object.__setattr__(self, "device", device)
        if "/" in self.track:
            raise ValueError(f"track name {self.track!r} has a '/', which the knob id uses")

    @property
    def id(self) -> str:
        d = self.device
        dev = "Mixer" if d == "Mixer" else f"plugin:{d[1]}" if d[0] == "plugin" else f"{d[0]}#{d[1]}"
        return f"{self.track}/{dev}/{self.param}"

    @classmethod
    def parse(cls, text: str) -> Knob:
        track, dev, param = text.split("/", 2)
        if dev == "Mixer":
            return cls(track, "Mixer", param)
        if dev.startswith("plugin:"):
            return cls(track, ("plugin", dev.removeprefix("plugin:")), param)
        tag, _, index = dev.partition("#")
        return cls(track, (tag, int(index)), param)

    @property
    def spec(self) -> tuple:
        """(track, device, param), as hands.als takes them."""
        return self.track, self.device, self.param

    def __str__(self) -> str:
        return self.id


# --------------------------------------------------------------------------- units

class Unit:
    """How a parameter's .als value maps onto its LOM value."""

    def to_lom(self, v):
        return float(v)

    def from_lom(self, u):
        return float(u)


class Lin(Unit):
    def __init__(self, lo: float, hi: float):
        self.lo, self.hi = lo, hi

    def to_lom(self, v):
        return (float(v) - self.lo) / (self.hi - self.lo)

    def from_lom(self, u):
        return self.lo + float(u) * (self.hi - self.lo)


class Log(Lin):
    def to_lom(self, v):
        return math.log(float(v) / self.lo) / math.log(self.hi / self.lo)

    def from_lom(self, u):
        return self.lo * (self.hi / self.lo) ** float(u)


class Bool(Unit):
    def to_lom(self, v):
        if not isinstance(v, bool):
            raise TypeError(f"a switch takes True/False, not {v!r}")
        return 1.0 if v else 0.0

    def from_lom(self, u):
        return float(u) >= 0.5


class Db35(Unit):
    """Utility's gain: linear amplitude in the .als, dB/35 (-1..1) in the LOM."""

    def to_lom(self, v):
        return -1.0 if v <= 0 else max(-1.0, min(1.0, 20 * math.log10(v) / 35))

    def from_lom(self, u):
        return 10 ** (float(u) * 35 / 20)


class Sqrt(Unit):
    """Utility's width: a fraction 0-4 in the .als, its square root 0-2 in the LOM."""

    def to_lom(self, v):
        return math.sqrt(float(v))

    def from_lom(self, u):
        return float(u) ** 2


class Ratio(Unit):
    """Compressor ratio: r in the .als, 1 - 1/r in the LOM."""

    def to_lom(self, v):
        return 1 - 1 / float(v)

    def from_lom(self, u):
        return math.inf if float(u) >= 1 else 1 / (1 - float(u))


class Fader(Unit):
    """Mixer volume: linear gain in the .als; in the LOM a fader position whose dB only Live
    knows (str_for_value), so Live finds the position by bisection on the display."""

    def to_lom(self, v):
        return max(-1000.0, 20 * math.log10(v)) if v > 0 else -1000.0  # dB, the target

    def from_lom(self, display):
        text = display.replace(" dB", "")
        return 0.0 if "inf" in text else 10 ** (float(text) / 20)


class Mute(Unit):
    """The track's activator (Mixer Speaker): True is on. The LOM sets track.mute to the opposite."""

    def to_lom(self, v):
        if not isinstance(v, bool):
            raise TypeError(f"a track's activator takes True/False, not {v!r}")
        return v

    def from_lom(self, u):
        return bool(u)


SAME, BOOL, MUTE, FADER = Unit(), Bool(), Mute(), Fader()

# (device tag, .als param) -> (LOM parameter name, unit). Evidence pairs, .als -> LOM:
#   Utility Gain 0.4084238708 -> -0.2222222 (-7.78 dB / 35); StereoWidth 0.8770471 -> 0.9365079;
#   BassMonoFrequency 120 -> 0.3802112 (log 50-500); EQ Eight Freq 30.95 Hz -> 0.1468144 and
#   5000 Hz -> 0.8074892 (log 10-22000), Q 2.2926 -> 0.6031746 (log 0.1-18), Gain -14.256 ->
#   -14.256; Compressor Ratio 3 -> 0.6666667, Attack 0.0791 ms -> 0.1796875 (log 0.01-1000);
#   Reverb MixDirect -> Dry/Wet as is (probe-pack bench, 6 Oct); plugin parameters 0-1 as is.
UNITS: dict[tuple[str, str], tuple[str, Unit]] = {
    ("StereoGain", "Gain"): ("Output", Db35()),
    ("StereoGain", "StereoWidth"): ("Stereo Width", Sqrt()),
    ("StereoGain", "BassMono"): ("Bass Mono", BOOL),
    ("StereoGain", "BassMonoFrequency"): ("Bass Freq", Log(50.0, 500.0)),
    ("StereoGain", "Balance"): ("Balance", SAME),
    ("StereoGain", "ChannelMode"): ("Channel Mode", SAME),
    ("StereoGain", "Mono"): ("Mono", BOOL),
    ("Eq8", "GlobalGain"): ("Output", SAME),
    ("Eq8", "Scale"): ("Scale", SAME),
    ("Compressor2", "Ratio"): ("Ratio", Ratio()),
    ("Compressor2", "Attack"): ("Attack", Log(0.01, 1000.0)),
    ("Compressor2", "Knee"): ("Knee", SAME),
    ("Reverb", "MixDirect"): ("Dry/Wet", SAME),
}
EQ8_FREQ = Log(10.0, 22000.0)
EQ8_BAND = {"Freq": ("Frequency", EQ8_FREQ), "Gain": ("Gain", SAME), "Q": ("Q", Log(0.1, 18.0)),
            "IsOn": ("Filter On", BOOL), "Mode": ("Filter Type", SAME)}
_BAND_PATH = re.compile(r"Bands\.(\d)/Parameter([AB])/(\w+)")
MIXER = {"Volume": ("volume", FADER), "Pan": ("pan", SAME), "Speaker": ("mute", MUTE)}


def lom_target(knob: Knob) -> tuple[str, str | None, Unit]:
    """(where, LOM parameter name, unit): where is "param", "volume", "pan" or "mute"."""
    if knob.device == "Mixer":
        if knob.param in MIXER:
            where, unit = MIXER[knob.param]
            return where, None, unit
    elif knob.device[0] == "plugin":
        return "param", knob.param, SAME
    elif knob.param == "On":
        return "param", "Device On", BOOL
    elif knob.device[0] == "Eq8" and (m := _BAND_PATH.fullmatch(knob.param)) and m[3] in EQ8_BAND:
        name, unit = EQ8_BAND[m[3]]
        return "param", f"{int(m[1]) + 1} {name} {m[2]}", unit
    elif (knob.device[0], knob.param) in UNITS:
        return "param", *UNITS[(knob.device[0], knob.param)]
    raise KeyError(f"{knob}: no measured LOM conversion; add one to knobs.UNITS after reading the "
                   f".als and LOM values of the same parameter in Live")


# --------------------------------------------------------------------------- LOM code

_FIND = '''
def _track(name):
    found = [(t.name, t) for t in list(song.tracks) + list(song.return_tracks)] + [("Main", song.master_track)]
    hits = [t for n, t in found if n == name]
    if len(hits) != 1:
        raise LookupError("%d tracks named %r" % (len(hits), name))
    return hits[0]

def _param(track, s):
    if s["where"] == "mute":
        return None
    if s["where"] in ("volume", "pan"):
        return track.mixer_device.volume if s["where"] == "volume" else track.mixer_device.panning
    kind, key = s["device"]
    if kind == "plugin":
        devs = [d for d in track.devices if d.class_name in ("PluginDevice", "AuPluginDevice") and d.name == key]
        if len(devs) != 1:
            raise LookupError("%d plugins named %r" % (len(devs), key))
        dev = devs[0]
    else:
        dev = [d for d in track.devices if d.class_name == kind][key]
    hits = [p for p in dev.parameters if p.name == s["name"]]
    if len(hits) != 1:
        raise LookupError("%s has %d parameters named %r" % (dev.name, len(hits), s["name"]))
    return hits[0]
'''

_SET = _FIND + '''
def _fader(p, db):
    lo, hi = p.min, p.max
    for _ in range(40):
        mid = (lo + hi) / 2
        shown = p.str_for_value(mid).replace(" dB", "")
        if "inf" in shown or float(shown) < db:
            lo = mid
        else:
            hi = mid
    return hi

todo, problems = [], []
for s in SPEC:
    try:
        t = _track(s["track"])
        p = _param(t, s)
    except Exception as exc:
        problems.append("%s: %s" % (s["id"], exc))
        continue
    if p is not None and p.automation_state != 0:
        problems.append("%s: automated; a manual value would override the arrangement" % s["id"])
    elif p is not None and s["where"] != "volume" and not p.min - 1e-6 <= s["value"] <= p.max + 1e-6:
        problems.append("%s: %r is outside the LOM range [%r, %r]" % (s["id"], s["value"], p.min, p.max))
    else:
        todo.append((s, t, p))
written = {}
if not problems:
    for s, t, p in todo:
        if s["where"] == "mute":
            t.mute = not s["value"]
        else:
            if s["where"] == "volume":
                s["value"] = _fader(p, s["value"])
            p.value = s["value"]
        written[s["id"]] = s["value"]
result = {"problems": problems, "written": written}
'''

_READ = _FIND + '''
result = {}
for s in SPEC:
    t = _track(s["track"])
    p = _param(t, s)
    if p is None:
        result[s["id"]] = [not t.mute, "on" if not t.mute else "off", 0]
    else:
        result[s["id"]] = [p.value, p.str_for_value(p.value), p.automation_state]
'''


def _specs(knobs: Iterable[Knob], values: Mapping[Knob, object] | None = None) -> list[dict]:
    specs = []
    for k in knobs:
        where, name, unit = lom_target(k)
        s = {"id": k.id, "track": k.track, "where": where, "name": name,
             "device": None if k.device == "Mixer" else tuple(k.device)}
        if values is not None:
            s["value"] = unit.to_lom(values[k])
        specs.append(s)
    per_device = Counter((s["track"], s["device"]) for s in specs if s["where"] == "param")
    crowded = [f"{track}/{dev}" for (track, dev), n in per_device.items() if n > MAX_PER_DEVICE]
    if crowded:
        raise ValueError(f"more than {MAX_PER_DEVICE} parameters of one device in one call: {crowded}")
    return specs


@dataclass(frozen=True)
class Reading:
    value: object      # in .als units
    lom: object        # the LOM's own value (bool for a track's activator)
    display: str       # what Live shows, e.g. "-7.8 dB"
    automated: bool


def set_many(client: McpTransport, values: Mapping[Knob, object]) -> dict[Knob, object]:
    """Write knob values (.als units) in one LOM call; return what was written, in LOM units.

    Every knob is found and checked first; if any is missing, automated, out of the LOM range or
    without a known conversion, nothing is written and KnobError (or KeyError) says why.
    """
    specs = _specs(values, values)
    res = client.run(f"SPEC = {specs!r}\n" + _SET)
    if res["problems"]:
        raise KnobError("nothing written: " + "; ".join(res["problems"]))
    steps.report(f"set {len(values)} knob(s)", "minor")
    return {k: res["written"][k.id] for k in values}


def read_many(client: McpTransport, knobs: Iterable[Knob]) -> dict[Knob, Reading]:
    """Read knobs in one LOM call (never the one that wrote them)."""
    knobs = list(knobs)
    raw = client.run(f"SPEC = {_specs(knobs)!r}\n" + _READ)
    out = {}
    for k in knobs:
        lom, display, state = raw[k.id]
        where, _, unit = lom_target(k)
        value = unit.from_lom(display if where == "volume" else lom)
        out[k] = Reading(value, lom, display, bool(state))
    return out


def apply(client: McpTransport, values: Mapping[Knob, object], *, verify: bool = True,
          tol: float = 1e-4) -> dict[Knob, Reading]:
    """set_many, then (with verify) read_many in a separate call and check each LOM value is the
    one written, within tol. Returns the readings ({} without verify)."""
    written = set_many(client, values)
    if not verify:
        return {}
    got = read_many(client, values)
    off = [f"{k}: wrote {written[k]!r}, reads {got[k].lom!r} ({got[k].display})" for k in values
           if not (got[k].lom == written[k] if isinstance(written[k], bool) else abs(got[k].lom - written[k]) <= tol)]
    if off:
        raise KnobError("read back differs: " + "; ".join(off))
    return got
