"""Horizontal probe kit: one Live load and one Main export render P variants of a section.

  template  once per shape: copy a set, keep [0, lead) plus one section, Duplicate Time to P
            patterns, save. A kit is "<new_set_prefix>kit_<name>" in sets_dir, described by
            <data_dir>/kits/<name>.json.
  batch     per batch, offline: add donor devices and step any knob per pattern, written into a
            copy of the kit (.als XML, hands.als). Pattern k starts at lead + k * pattern_beats.
  render    load the batch set, export Main once, check the render, slice one WAV per pattern.

Measured on HW002 (docs/probe-packing-findings.md): about 4 s per 20-bar probe at P = 16 and
1.8 s per 8-bar probe at P = 32, with Live's memory flat in P. Patterns sit at different song
positions and tails ring into the next one, so compare features, not samples, and keep control
patterns in every batch. Every Live step is guarded (session.check) and stops on a surprise.

    hands kit template KIT SRC_SET KEEP_START KEEP_END P [--lead 8]
    hands kit render BATCH_SET KIT [--out DIR]
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from hands import als, audio, config
from hands.live import render as live_render
from hands.live import session, timeops
from hands.live.knobs import Knob
from hands.live.session import stop
from hands.live.transport import McpTransport
from hands.steps import timing

Step = tuple[Knob, Sequence]  # one value per pattern, in the knob's .als units


@dataclass
class Kit:
    kit: str               # the kit's name, e.g. "c8x4"
    set: str               # its Live set in sets_dir
    src: str               # the set it was cut from
    keep: list[float]      # [start, end) of the section in src, in beats
    lead: float            # beats before the first pattern
    pattern_beats: float
    P: int

    @staticmethod
    def path(name: str) -> Path:
        return config.rig().data_dir / "kits" / f"{name}.json"

    @classmethod
    def load(cls, name: str) -> Kit:
        return cls(**json.loads(cls.path(name).read_text()))

    def save(self) -> Path:
        path = self.path(self.kit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1))
        return path

    @property
    def length_beats(self) -> float:
        return self.lead + self.P * self.pattern_beats

    def step_times(self) -> list[float]:
        """Where each pattern's value starts: pattern 0's holds from the start of the song."""
        return [0.0] + [self.lead + j * self.pattern_beats for j in range(1, self.P)]


def _kit(kit: Kit | str) -> Kit:
    return Kit.load(kit) if isinstance(kit, str) else kit


def template(client: McpTransport, kit: str, src: str, keep_start: float, keep_end: float, P: int,
             lead: float = 8.0) -> Kit:
    """Build a kit set in Live: [0, lead) of `src` + [keep_start, keep_end), repeated P times.

    P must be a power of two: Duplicate Time doubles the region. Takes 14 s + 7 s per doubling.
    """
    if P < 1 or P & (P - 1):
        raise ValueError("P must be a power of two (built by doubling)")
    name = f"{config.rig().new_set_prefix}kit_{kit}"
    pat = keep_end - keep_start
    if session.check(client, "kit:start") == name:
        stop(f"kit: {name} is open; open another set before rebuilding it")
    session.copy_set(src, name)
    timing("kit_load", session.open_set(client, name), kit=kit)
    session.check(client, "kit:loaded", expect_front=name)
    end = timeops.song_end(client)
    if end > keep_end + 1.0:
        timeops.delete(client, keep_end, end - keep_end, tol=1.0)  # a breakpoint past the content may stay
        session.check(client, "kit:trim_tail", expect_front=name)
    if keep_start > lead:
        timeops.delete(client, lead, keep_start - lead, tol=1.0)
        session.check(client, "kit:trim_gap", expect_front=name)
    end = timeops.song_end(client)
    if not lead + pat <= end <= lead + pat + 2.0:
        stop(f"kit: after trims the set ends at {end}, expected about {lead + pat}")
    n = 1
    while n < P:
        t = time.monotonic()
        timeops.duplicate(client, lead, n * pat, end=lead + 2 * n * pat, clips_from=lead)
        timing("kit_duplicate", time.monotonic() - t, kit=kit, to_P=2 * n)
        n *= 2
        session.check(client, f"kit:dup{n}", expect_front=name)
    session.save(name)
    session.check(client, "kit:saved", expect_front=name)
    made = Kit(kit=kit, set=name, src=src, keep=[keep_start, keep_end], lead=lead, pattern_beats=pat, P=P)
    made.save()
    return made


def write_batch(kit: Kit | str, tag: str, steps: Iterable[Step], devices: Iterable[tuple] = ()) -> str:
    """Offline: a batch set from the kit, with devices added and knobs stepped per pattern.

    devices: (track, donor_set, donor_track, device_tag), each appended to `track`.
    Returns the batch set's name, "<new_set_prefix>x_<kit>_<tag>", after als.check passes.
    """
    kit = _kit(kit)
    rig = config.rig()
    tree = als.load(rig.set_path(kit.set))
    for track, donor_set, donor_track, device_tag in devices:
        donor = als.find_device(als.find_track(als.load(rig.set_path(donor_set)), donor_track), device_tag)
        als.add_device_from_donor(tree, als.find_track(tree, track), donor)
    times = kit.step_times()
    for knob, values in steps:
        if len(values) != kit.P:
            raise ValueError(f"{knob}: {len(values)} values for {kit.P} patterns")
        track, device, path = als.resolve(tree, *knob.spec)
        als.set_steps(tree, track, device, path, list(zip(times, values)))
    name = f"{rig.new_set_prefix}x_{kit.kit}_{tag}"
    problems = als.check(als.save(tree, rig.set_path(name), overwrite=True)).problems
    if problems:
        stop(f"batch {name}: als check failed: {problems}")
    return name


def render(client: McpTransport, batch_set: str, kit: Kit | str, out_dir: str | Path) -> dict:
    """Guarded load, one Main export, a silence and length check, and one WAV per pattern
    (pattern_XX.wav beside all.wav). Writes and returns manifest.json."""
    kit = _kit(kit)
    out_dir = Path(out_dir)
    session.check(client, "render:start")
    t_load = session.open_set(client, batch_set)
    session.check(client, "render:loaded", expect_front=batch_set)
    out_dir.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    live_render.export(client, out_dir / "all.wav", 0.0, kit.length_beats, mode="Main")
    t_export = time.monotonic() - t
    session.check(client, "render:exported", expect_front=batch_set)
    spb = 60.0 / client.run("result = song.tempo")
    audio.check_audio(out_dir / "all.wav", seconds=kit.length_beats * spb)
    cuts = [(kit.lead + k * kit.pattern_beats) * spb for k in range(kit.P + 1)]
    files = audio.slice_render(out_dir / "all.wav", cuts, out_dir)
    manifest = {"batch_set": batch_set, "kit": asdict(kit), "load_s": round(t_load, 2), "export_s": round(t_export, 2),
                "files": [str(f) for f in files], "seconds_per_probe": round((t_load + t_export) / kit.P, 2)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    timing("kit_render", t_load + t_export, kit=kit.kit, P=kit.P, load=round(t_load, 2), export=round(t_export, 2))
    return manifest


def merge_patterns(patterns: Sequence[Iterable[tuple[Knob, object]]], P: int,
                   baseline: Callable[[Knob], object], *, taken: Iterable[Knob] = ()) -> list[Step]:
    """One step envelope per knob from per-pattern settings.

    patterns[j] lists the (knob, value) pairs pattern j sets (at most P patterns). A pattern that
    does not set a knob keeps baseline(knob), the set's own value (als.current_value), as do the
    patterns past the listed ones. Knobs in `taken` (stepped already, e.g. by a baseline mix)
    are refused: two envelopes on one parameter would fight.
    """
    if len(patterns) > P:
        raise ValueError(f"{len(patterns)} patterns for a {P}-pattern kit")
    taken = set(taken)
    rows: dict[Knob, list] = {}
    for j, sets in enumerate(patterns):
        for knob, value in sets:
            if knob in taken:
                raise ValueError(f"{knob} is already set by the baseline")
            if knob not in rows:
                rows[knob] = [baseline(knob)] * P
            rows[knob][j] = value
    return list(rows.items())


def constant(values: Mapping[Knob, object], P: int) -> list[Step]:
    """Steps that hold each knob at one value in every pattern (a view's mutes, a fixed setting)."""
    return [(knob, [value] * P) for knob, value in values.items()]


def scale(u: float, lo: float, hi: float, kind: str) -> float | bool:
    """A knob value from a position u in [0, 1]: "lin" or "log" between lo and hi, or "bool"."""
    if kind == "bool":
        return bool(u >= 0.5)
    return lo + (hi - lo) * u if kind == "lin" else lo * (hi / lo) ** u


def unscale(v: float | bool, lo: float, hi: float, kind: str) -> float:
    """The position in [0, 1] of a knob value; raises if it is outside [lo, hi]."""
    if kind == "bool":
        return 0.75 if v else 0.25
    u = (v - lo) / (hi - lo) if kind == "lin" else math.log(v / lo) / math.log(hi / lo)
    if not -1e-6 <= u <= 1 + 1e-6:
        raise ValueError(f"value {v} outside [{lo}, {hi}]")
    return min(1.0, max(0.0, u))
