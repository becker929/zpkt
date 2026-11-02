"""compile(): a checked score becomes a Plan, the exact Live state to build, still as plain data.

Everything Live will see is decided here: track names (the booth's, never the score's text), absolute notes after
patterns repeat and the feel is applied, mixer values in dB, device settings in display units. live.py turns a Plan
into LOM calls; nothing in a Plan is a string from the score except palette ids already looked up.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .palette import Instrument, Palette
from .score import BEATS_PER_BAR, Score

HEADROOM_DB = -6.0   # every track starts here, so a full mix leaves the master chain room
TAIL_BARS = 1        # rendered after the song so reverb and echo ring out
SEND_OFF = 0.0


@dataclass
class TrackPlan:
    name: str                                # "p1".."p8": the booth's names
    instrument: Instrument
    notes: list[tuple[int, float, float, int]] = field(default_factory=list)   # (pitch, start, length, velocity)
    volume_db: float = HEADROOM_DB
    pan: float = 0.0
    room_db: float | None = None             # None: send off
    echo_db: float | None = None
    settings: dict[int, dict[str, Any]] = field(default_factory=dict)          # device index -> {param: display}


@dataclass
class Plan:
    bpm: float
    beats: float
    render_beats: float
    tracks: list[TrackPlan]
    returns: dict[int, dict[str, Any]]      # return track index -> settings for its device 0
    master_devices: tuple[str, ...]
    master_set: dict[int, dict[str, Any]]


def send_db(amount: float) -> float | None:
    """A send from 0..1: off at 0, else -36 dB to -6 dB."""
    return None if amount <= SEND_OFF else round(-36.0 + 30.0 * amount, 2)


def _feel(notes: list[tuple[int, float, float, int]], score: Score, salt: int) -> list[tuple[int, float, float, int]]:
    f = score.feel
    rng = random.Random(f.seed * 1009 + salt)
    beat_s = 60.0 / score.bpm
    out = []
    for p, t, d, v in notes:
        frac = round((t % 1.0) * 4, 6)
        if f.swing and frac in (1.0, 3.0):             # the off-beat 16ths
            t += f.swing * 0.25
        if f.humanize_ms:
            t += rng.gauss(0.0, f.humanize_ms / 1000.0) / beat_s
        if f.velocity_jitter:
            v += rng.randint(-f.velocity_jitter, f.velocity_jitter)
        out.append((p, max(0.0, round(t, 4)), d, min(127, max(1, v))))
    return out


def _dedupe(notes: list[tuple[int, float, float, int]]) -> list[tuple[int, float, float, int]]:
    """Live merges two notes on the same pitch and start: keep the louder (then the longer), as SH001 did."""
    best: dict[tuple[int, float], tuple[int, float, float, int]] = {}
    for n in notes:
        k = (n[0], n[1])
        if k not in best or (n[3], n[2]) > (best[k][3], best[k][2]):
            best[k] = n
    return sorted(best.values(), key=lambda n: (n[1], n[0]))


def compile(score: Score, pal: Palette) -> Plan:
    """Assumes check() passed (palette ids exist, patterns belong to their parts)."""
    patterns = {p.id: p for p in score.patterns}
    index = {p.id: k for k, p in enumerate(score.parts)}
    notes: dict[str, list] = {p.id: [] for p in score.parts}
    offset = 0.0
    for sec in score.song:
        end = offset + sec.bars * BEATS_PER_BAR
        for play in sec.play:
            pat = patterns[play.pattern]
            length = pat.bars * BEATS_PER_BAR
            start = offset
            while start < end:
                for n in pat.notes:
                    t = start + n.t
                    if n.t < length and t < end:
                        notes[play.part].append((n.p, round(t, 4), round(min(n.d, end - t), 4), n.v))
                start += length
        offset = end

    tracks = []
    for part in score.parts:
        inst = pal.instruments[part.instrument]
        settings = {k: dict(v) for k, v in inst.set.items()}
        for m in part.macros:
            mm = inst.macros[m.name]
            settings.setdefault(mm.device, {})[mm.param] = mm.display(m.value)
        tracks.append(TrackPlan(
            name=f"p{index[part.id] + 1}", instrument=inst,
            notes=_dedupe(_feel(notes[part.id], score, index[part.id])),
            volume_db=round(max(-70.0, min(6.0, HEADROOM_DB + inst.trim + part.gain_db)), 2),
            pan=part.pan, room_db=send_db(part.room), echo_db=send_db(part.echo), settings=settings,
        ))
    return Plan(
        bpm=score.bpm, beats=score.beats, render_beats=score.beats + TAIL_BARS * BEATS_PER_BAR, tracks=tracks,
        returns={pal.returns[name].track: pal.returns[name].settings[getattr(score.mix, name)] for name in ("room", "echo")},
        master_devices=pal.master_devices, master_set=pal.master_set,
    )
