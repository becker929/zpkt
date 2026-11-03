"""compile(): a checked score becomes a Plan, the exact Live state to build, still as plain data.

Everything Live will see is decided here: track names (the booth's, never the score's text), absolute notes after
patterns repeat and the feel is applied, mixer values in dB, device settings in display units. live.py turns a Plan
into LOM calls; nothing in a Plan is a string from the score except palette ids already looked up, and sample ids,
which only ever reach Live as the booth's own path to its own file (samples.path).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from pathlib import Path

from . import samples as S
from .palette import Instrument, Palette
from .score import BEATS_PER_BAR, Part, Score

HEADROOM_DB = 0.0    # every track starts here; at -6 dB the first real render was -21.6 LUFS and never reached the limiter
TAIL_BARS = 1        # rendered after the song so reverb and echo ring out
SEND_OFF = 0.0


WARP_MODES = {"beats": 0, "complex": 4}     # Live's Clip.warp_mode: 0 Beats, 1 Tones, 2 Texture, 3 Re-Pitch, 4 Complex
PLAYBACK_MODES = {"one_shot": 1, "slices": 2}   # SimplerDevice.playback_mode: 0 Classic, 1 One-Shot, 2 Slicing
ONE_SHOT_ROOT = 60                          # Simpler plays its sample as recorded on C3
ONE_SHOT_RANGE = (24, 96)                   # four octaves down and three up from the root is enough to be music
SLICE_ROOT = 36                             # Simpler's first slice is on C1
MIN_CLIP_BEATS = 1 / 64                     # a copy shorter than this after the cut is left out


@dataclass
class SamplePlan:
    """A sample on a part's track: arrangement clips on an audio track (mode "clip"), or a Simpler on a MIDI track."""

    id: str
    path: Path                               # the booth's own file; the only path that reaches Live
    mode: str
    seconds: float
    frames: int
    warp: str = "off"
    fit_beats: float | None = None           # warped: the whole file spans this many beats
    transpose: int = 0
    natural_beats: float = 0.0               # one whole play of the file, in song beats
    clips: list[tuple[float, float]] = field(default_factory=list)   # (song beat, length in beats), one per copy
    slices: list[int] = field(default_factory=list)                  # slice starts in frames, after the first at 0

    def end_marker(self, beats: float, bpm: float) -> float:
        """A clip `beats` long ends here, in the clip's own units: beats when warped, file seconds when not (and a
        transposed unwarped clip plays its file faster or slower)."""
        if self.warp != "off":
            return round(beats, 6)
        return round(beats * 60.0 / bpm * 2 ** (self.transpose / 12), 6)


@dataclass
class TrackPlan:
    name: str                                # "p1".."p8": the booth's names
    instrument: Instrument | None
    notes: list[tuple[int, float, float, int]] = field(default_factory=list)   # (pitch, start, length, velocity)
    volume_db: float = HEADROOM_DB
    pan: float = 0.0
    room_db: float | None = None             # None: send off
    echo_db: float | None = None
    settings: dict[int, dict[str, Any]] = field(default_factory=dict)          # device index -> {param: display}
    sample: SamplePlan | None = None

    @property
    def kind(self) -> str:
        """The track Live needs: audio for clips, MIDI for an instrument or a Simpler."""
        return "audio" if self.sample and self.sample.mode == "clip" else "midi"

    @property
    def label(self) -> str:
        return self.instrument.id if self.instrument else f"sample {self.sample.mode.replace('_', '-')}"

    @property
    def range(self) -> tuple[int, int]:
        if self.instrument:
            return self.instrument.range
        return pitch_range(self.sample.mode, len(self.sample.slices) + 1)


@dataclass
class Plan:
    bpm: float
    beats: float
    render_beats: float
    tracks: list[TrackPlan]
    returns: dict[int, dict[str, Any]]      # return track index -> settings for its device 0
    master_devices: tuple[str, ...]
    master_set: dict[int, dict[str, Any]]
    master_gain_db: float = 6.0              # the Limiter's Input Gain the template starts with


