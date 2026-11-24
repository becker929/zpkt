"""Knobs: one name for a parameter in the .als and in the running set, and setting them over the LOM.

A Knob is (track, device, param) as the .als names it (hands.als.resolve):

    device  "Mixer" | ("plugin", <plugin name>) | (<device tag>, <index among that tag>)
    param   the XML path in the device ("Bands.1/ParameterA/Gain"), or a plugin parameter's name

Its id is "track/device/param", the device written "Mixer", "plugin:<name>" or "<tag>#<index>":
"S01 kick group/Compressor2#0/Ratio", "Break group/plugin:Dist COLDFIRE/Color". The plan files and the studio
lab spelled the same id with pipes, "track|Tag:index|param" (`pipe_id`); `Knob.parse` reads both. Values are in the
.als's units (the parameter's Manual), as in hands.probe_kit steps.

The LOM shows the same parameter under another name and often in other units: EQ Eight's
frequency is 0-1 on a log scale, Utility's gain is dB/35, its width the square root of the .als
fraction. hands.live.units holds the conversions (UNITS) measured on HW002: the rumble chain's .als values against a
LOM dump of the same devices (prototypes/soundfunction/results/live_rumble_bypass_v1, 12 Sep; the prototype is
in git tag pre-upgrade-2026-11-24) and the kick-group compressor's (knobmap_hw002_kickgroup_v1). A knob without a measured conversion is
refused rather than written with a guess; add one after reading both values in Live.

set_many writes in one LOM call and read_many reads in another: reading a value in the call that
wrote it crashes Live (ableton-guide rule 1). apply does both and checks the read-back. Automated
parameters are refused: a manual write would override their arrangement automation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from hands.live.transport import McpTransport
from hands.live.units import (  # noqa: F401  (Unit, Lin, Log and the tables are part of knobs' API)
    _BAND_PATH,
    BOOL,
    EQ8_BAND,
    EQ8_FREQ,
    FADER,
    MIXER,
    MUTE,
    SAME,
    UNITS,
    Bool,
    Db35,
    Fader,
    Lin,
    Log,
    Mute,
    Ratio,
    Sqrt,
    Unit,
)

MAX_PER_DEVICE = 20  # parameters of one device per call (ableton-guide rule 2)


class KnobError(RuntimeError):
    """Live refused a knob write or read back something else; nothing was written on a refusal."""


@dataclass(frozen=True)
class Knob:
    track: str
    device: Any  # "Mixer" | ("plugin", name) | (tag, index); a bare tag means the last one
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
        """The id hands writes: "track/Tag#index/param", "track/plugin:Name/param", "track/Mixer/param"."""
        return f"{self.track}/{self._device_text('#')}/{self.param}"

    @property
    def pipe_id(self) -> str:
        """The same id in the plan files' and the studio lab's spelling: "track|Tag:index|param"."""
        return f"{self.track}|{self._device_text(':')}|{self.param}"

    def _device_text(self, index_mark: str) -> str:
        d = self.device
        return "Mixer" if d == "Mixer" else f"plugin:{d[1]}" if d[0] == "plugin" else f"{d[0]}{index_mark}{d[1]}"

    @classmethod
    def parse(cls, text: str) -> Knob:
        """A knob from either spelling of its id (`id`, `pipe_id`). ValueError says what an id looks like."""
        pipes = [part.strip() for part in text.split("|")]
        if len(pipes) == 3 and all(pipes) and "/" not in pipes[0]:  # a slash id's param may hold a "|"
            track, dev, param = pipes
            return cls._from_parts(text, track, dev, param, index_mark=":")
        slashes = text.split("/", 2)
        if len(slashes) == 3 and all(slashes):
            track, dev, param = slashes
            return cls._from_parts(text, track, dev, param, index_mark="#")
        raise ValueError(f"a knob id is track/Tag#index/param (or track|Tag:index|param), not {text!r}")

    @classmethod
    def _from_parts(cls, text: str, track: str, dev: str, param: str, index_mark: str) -> Knob:
        if dev == "Mixer":
            return cls(track, "Mixer", param)
        if dev.startswith("plugin:"):
            return cls(track, ("plugin", dev.removeprefix("plugin:")), param)
        tag, _, index = dev.rpartition(index_mark)
        if not tag or not index.lstrip("-").isdigit():
            raise ValueError(f"{text!r}: the device is Mixer, plugin:<name> or <Tag>{index_mark}<index>, not {dev!r}")
        return cls(track, (tag, int(index)), param)

    @property
    def spec(self) -> tuple:
        """(track, device, param), as hands.als takes them."""
        return self.track, self.device, self.param

    def __str__(self) -> str:
        return self.id


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
    raise KeyError(
        f"{knob}: no measured LOM conversion; add one to knobs.UNITS after reading the "
        f".als and LOM values of the same parameter in Live"
    )


# --------------------------------------------------------------------------- LOM code

_FIND = """
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
        devs = [d for d in track.devices if d.class_name == kind]
        if not -len(devs) <= key < len(devs):
            raise LookupError("no %s #%d: the track has %d" % (kind, key, len(devs)))
        dev = devs[key]
    hits = [p for p in dev.parameters if p.name == s["name"]]
    if len(hits) != 1:
        raise LookupError("%s has %d parameters named %r" % (dev.name, len(hits), s["name"]))
    return hits[0]
