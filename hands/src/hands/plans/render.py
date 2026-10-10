"""Rendering plans: packed into kit batches, kept in the cache, with the likely next asks rendered alongside.

Plans on the same kit are written into one copy of the kit, one pattern each, and rendered with one load and one
export (probe_kit): ~7 s to load and ~13 s plus a tenth of the audio's length to export, so four plans cost barely
more than two. Patterns a pack does not fill repeat its first plan.

The Live renderer goes through probe_kit's guarded steps: no dialog open, one of our sets in front, Live answering.
If anything is off it stops with pp.Guard and renders nothing.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from .cache import Cache, Entry
from .kits import Kit, KnobReader, probe_pack
from .model import KnobId, KnobInfo, Plan, write_ahead


class Renderer(Protocol):
    def render(self, kit: Kit, patterns: list[dict[str, float]], tag: str) -> tuple[list[Path], dict[str, Any]]:
        """Render one kit batch: `patterns` holds every knob's value per pattern (len == kit.P). Returns one WAV per
        pattern and timings."""


class LiveRenderer:
    def __init__(self, work: Path | None = None):
        self.work = work or Path(os.environ.get("HANDS_PLANS", "~/_agent_scratch/plans")).expanduser() / "work"

    def render(self, kit: Kit, patterns: list[dict[str, float]], tag: str) -> tuple[list[Path], dict[str, Any]]:
        pk = probe_pack()
        knobs = sorted({k for p in patterns for k in p})
        steps = []
        for k in knobs:
            track, dev, param = KnobId.parse(k).resolve_args()
            steps.append((track, dev, param, [p[k] for p in patterns]))
        t0 = time.time()
        batch = pk.write_batch(kit.name, tag, devices=[], steps=steps)
        out = self.work / f"{tag}-{int(time.time())}"
        man = pk.render(batch, kit.name, str(out))
        return [Path(f) for f in man["files"]], {"batch_set": batch, "load_s": man["load_s"],
                                                  "export_s": man["export_s"], "total_s": round(time.time() - t0, 2)}


class FakeRenderer:
    """For tests and dry runs: a tone per pattern whose pitch and level follow the knob values (so different plans
    sound different and loudness matching has something to do), at the kit's tempo and pattern length."""

    def __init__(self, work: Path, sr: int = 44_100, bar_seconds: float = 0.25):
        self.work, self.sr, self.bar_seconds = work, sr, bar_seconds
        self.calls: list[list[dict[str, float]]] = []

    def render(self, kit: Kit, patterns: list[dict[str, float]], tag: str) -> tuple[list[Path], dict[str, Any]]:
        import numpy as np
        import soundfile as sf

        self.calls.append(patterns)
        out = self.work / tag
        out.mkdir(parents=True, exist_ok=True)
        n = int(self.bar_seconds * kit.bars_per_pattern() * self.sr)
        t = np.arange(n) / self.sr
        files = []
        for j, p in enumerate(patterns):
            s = sum(p.values())
            y = (0.1 + 0.05 * (s % 4)) * np.sin(2 * np.pi * (220 + 40 * s) * t)
            f = out / f"pattern_{j:02d}.wav"
            sf.write(f, np.stack([y, y], axis=1).astype(np.float32), self.sr, subtype="FLOAT")
            files.append(f)
        return files, {"batch_set": f"fake_{tag}", "load_s": 0.0, "export_s": 0.0, "total_s": 0.0}


@dataclass
class Result:
    entries: list[Entry]                       # the plans asked for, in order
    rendered: list[str] = field(default_factory=list)          # keys rendered now (asked for or written ahead)
    cached: list[str] = field(default_factory=list)            # keys that were already there
    ahead: list[Entry] = field(default_factory=list)           # the write-ahead renders
    timings: list[dict[str, Any]] = field(default_factory=list)