def pitch_range(mode: str, slices: int = 0) -> tuple[int, int]:
    """The pitches a sample part's patterns may play."""
    if mode == "one_shot":
        return ONE_SHOT_RANGE
    if mode == "slices":
        return SLICE_ROOT, SLICE_ROOT + max(0, slices - 1)
    return 0, -1                             # clips play no notes


def natural_beats(meta: dict, sample, bpm: float) -> float:
    """One whole play of the file in song beats: fit_beats when warped (default: the nearest whole bars, at least
    one), else its seconds at the song's tempo, shorter or longer by the transpose."""
    beats = meta["seconds"] * bpm / 60.0
    if sample.warp != "off":
        return float(sample.fit_beats) if sample.fit_beats else float(max(1, round(beats / BEATS_PER_BAR)) * BEATS_PER_BAR)
    return beats / 2 ** (sample.transpose / 12)


def clip_layout(meta: dict, sample, bpm: float, song_beats: float) -> list[tuple[float, float]]:
    """Where a clip-mode sample's copies go: (song beat, length). Every copy ends by length_beats and by the song's
    end, so nothing but reverb and echo rings into the loop's seam."""
    nat = natural_beats(meta, sample, bpm)
    stop = min(song_beats, sample.start_beat + sample.length_beats) if sample.length_beats else song_beats
    out, at = [], float(sample.start_beat)
    while at < stop - 1e-9:
        length = min(nat, stop - at)
        if length >= MIN_CLIP_BEATS:
            out.append((round(at, 6), round(length, 6)))
        if not sample.loop:
            break
        at += nat
        if len(out) > 4096:                  # check() refuses past MAX_CLIPS; this only bounds the loop
            break
    return out


def sample_plan(part: Part, score: Score) -> SamplePlan:
    sm = part.sample
    meta = S.info(sm.id)
    sp = SamplePlan(id=sm.id, path=S.path(sm.id), mode=sm.mode, seconds=meta["seconds"], frames=meta["frames"])
    if sm.mode == "clip":
        sp.warp, sp.transpose = sm.warp, sm.transpose
        sp.fit_beats = natural_beats(meta, sm, score.bpm) if sm.warp != "off" else None
        sp.natural_beats = natural_beats(meta, sm, score.bpm)
        sp.clips = clip_layout(meta, sm, score.bpm, score.beats)
    elif sm.mode == "slices":
        sp.slices = [round(t * meta["sample_rate"]) for t in sm.slices if t > 0]
    return sp


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
        if part.sample:
            inst, sp, settings = None, sample_plan(part, score), {}
            trim = S.info(part.sample.id)["trim_db"]
        else:
            inst, sp = pal.instruments[part.instrument], None
            trim = inst.trim
            settings = {k: dict(v) for k, v in inst.set.items()}
            for m in part.macros:
                mm = inst.macros[m.name]
                settings.setdefault(mm.device, {})[mm.param] = mm.display(m.value)
        tracks.append(TrackPlan(
            name=f"p{index[part.id] + 1}", instrument=inst,
            notes=_dedupe(_feel(notes[part.id], score, index[part.id])),
            volume_db=round(max(-70.0, min(6.0, HEADROOM_DB + trim + part.gain_db)), 2),
            pan=part.pan, room_db=send_db(part.room), echo_db=send_db(part.echo), settings=settings, sample=sp,
        ))
    return Plan(
        bpm=score.bpm, beats=score.beats, render_beats=score.beats + TAIL_BARS * BEATS_PER_BAR, tracks=tracks,
        returns={pal.returns[name].track: pal.returns[name].settings[getattr(score.mix, name)] for name in ("room", "echo")},
        master_devices=pal.master_devices, master_set=pal.master_set,
        master_gain_db=_limiter_gain(pal),
    )


def _limiter_gain(pal: Palette) -> float:
    k = pal.master_devices.index("Limiter")
    return float(str(pal.master_set.get(k, {}).get("Input Gain", "0 dB")).split()[0])
