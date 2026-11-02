"""check(): is this a score the booth will build? Saves nothing and never touches Live (POST /v1/check).

Errors are {path, code, message}: `path` points into the score ("parts[2].instrument") so the composer can fix just
that, and `code` is stable for the bot to act on. Warnings never stop a build. The estimate is the booth's guess at
the job's cost in Live time, from the measurements in docs/bluesky-bot.md ("Inside the booth").
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from . import compile as C
from . import palette as P
from .score import BEATS_PER_BAR, MAX_AUDIO_S, MAX_BARS, MAX_NOTES, Score

MIN_BARS = 4


@dataclass
class Result:
    ok: bool
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    estimate: dict | None = None
    score: Score | None = None

    def json(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "estimate": self.estimate}


def _path(loc: tuple) -> str:
    out = ""
    for k in loc:
        out += f"[{k}]" if isinstance(k, int) else (f".{k}" if out else str(k))
    return out


def estimate(score: Score, notes: int) -> dict:
    audio = score.seconds
    # measured on the first real runs (2026-11-01, 3 parts): open ~4 s, build ~15 s a part (browser loads and their
    # waits), export ~16 s, close and encode ~4 s; a quiet piece adds a second export (~18 s), counted at half
    render = 4 + 15 * len(score.parts) + 0.9 * notes / 400 + 16 + 0.1 * (audio + 2) + 4 + 9
    return {"audio_s": round(audio, 1), "render_s": round(render), "notes": notes}


def check(raw: Any) -> Result:
    try:
        score = Score.model_validate(raw)
    except ValidationError as exc:
        return Result(False, errors=[{"path": _path(e["loc"]), "code": "schema", "message": e["msg"]} for e in exc.errors()])
    errors: list[dict] = []
    warnings: list[dict] = []

    def err(path: str, code: str, message: str) -> None:
        errors.append({"path": path, "code": code, "message": message})

    def warn(path: str, code: str, message: str) -> None:
        warnings.append({"path": path, "code": code, "message": message})

    try:
        pal = P.load(score.palette)
    except KeyError:
        err("palette", "unknown_palette", f"the booth has palettes {P.versions()}")
        return Result(False, errors=errors)

    for name, items in (("parts", score.parts), ("patterns", score.patterns)):
        for iid, n in Counter(x.id for x in items).items():
            if n > 1:
                err(name, "duplicate_id", f"{iid!r} is used {n} times")
    parts = {p.id: p for p in score.parts}
    patterns = {p.id: p for p in score.patterns}

    for i, part in enumerate(score.parts):
        inst = pal.instruments.get(part.instrument)
        if not inst:
            err(f"parts[{i}].instrument", "unknown_instrument", f"{part.instrument!r} is not in palette {pal.version}")
            continue
        for k, m in enumerate(part.macros):
            if m.name not in inst.macros:
                err(f"parts[{i}].macros[{k}].name", "unknown_macro",
                    f"{part.instrument} has macros {sorted(inst.macros) or 'none'}")
        for name, n in Counter(m.name for m in part.macros).items():
            if n > 1:
                err(f"parts[{i}].macros", "duplicate_macro", f"{name!r} is set {n} times")

    for i, pat in enumerate(score.patterns):
        owner = parts.get(pat.part)
        if not owner:
            err(f"patterns[{i}].part", "unknown_part", f"no part {pat.part!r}")
        inst = pal.instruments.get(owner.instrument) if owner else None
        length = pat.bars * BEATS_PER_BAR
        if not pat.notes:
            warn(f"patterns[{i}]", "empty_pattern", f"{pat.id!r} has no notes")
        for k, n in enumerate(pat.notes):
            if n.t >= length:
                err(f"patterns[{i}].notes[{k}].t", "note_outside_pattern", f"starts at beat {n.t}; the pattern is {length} beats")
            if inst and not inst.range[0] <= n.p <= inst.range[1]:
                err(f"patterns[{i}].notes[{k}].p", "pitch_out_of_range", f"{owner.instrument} plays {inst.range[0]}-{inst.range[1]}")

    used_parts: set[str] = set()
    used_patterns: set[str] = set()
    for s, sec in enumerate(score.song):
        if not sec.play:
            warn(f"song[{s}]", "silent_section", f"{sec.bars} bars of silence")
        for name, n in Counter(p.part for p in sec.play).items():
            if n > 1:
                err(f"song[{s}].play", "duplicate_play", f"part {name!r} plays {n} patterns at once")
        for k, play in enumerate(sec.play):
            if play.part not in parts:
                err(f"song[{s}].play[{k}].part", "unknown_part", f"no part {play.part!r}")
            pat = patterns.get(play.pattern)
            if not pat:
                err(f"song[{s}].play[{k}].pattern", "unknown_pattern", f"no pattern {play.pattern!r}")
            elif pat.part != play.part:
                err(f"song[{s}].play[{k}]", "pattern_part_mismatch", f"pattern {pat.id!r} belongs to part {pat.part!r}")
            used_parts.add(play.part)
            used_patterns.add(play.pattern)
    for i, part in enumerate(score.parts):
        if part.id not in used_parts:
            warn(f"parts[{i}]", "unused_part", f"{part.id!r} never plays")
    for i, pat in enumerate(score.patterns):
        if pat.id not in used_patterns:
            warn(f"patterns[{i}]", "unused_pattern", f"{pat.id!r} is never played")

    for name in ("room", "echo"):
        setting = getattr(score.mix, name)
        if setting not in pal.returns[name].settings:
            err(f"mix.{name}", "unknown_setting", f"{name} settings are {sorted(pal.returns[name].settings)}")

    if score.bars < MIN_BARS:
        err("song", "too_short", f"{score.bars} bars; at least {MIN_BARS}")
    if score.bars > MAX_BARS:
        err("song", "too_long", f"{score.bars} bars; at most {MAX_BARS}")
    if score.seconds > MAX_AUDIO_S:
        err("song", "too_long", f"{score.seconds:.1f} s at {score.bpm:g} BPM; at most {MAX_AUDIO_S:g} s")

    notes = 0
    if not errors:
        plan = C.compile(score, pal)
        notes = sum(len(t.notes) for t in plan.tracks)
        if notes > MAX_NOTES:
            err("song", "too_many_notes", f"{notes} notes once patterns repeat; at most {MAX_NOTES}")
        if notes == 0:
            err("song", "no_notes", "nothing plays")
    return Result(not errors, errors, warnings, estimate(score, notes) if not errors else None, score if not errors else None)
