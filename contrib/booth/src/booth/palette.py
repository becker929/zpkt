"""The palette: the booth's own table of what a score may name (palettes/<version>.toml).

Only the booth reads `load`, `fx`, `set` and the macro mappings; `guide()` is what the bot (and Claude) see.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

PALETTES = Path(__file__).resolve().parents[2] / "palettes"
# The palette GET /v1/guide serves, so the one the composer writes for, unless BOOTH_HOME/config.toml names another
# (`palette = "2026-12"`). A new palette file changes nothing until one of the two says so: check, compile and jobs
# take any palette the booth has, since a score carries its own version.
SERVED = "2026-11"
UNIT = re.compile(r"^\s*(-?[\d.]+)\s*(dB|ms|Hz|kHz|%|s|st|ct)?\s*$")


@dataclass(frozen=True)
class MacroMap:
    """A 0..1 macro, linear between two display values on one device of the part's chain."""

    device: int
    param: str
    lo: str
    hi: str

    def display(self, value: float) -> str:
        a, b = UNIT.match(self.lo), UNIT.match(self.hi)
        if not a or not b or a.group(2) != b.group(2):
            raise ValueError(f"macro {self.param}: {self.lo!r} and {self.hi!r} are not in one unit")
        v = float(a.group(1)) + (float(b.group(1)) - float(a.group(1))) * value
        return f"{v:.2f} {a.group(2)}" if a.group(2) else f"{v:.4f}"


@dataclass(frozen=True)
class Instrument:
    id: str
    role: str
    load: tuple[str, str, str]                    # browser root, folder ("" for the root's top), item
    range: tuple[int, int]
    about: str
    trim: float = 0.0
    fx: tuple[str, ...] = ()
    set: dict[int, dict[str, Any]] = field(default_factory=dict)
    macros: dict[str, MacroMap] = field(default_factory=dict)

    @property
    def device_name(self) -> str:
        """What Live calls the first device once loaded (a preset loads as its file name without the extension)."""
        return self.load[2].rsplit(".", 1)[0]


@dataclass(frozen=True)
class Return:
    track: int
    device: str
    settings: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Palette:
    version: str
    instruments: dict[str, Instrument]
    returns: dict[str, Return]
    master_devices: tuple[str, ...]
    master_set: dict[int, dict[str, Any]]

    def guide(self) -> dict:
        """What the composer sees. Drum kits carry their pads' names from `booth survey` (<version>.survey.json),
        read from Live itself, those inside the kit's range only."""
        survey = PALETTES / f"{self.version}.survey.json"
        found = json.loads(survey.read_text()) if survey.is_file() else {}
        pads = {k: [(n, name) for n, name in v.get("pads", []) if self.instruments[k].range[0] <= n <= self.instruments[k].range[1]]
                for k, v in found.items() if k in self.instruments}
        return {
            "palette": self.version,
            "instruments": [
                {"id": i.id, "role": i.role, "range": list(i.range), "about": i.about, "macros": sorted(i.macros),
                 **({"pads": [{"note": n, "name": name} for n, name in pads[i.id]]} if pads.get(i.id) else {})}
                for i in self.instruments.values()
            ],
            "returns": {name: sorted(r.settings) for name, r in self.returns.items()},
        }


def _parse(raw: dict) -> Palette:
    instruments = {}
    for iid, d in raw["instrument"].items():
        instruments[iid] = Instrument(
            id=iid, role=d["role"], load=tuple(d["load"]), range=tuple(d["range"]), about=d["about"],
            trim=float(d.get("trim", 0.0)), fx=tuple(d.get("fx", ())),
            set={int(k): v for k, v in d.get("set", {}).items()},
            macros={name: MacroMap(**m) for name, m in d.get("macros", {}).items()},
        )
    returns = {name: Return(track=d["track"], device=d["device"], settings=d["settings"]) for name, d in raw["returns"].items()}
    master = raw["master"]
    return Palette(version=raw["version"], instruments=instruments, returns=returns,
                   master_devices=tuple(master["devices"]), master_set={int(k): v for k, v in master["set"].items()})


@cache
def load(version: str) -> Palette:
    """The palette of that version. Raises KeyError for one the booth doesn't have."""
    if not re.fullmatch(r"\d{4}-\d{2}", version):
        raise KeyError(version)
    path = PALETTES / f"{version}.toml"
    if not path.is_file():
        raise KeyError(version)
    pal = _parse(tomllib.loads(path.read_text()))
    if pal.version != version:
        raise ValueError(f"{path.name} says it is {pal.version}")
    return pal


def versions() -> list[str]:
    return sorted(p.stem for p in PALETTES.glob("*.toml"))


def served(pin: str | None = None) -> Palette:
    """The palette the guide serves: `pin` (config.toml's `palette`) if set, else SERVED."""
    return load(pin or SERVED)
