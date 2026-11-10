"""check(): is this a score the booth will build? Saves nothing and never touches Live (POST /v1/check).

Errors are {path, code, message}: `path` points into the score ("parts[2].instrument") so the composer can fix just
that, and `code` is stable for the bot to act on. Warnings never stop a build. The estimate is the booth's guess at
the job's cost in Live time, from the measurements in contrib/docs/design/bluesky-bot.md ("Inside the booth").
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from . import compile as C
from . import palette as P
from . import samples as S
from .score import BEATS_PER_BAR, MAX_AUDIO_S, MAX_BARS, MAX_CLIPS, MAX_NOTES, Score

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


def estimate(score: Score, notes: int, clips: int = 0) -> dict:
    audio = score.seconds
    # measured on the first real runs (2026-11-01, 3 parts): open ~4 s, build ~15 s a part (browser loads and their
    # waits), export ~16 s, close and encode ~4 s; a quiet piece adds a second export (~18 s), counted at half. A clip
    # part loads nothing from the browser: about ten short calls, then a call for each 8 copies (not yet measured)
    loads = sum(1 for p in score.parts if not (p.sample and p.sample.mode == "clip"))
    render = 4 + 15 * loads + 9 * (len(score.parts) - loads) + clips / 8 + 0.9 * notes / 400 + 16 + 0.1 * (audio + 2) + 4 + 9
    out = {"audio_s": round(audio, 1), "render_s": round(render), "notes": notes}
    return {**out, "clips": clips} if clips else out


# Fields of Sample that mean something in one mode only: given in another, they are a mistake worth saying
CLIP_ONLY = ("start_beat", "length_beats", "loop", "warp", "fit_beats", "transpose")


def _sample(i: int, part, modes, err, warn) -> dict | None:
    """Errors for one sample part; its measurements if it may play."""
    sm, where = part.sample, f"parts[{i}].sample"
    if modes is not None and sm.mode not in modes:
        err(f"{where}.mode", "samples_off", f"the booth takes samples in modes {sorted(modes) or 'none'} now")
        return None
    meta = S.info(sm.id)
    if not meta:
        err(f"{where}.id", "unknown_sample", f"the booth has no sample {sm.id}; upload it first (POST /v1/samples)")
        return None
    # a structured output may send every field, so only a value other than the default counts as given
    given = {f for f in CLIP_ONLY if getattr(sm, f) != type(sm).model_fields[f].default}
    wrong = [f for f in CLIP_ONLY if f in given] if sm.mode != "clip" else []
    wrong += ["slices"] if sm.mode != "slices" and sm.slices else []
    for f in wrong:
        err(f"{where}.{f}", "sample_field_mode", f"{f} is not used in mode {sm.mode}")
    if part.macros:
        err(f"parts[{i}].macros", "unknown_macro", "a sample part has no macros")
    if sm.mode == "clip" and sm.warp == "off" and sm.fit_beats is not None:
        err(f"{where}.fit_beats", "sample_field_mode", "fit_beats needs warp beats or complex")
    if sm.mode == "slices":
        ts = sm.slices
        if len(ts) < 2:
            err(f"{where}.slices", "bad_slices", "at least two slices, the first at 0")
        elif ts[0] != 0 or any(b <= a for a, b in zip(ts, ts[1:])):
            err(f"{where}.slices", "bad_slices", "slice starts rise from 0")
        elif ts[-1] >= meta["seconds"] - 0.01:
            err(f"{where}.slices", "bad_slices", f"the sample is {meta['seconds']:.2f} s long")
    return meta


def check(raw: Any, *, samples: list[str] | tuple[str, ...] | None = None) -> Result:
    """`samples`: the sample modes the booth takes now (config.toml's `samples`); None takes all of them, for a score
    already accepted and for the CLI."""
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

    metas: dict[str, dict] = {}
    for i, part in enumerate(score.parts):
        if (part.instrument is None) == (part.sample is None):
            err(f"parts[{i}]", "part_source", "a part has an instrument or a sample, one of the two")
            continue
        if part.sample:
            meta = _sample(i, part, samples, err, warn)
            if meta:
                metas[part.id] = meta
            continue
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
        inst = pal.instruments.get(owner.instrument) if owner and owner.instrument else None
        rng = inst.range if inst else None
        if owner and owner.sample:
            if owner.sample.mode == "clip":
                err(f"patterns[{i}].part", "clip_part_pattern", f"{owner.id!r} places its sample as clips; it plays no patterns")
            rng = C.pitch_range(owner.sample.mode, len(owner.sample.slices))
        length = pat.bars * BEATS_PER_BAR
        if not pat.notes:
            warn(f"patterns[{i}]", "empty_pattern", f"{pat.id!r} has no notes")
        for k, n in enumerate(pat.notes):
            if n.t >= length:
                err(f"patterns[{i}].notes[{k}].t", "note_outside_pattern", f"starts at beat {n.t}; the pattern is {length} beats")
            if rng and not rng[0] <= n.p <= rng[1]:
                err(f"patterns[{i}].notes[{k}].p", "pitch_out_of_range", f"{owner.instrument or 'its sample'} plays {rng[0]}-{rng[1]}")

    used_parts: set[str] = set()
    used_patterns: set[str] = set()
    for s, sec in enumerate(score.song):
        if not sec.play and not any(p.sample and p.sample.mode == "clip" for p in score.parts):
            warn(f"song[{s}]", "silent_section", f"{sec.bars} bars of silence")
        for name, n in Counter(p.part for p in sec.play).items():
            if n > 1:
                err(f"song[{s}].play", "duplicate_play", f"part {name!r} plays {n} patterns at once")
        for k, play in enumerate(sec.play):
            if play.part not in parts:
                err(f"song[{s}].play[{k}].part", "unknown_part", f"no part {play.part!r}")
            elif parts[play.part].sample and parts[play.part].sample.mode == "clip":
                err(f"song[{s}].play[{k}].part", "clip_part_pattern", f"{play.part!r} places its sample as clips; leave it out of sections")
            pat = patterns.get(play.pattern)
            if not pat:
                err(f"song[{s}].play[{k}].pattern", "unknown_pattern", f"no pattern {play.pattern!r}")
            elif pat.part != play.part:
                err(f"song[{s}].play[{k}]", "pattern_part_mismatch", f"pattern {pat.id!r} belongs to part {pat.part!r}")
            used_parts.add(play.part)
            used_patterns.add(play.pattern)
    for i, part in enumerate(score.parts):
        if part.sample and part.sample.mode == "clip":
            sm = part.sample
            if sm.start_beat >= score.beats:
                err(f"parts[{i}].sample.start_beat", "sample_after_end", f"the song is {score.beats:g} beats")
            elif part.id in metas and not C.clip_layout(metas[part.id], sm, score.bpm, score.beats):
                err(f"parts[{i}].sample", "sample_too_short", "under 1/64 beat of it would play")
            continue
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

    notes = clips = 0
    if not errors:
        plan = C.compile(score, pal)
        notes = sum(len(t.notes) for t in plan.tracks)
        clips = sum(len(t.sample.clips) for t in plan.tracks if t.sample)
        if notes > MAX_NOTES:
            err("song", "too_many_notes", f"{notes} notes once patterns repeat; at most {MAX_NOTES}")
        if clips > MAX_CLIPS:
            err("parts", "too_many_clips", f"looped samples make {clips} clips; at most {MAX_CLIPS} (loop a longer stretch)")
        if notes == 0 and clips == 0:
            err("song", "no_notes", "nothing plays")
    return Result(not errors, errors, warnings, estimate(score, notes, clips) if not errors else None, score if not errors else None)
