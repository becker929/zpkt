"""Knob ids, plans, the canonical plan and its cache key, and the plans worth rendering ahead.

A knob id names one device parameter in a kit: ``<track>|<device>|<parameter>``.

- device: ``Mixer`` (the track's mixer: ``Volume``, ``Pan``, sends), ``plugin:<name>`` for a VST/AU plugin (the
  parameter is its display name, e.g. ``plugin:Decapitator`` / ``Drive``), or ``<DeviceTag>:<index>`` for a Live
  device, the index counting devices with that tag on the track (``-1`` = the last), with an XML path for the
  parameter (``Eq8:0`` / ``Bands.1/ParameterA/Gain``).
- values are in the set's own units (dB for EQ gains, 0-1 for plugin parameters).

The canonical plan drops knobs left at the kit's value and rounds the rest, so two plans that sound the same have
the same key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

DECIMALS = 4


@dataclass(frozen=True)
class KnobId:
    track: str
    device: str
    param: str

    @classmethod
    def parse(cls, text: str) -> "KnobId":
        parts = text.split("|")
        if len(parts) != 3 or not all(p.strip() for p in parts):
            raise ValueError(f"a knob id is <track>|<device>|<parameter>, got {text!r}")
        track, device, param = (p.strip() for p in parts)
        if device != "Mixer" and not device.startswith("plugin:"):
            tag, _, index = device.rpartition(":")
            if not tag or not index.lstrip("-").isdigit():
                raise ValueError(f"device must be Mixer, plugin:<name> or <DeviceTag>:<index>, got {device!r}")
        return cls(track, device, param)

    def resolve_args(self) -> tuple[str, Any, str]:
        """(track, device spec, parameter) as probe_kit.resolve takes them."""
        if self.device == "Mixer":
            return self.track, "Mixer", self.param
        if self.device.startswith("plugin:"):
            return self.track, ("plugin", self.device[len("plugin:"):]), self.param
        tag, _, index = self.device.rpartition(":")
        return self.track, (tag, int(index)), self.param

    def __str__(self) -> str:
        return f"{self.track}|{self.device}|{self.param}"


@dataclass(frozen=True)
class KnobInfo:
    """A knob's value in the kit and its range (for distances between plans)."""
    base: float
    lo: float
    hi: float

    @property
    def span(self) -> float:
        return (self.hi - self.lo) or 1.0

    def clamp(self, v: float) -> float:
        return min(max(v, self.lo), self.hi)


@dataclass
class Plan:
    kit: str
    knobs: dict[str, float] = field(default_factory=dict)
    label: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Plan":
        if "kit" not in data:
            raise ValueError("a plan needs a kit")
        knobs = {}
        for k, v in (data.get("knobs") or {}).items():
            KnobId.parse(k)
            knobs[k] = float(v) if not isinstance(v, bool) else float(v)
        return cls(kit=str(data["kit"]), knobs=knobs, label=str(data.get("label", "")))

    def to_json(self) -> dict[str, Any]:
        return {"kit": self.kit, "knobs": dict(self.knobs), "label": self.label}

    def values(self, info: dict[str, KnobInfo]) -> dict[str, float]:
        """Every knob in `info`, at this plan's value or the kit's."""
        return {k: self.knobs.get(k, i.base) for k, i in info.items()}

    def canonical(self, info: dict[str, KnobInfo]) -> dict[str, float]:
        """Rounded, sorted, without knobs left at the kit's value."""
        out = {}
        for k in sorted(self.knobs):
            v = round(self.knobs[k], DECIMALS)
            if k in info and v == round(info[k].base, DECIMALS):
                continue
            out[k] = v
        return out

    def key(self, kit_version: str, info: dict[str, KnobInfo]) -> str:
        body = json.dumps({"kit": kit_version, "knobs": self.canonical(info)}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def describe(self) -> str:
        if self.label:
            return self.label
        return ", ".join(f"{KnobId.parse(k).param} {v:g}" for k, v in sorted(self.knobs.items())) or "as set"


def distance(a: dict[str, float], b: dict[str, float], info: dict[str, KnobInfo]) -> float:
    """Euclidean distance with each knob scaled to its range, so knobs in dB and 0-1 knobs compare. Knobs one plan
    leaves out are at the kit's value."""
    total = 0.0
    for k in set(a) | set(b):
        i = info.get(k) or KnobInfo(0.0, 0.0, 1.0)
        total += ((a.get(k, i.base) - b.get(k, i.base)) / i.span) ** 2
    return total ** 0.5


def write_ahead(a: Plan, b: Plan, info: dict[str, KnobInfo]) -> list[Plan]:
    """The likely next asks after hearing A against B: "more" (B pushed as far again) and "the other end" (A pushed
    the other way), each clamped to the knobs' ranges. Guesses that come out the same as A or B are left out."""
    knobs = set(a.knobs) | set(b.knobs)
    if not knobs:
        return []
    av = {k: a.knobs.get(k, info[k].base if k in info else 0.0) for k in knobs}
    bv = {k: b.knobs.get(k, info[k].base if k in info else 0.0) for k in knobs}

    def clamp(k: str, v: float) -> float:
        return info[k].clamp(v) if k in info else v

    more = {k: clamp(k, bv[k] + (bv[k] - av[k])) for k in knobs}
    other = {k: clamp(k, av[k] - (bv[k] - av[k])) for k in knobs}
    out = []
    for vals, label in ((more, f"more: {b.describe()}"), (other, f"the other end: {a.describe()}")):
        if all(round(vals[k], DECIMALS) == round(bv[k], DECIMALS) for k in knobs):
            continue
        if all(round(vals[k], DECIMALS) == round(av[k], DECIMALS) for k in knobs):
            continue
        out.append(Plan(a.kit, vals, label))
    return out