"""

_SET = (
    _FIND
    + '''
def _gate(t, s):
    """The DeviceParameter whose automation a write would override (a mute's is the track activator)."""
    if s["where"] == "mute":
        return getattr(t.mixer_device, "track_activator", None)
    return _param(t, s)

def _db(p, v):
    shown = p.str_for_value(v).replace(" dB", "")
    return None if "inf" in shown else float(shown)

def _fader(p, db):
    if db is None:  # silence: the bottom of the fader, which shows -inf
        return p.min
    top = _db(p, p.max)
    if db > top + 0.05:
        raise ValueError("%.2f dB is above the fader's top, %.2f dB" % (db, top))
    lo, hi = p.min, p.max
    for _ in range(40):
        mid = (lo + hi) / 2
        shown = _db(p, mid)
        if shown is None or shown < db:
            lo = mid
        else:
            hi = mid
    if _db(p, hi) - db > 0.5:
        raise ValueError("%.2f dB is below the fader's quietest step, %.2f dB (0 is silence)" % (db, _db(p, hi)))
    return hi

todo, problems = [], []
for s in SPEC:
    try:
        t = _track(s["track"])
        p = _param(t, s)
        gate = _gate(t, s)
    except Exception as exc:
        problems.append("%s: %s" % (s["id"], exc))
        continue
    value = s["value"]
    if gate is not None and gate.automation_state != 0:
        problems.append("%s: automated; a manual value would override the arrangement" % s["id"])
        continue
    if s["where"] == "volume":
        try:
            value = _fader(p, value)
        except ValueError as exc:
            problems.append("%s: %s" % (s["id"], exc))
            continue
    elif p is not None and not p.min - 1e-6 <= value <= p.max + 1e-6:
        problems.append("%s: %r is outside the LOM range [%r, %r]" % (s["id"], value, p.min, p.max))
        continue
    todo.append((s, t, p, value))
written, done, failed = {}, [], False
if not problems:
    try:
        for s, t, p, value in todo:
            if p is None:
                old = t.mute
                t.mute = not value
            else:
                old = p.value
                p.value = value
            done.append((s, t, p, old))
            written[s["id"]] = value
    except Exception as exc:
        failed = True
        problems.append("%s: write failed: %s" % (s["id"], exc))
        for s, t, p, old in reversed(done):
            try:
                if p is None:
                    t.mute = old
                else:
                    p.value = old
            except Exception as exc:
                problems.append("%s: could not restore %r: %s" % (s["id"], old, exc))
        written = {}
result = {"problems": problems, "written": written, "failed": failed, "restored": len(done) if failed else 0}
'''
)

_READ = (
    _FIND
    + """
result = {}
for s in SPEC:
    t = _track(s["track"])
    p = _param(t, s)
    if p is None:
        gate = getattr(t.mixer_device, "track_activator", None)
        result[s["id"]] = [not t.mute, "on" if not t.mute else "off", gate.automation_state if gate else 0]
    else:
        result[s["id"]] = [p.value, p.str_for_value(p.value), p.automation_state]
"""
)


def _specs(knobs: Iterable[Knob], values: Mapping[Knob, object] | None = None) -> list[dict]:
    specs = []
    for k in knobs:
        where, name, unit = lom_target(k)
        s: dict[str, Any] = {
            "id": k.id,
            "track": k.track,
            "where": where,
            "name": name,
            "device": None if k.device == "Mixer" else tuple(k.device),
        }
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
    value: Any  # in .als units
    lom: Any  # the LOM's own value (bool for a track's activator)
    display: str  # what Live shows, e.g. "-7.8 dB"
    automated: bool


def set_many(client: McpTransport, values: Mapping[Knob, Any]) -> dict[Knob, Any]:
    """Write knob values (.als units) in one LOM call; return what was written, in LOM units.

    Every knob is found and checked first (a fader's position too); if any is missing, automated
    (a mute's track activator included), out of the LOM or fader range or without a known
    conversion, nothing is written and KnobError (or KeyError) says why. If Live refuses a write
    partway, the values already written in that call are put back before KnobError. The one case
    this cannot cover is the server's 12 s timeout cutting the call off mid-write; set_many's
    calls are a few writes, far below that.
    """
    specs = _specs(values, values)
    res = client.run(f"SPEC = {specs!r}\n" + _SET)
    if res["problems"] and res.get("failed"):
        raise KnobError(f"write failed, {res['restored']} earlier write(s) put back: " + "; ".join(res["problems"]))
    if res["problems"]:
        raise KnobError("nothing written: " + "; ".join(res["problems"]))
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


def apply(
    client: McpTransport, values: Mapping[Knob, object], *, verify: bool = True, tol: float = 1e-4
) -> dict[Knob, Reading]:
    """set_many, then (with verify) read_many in a separate call and check each LOM value is the
    one written, within tol. Returns the readings ({} without verify)."""
    written = set_many(client, values)
    if not verify:
        return {}
    got = read_many(client, values)
    off = [
        f"{k}: wrote {written[k]!r}, reads {got[k].lom!r} ({got[k].display})"
        for k in values
        if not (got[k].lom == written[k] if isinstance(written[k], bool) else abs(got[k].lom - written[k]) <= tol)
    ]
    if off:
        raise KnobError("read back differs: " + "; ".join(off))
    return got
