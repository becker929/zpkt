"""Probe kits as plans see them: metadata, version, tempo, and each knob's value and range in the kit.

A kit (hands/scripts/probe_pack/probe_kit.py) is a copy of a set trimmed to a lead-in plus one section repeated P
times, built once in the GUI. Its metadata is ``<kits>/<kit>.json``; its set is ``<sets>/<set>.als``. Its version is
the hash of the set's XML, so a kit rebuilt or edited gets new cache keys.

Everything here reads files only; nothing talks to Live.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .model import KnobId, KnobInfo

PROBE_PACK = Path(__file__).resolve().parents[3] / "scripts" / "probe_pack"


def kits_dir() -> Path:
    return Path(os.environ.get("HANDS_KITS", "~/_agent_scratch/probepack/kits")).expanduser()


def sets_dir() -> Path:
    return Path(os.environ.get("HANDS_SETS", "~/_agent_scratch/HW002")).expanduser()


def probe_pack() -> Any:
    """probe_kit (and with it als_probe and pp), imported from the scripts folder. Importing does not touch Live."""
    if str(PROBE_PACK) not in sys.path:
        sys.path.insert(0, str(PROBE_PACK))
    import probe_kit  # type: ignore[import-not-found]
    return probe_kit


@dataclass
class Kit:
    name: str
    set: str
    lead: float                  # beats before the first pattern
    pattern_beats: float
    P: int
    path: Path                   # the kit's .als
    beats_per_bar: int = 4

    @classmethod
    def load(cls, name: str, kits: Path | None = None, sets: Path | None = None) -> "Kit":
        meta_path = (kits or kits_dir()) / f"{name}.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"no kit {name!r} (looked for {meta_path}); build one with probe_kit.py template")
        meta = json.loads(meta_path.read_text())
        return cls(name=name, set=meta["set"], lead=float(meta["lead"]), pattern_beats=float(meta["pattern_beats"]),
                   P=int(meta["P"]), path=(sets or sets_dir()) / f"{meta['set']}.als",
                   beats_per_bar=int(meta.get("beats_per_bar", 4)))

    def xml(self) -> bytes:
        data = self.path.read_bytes()
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data

    def version(self) -> str:
        return hashlib.sha256(self.xml()).hexdigest()[:16]

    def tempo(self) -> float:
        root = ET.fromstring(self.xml())
        el = root.find("./LiveSet/MainTrack/DeviceChain/Mixer/Tempo/Manual")
        if el is None:
            raise ValueError(f"{self.path}: no tempo in the set")
        return float(el.get("Value"))

    def bar_seconds(self) -> float:
        return self.beats_per_bar * 60.0 / self.tempo()

    def bars_per_pattern(self) -> int:
        return int(round(self.pattern_beats / self.beats_per_bar))


def _number(el: ET.Element | None) -> float | None:
    if el is None:
        return None
    v = el.get("Value")
    if v in ("true", "false"):
        return 1.0 if v == "true" else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_knob(tree: Any, knob: KnobId) -> KnobInfo:
    """The knob's value and range in a parsed set (als_probe tree): its Manual value, and its MidiControllerRange
    (or 0-1 for switches and plugin parameters, which Live keeps normalised)."""
    pk = probe_pack()
    _, device, path = pk.resolve(tree, *knob.resolve_args())
    param = device.find(path)
    if param is None:
        raise KeyError(f"{knob}: no parameter at {path!r}")
    base = _number(param.find("Manual"))
    if base is None:
        raise KeyError(f"{knob}: the parameter has no numeric value")
    lo, hi = _number(param.find("MidiControllerRange/Min")), _number(param.find("MidiControllerRange/Max"))
    if lo is None or hi is None or hi <= lo:
        lo, hi = (0.0, 1.0) if 0.0 <= base <= 1.0 else (min(base, 0.0), max(base, 1.0))
    return KnobInfo(base=base, lo=lo, hi=hi)


class KnobReader:
    """Reads knobs from kits, parsing each kit's set once."""

    def __init__(self) -> None:
        self._trees: dict[Path, Any] = {}

    def __call__(self, kit: Kit, knobs: list[str]) -> dict[str, KnobInfo]:
        if kit.path not in self._trees:
            self._trees[kit.path] = probe_pack().X.load(str(kit.path))
        tree = self._trees[kit.path]
        return {k: read_knob(tree, KnobId.parse(k)) for k in knobs}