class Planner:
    def __init__(self, cache: Cache | None = None, renderer: Renderer | None = None,
                 reader: Any = None, kits: Path | None = None, sets: Path | None = None):
        self.cache = cache or Cache()
        self.renderer = renderer or LiveRenderer()
        self.reader = reader or KnobReader()
        self.kits, self.sets = kits, sets

    # --- what a plan is -----------------------------------------------------------------------------------------
    def kit(self, name: str) -> Kit:
        return Kit.load(name, self.kits, self.sets)

    def info(self, kit: Kit, knobs: set[str]) -> dict[str, KnobInfo]:
        return self.reader(kit, sorted(knobs)) if knobs else {}

    def key(self, plan: Plan) -> tuple[str, str, dict[str, KnobInfo]]:
        kit = self.kit(plan.kit)
        info = self.info(kit, set(plan.knobs))
        version = kit.version()
        return plan.key(version, info), version, info

    def lookup(self, plan: Plan) -> dict[str, Any]:
        """An exact hit, else the nearest cached render within reach, else nothing."""
        kit = self.kit(plan.kit)
        version = kit.version()
        cached = self.cache.all(version)
        info = self.info(kit, set(plan.knobs) | {k for e in cached for k in e.canonical})
        key = plan.key(version, info)
        hit = self.cache.get(key)
        if hit is not None:
            return {"key": key, "hit": True, "audio": str(hit.audio), "plan": hit.plan.to_json()}
        near = self.cache.nearest(plan, version, info)
        if near is None:
            return {"key": key, "hit": False}
        entry, d = near
        return {"key": key, "hit": False, "nearest": {"key": entry.key, "distance": round(d, 4),
                                                      "audio": str(entry.audio), "plan": entry.plan.to_json()}}

    # --- rendering ----------------------------------------------------------------------------------------------
    def ensure(self, plans: list[Plan], ahead_of: tuple[Plan, Plan] | None = None) -> Result:
        """Render whatever of `plans` is not cached, packed with the write-ahead guesses after (A, B), one batch per
        P plans. Returns the cache entries for `plans` in order."""
        if not plans:
            return Result(entries=[])
        kits = {p.kit for p in plans}
        if len(kits) != 1:
            raise ValueError(f"plans in one call share a kit; got {sorted(kits)}")
        kit = self.kit(plans[0].kit)
        version = kit.version()
        knobs = {k for p in plans + list(ahead_of or ()) for k in p.knobs}
        info = self.info(kit, knobs)
        guesses = write_ahead(*ahead_of, info) if ahead_of else []
        result = Result(entries=[])
        with self._lock():
            todo: list[tuple[str, Plan]] = []
            seen: set[str] = set()
            for p in plans + guesses:
                key = p.key(version, info)
                if key in seen:
                    continue
                seen.add(key)
                if self.cache.get(key) is not None:
                    result.cached.append(key)
                else:
                    todo.append((key, p))
            for i in range(0, len(todo), kit.P):
                pack = todo[i:i + kit.P]
                patterns = [p.values(info) for _, p in pack]
                patterns += [patterns[0]] * (kit.P - len(patterns))
                tag = "plan_" + hashlib.sha256("".join(k for k, _ in pack).encode()).hexdigest()[:10]
                files, timing = self.renderer.render(kit, patterns, tag)
                timing = {**timing, "plans": len(pack), "P": kit.P}
                result.timings.append(timing)
                for (key, p), f in zip(pack, files):
                    self.cache.put(key, p, p.canonical(info), version, f, render=timing)
                    result.rendered.append(key)
        result.entries = [self.cache.get(p.key(version, info)) for p in plans]      # type: ignore[misc]
        result.ahead = [e for g in guesses if (e := self.cache.get(g.key(version, info))) is not None]
        return result

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """One render at a time on this Mac (Live has one front set)."""
        self.cache.root.mkdir(parents=True, exist_ok=True)
        with open(self.cache.root / ".render.lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
