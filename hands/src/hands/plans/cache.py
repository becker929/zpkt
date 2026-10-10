"""The render cache: every render kept by its key (the kit's version plus the canonical plan).

    <root>/entries/<key>/plan.json    the plan, its canonical knobs, the kit version, when and how it was rendered
    <root>/entries/<key>/audio.wav    the pattern's audio as Live exported it (first bar = the previous pattern's tail)

A plan already rendered plays at once. Nearest neighbour: with knob values scaled to their ranges, a cached plan
within a small distance can be offered while the exact one renders.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import KnobInfo, Plan, distance

NEAR = 0.08          # within 8% of the knobs' ranges (Euclidean, across knobs) counts as near


def cache_dir() -> Path:
    return Path(os.environ.get("HANDS_PLANS", "~/_agent_scratch/plans")).expanduser()


@dataclass
class Entry:
    key: str
    plan: Plan
    canonical: dict[str, float]
    kit_version: str
    audio: Path
    meta: dict[str, Any]


class Cache:
    def __init__(self, root: Path | None = None):
        self.root = root or cache_dir()
        self.entries = self.root / "entries"

    def get(self, key: str) -> Entry | None:
        d = self.entries / key
        if not (d / "plan.json").is_file() or not (d / "audio.wav").is_file():
            return None
        return self._entry(d)

    def put(self, key: str, plan: Plan, canonical: dict[str, float], kit_version: str, audio: Path,
            **meta: Any) -> Entry:
        d = self.entries / key
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "audio.wav.part"
        shutil.copyfile(audio, tmp)
        tmp.replace(d / "audio.wav")
        body = {"key": key, "plan": plan.to_json(), "canonical": canonical, "kit_version": kit_version,
                "rendered": time.time(), **meta}
        (d / "plan.json").write_text(json.dumps(body, indent=1))
        return self._entry(d)

    def all(self, kit_version: str | None = None) -> list[Entry]:
        if not self.entries.is_dir():
            return []
        out = []
        for d in sorted(self.entries.iterdir()):
            if (d / "plan.json").is_file() and (d / "audio.wav").is_file():
                e = self._entry(d)
                if kit_version is None or e.kit_version == kit_version:
                    out.append(e)
        return out

    def nearest(self, plan: Plan, kit_version: str, info: dict[str, KnobInfo],
                within: float = NEAR) -> tuple[Entry, float] | None:
        """The closest cached render of the same kit version, if it is within `within`."""
        want = plan.canonical(info)
        best: tuple[Entry, float] | None = None
        for e in self.all(kit_version):
            d = distance(want, e.canonical, info)
            if best is None or d < best[1]:
                best = (e, d)
        return best if best is not None and best[1] <= within else None

    @staticmethod
    def _entry(d: Path) -> Entry:
        body = json.loads((d / "plan.json").read_text())
        meta = {k: v for k, v in body.items() if k not in ("key", "plan", "canonical", "kit_version")}
        return Entry(key=body["key"], plan=Plan.from_json(body["plan"]), canonical=body["canonical"],
                     kit_version=body["kit_version"], audio=d / "audio.wav", meta=meta)
