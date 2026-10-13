"""Options: a few plans baked in Live and cut into one file, so the phone can switch between them at once.

The phone fetches the file when the card arrives and decodes every option into memory. Moving the slider or
tapping an option then switches on the phone's own audio clock, with no request to the Mac. Only these options
exist; anything in between is a new bake.

- **slider**: one knob at N values (`hands plan slider`), or every knob moved together along the line from plan A
  to plan B (`hands plan line`). The options are ordered, so the phone shows a slider.
- **buttons**: any plans on one kit (`hands plan options`). They are unordered, so the phone shows one button each.

Baking goes through the Planner like any other plans. They are packed P to a Live pass and kept in the cache, so a
16-stop slider on a 16-pattern kit costs one load and one export, and options rendered before cost nothing.

The file puts the options end to end, `bars` bars each, starting after the first bar of each pattern (that bar
carries the previous pattern's tail). Each option is cut to loop: its first 10 ms crossfade from the audio after
its last bar into its own start, so its end flows into its start as it would in the set. `match_db` brings each
option to one loudness (BS.1770, -14 LUFS), less one shared offset so no option's peak passes -1 dBFS. The phone
plays the options at Live's own levels, or matched.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .abfile import TARGET_LUFS, integrated, read
from .model import KnobId, KnobInfo, Plan

XF_S = 0.010
PEAK_DB = -1.0
MAX_SECONDS = 135.0        # the phone keeps the file decoded: 135 s of stereo float at 48 kHz is ~52 MB
MAX_OPTIONS = 32
DEFAULT_BARS = 4


@dataclass
class Strip:
    path: Path
    bar_seconds: float
    bars: int                          # per option
    lufs: list[float | None]           # each option's integrated loudness as Live made it (None: silent)
    peak_db: list[float | None]
    match_db: list[float]              # the gain that matches it to the others

    def present(self, labels: list[str], *, layout: str, name: str, now: int | None) -> dict[str, Any]:
        """The `options` argument for studio's present_music."""
        return {"layout": layout, "name": name, "bar_seconds": self.bar_seconds, "bars": self.bars, "now": now,
                "options": [{"label": label, "match_db": m, "lufs": lu, "peak_db": pk}
                            for label, m, lu, pk in zip(labels, self.match_db, self.lufs, self.peak_db)]}


def fit_bars(n: int, bar_seconds: float, bars: int, pattern_bars: int, drop_bars: int = 1) -> int:
    """How many bars each option gets: at most what a pattern has after its first bar, and few enough that the whole
    file stays under MAX_SECONDS. Raises if even one bar each is too long."""
    if not 2 <= n <= MAX_OPTIONS:
        raise ValueError(f"between 2 and {MAX_OPTIONS} options, got {n}")
    bars = max(1, min(bars, pattern_bars - drop_bars))
    if n * bar_seconds > MAX_SECONDS:
        raise ValueError(f"{n} options of one {bar_seconds:.2f} s bar each pass {MAX_SECONDS:.0f} s; use fewer")
    return min(bars, int(MAX_SECONDS // (n * bar_seconds)))


def build(paths: list[Path], out: Path, bar_seconds: float, bars: int, *, drop_bars: int = 1) -> Strip:
    """Cut each render to `bars` bars after the first `drop_bars`, ready to loop, and put them end to end."""
    import numpy as np
    import soundfile as sf

    xs, rates = zip(*(read(p) for p in paths))
    if len(set(rates)) != 1:
        raise ValueError(f"sample rates differ: {sorted(set(rates))}")
    sr = rates[0]
    bar = int(round(bar_seconds * sr))
    length = bars * bar
    xf = int(XF_S * sr)
    ramp = np.linspace(0.0, 1.0, xf)[:, None]
    segs, lufs, peaks = [], [], []
    for p, x in zip(paths, xs):
        s, e = drop_bars * bar, drop_bars * bar + length
        if len(x) < e:
            raise ValueError(f"{p.name} is {len(x) / sr:.2f} s, shorter than {drop_bars} + {bars} bars")
        seg = x[s:e].copy()
        if len(x) >= e + xf:
            seg[:xf] = x[e:e + xf] * (1 - ramp) + seg[:xf] * ramp      # the loop's join: what follows, into the start
        else:
            seg[:xf] *= ramp
            seg[-xf:] *= ramp[::-1]
        segs.append(seg)
        loud = integrated(seg, sr)
        lufs.append(round(loud, 2) if math.isfinite(loud) else None)
        peak = float(np.max(np.abs(seg)))
        peaks.append(round(20 * math.log10(peak), 2) if peak > 0 else None)
    match = [TARGET_LUFS - lu if lu is not None else 0.0 for lu in lufs]
    over = max((pk + m for pk, m in zip(peaks, match) if pk is not None), default=PEAK_DB)
    shift = min(0.0, PEAK_DB - over)
    match = [round(m + shift, 2) for m in match]
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), np.concatenate(segs).astype(np.float32), sr, subtype="FLOAT")    # Live's levels, unclipped
    return Strip(out, round(bar / sr, 6), bars, lufs, peaks, match)


def strip_path(root: Path, keys: list[str], bars: int) -> Path:
    digest = hashlib.sha256(("|".join(keys) + f"|{bars}").encode()).hexdigest()[:16]
    return root / "options" / f"{digest}.wav"


# --- what the options are ------------------------------------------------------------------------------------------

def values(lo: float, hi: float, n: int, scale: str = "lin") -> list[float]:
    """n values from lo to hi, evenly spaced ("lin") or evenly spaced in ratio ("log", both ends above 0)."""
    if n < 2:
        raise ValueError("a slider needs at least 2 stops")
    if scale == "lin":
        return [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    if scale == "log":
        if lo <= 0 or hi <= 0:
            raise ValueError(f"a log slider needs both ends above 0, got {lo} and {hi}")
        return [lo * (hi / lo) ** (i / (n - 1)) for i in range(n)]
    raise ValueError(f"unknown scale {scale!r}: lin or log")


def label(v: float, info: KnobInfo, step: float) -> str:
    """A stop's value as the slider shows it: percent for 0-1 knobs, else the set's own units. Enough decimals
    that neighbouring stops read differently."""
    pct = info.lo == 0.0 and info.hi == 1.0
    shown, step = (v * 100, step * 100) if pct else (v, step)
    decimals = max(0, min(3, math.ceil(-math.log10(abs(step))) if step else 0))
    text = f"{shown:.{decimals}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text + ("%" if pct else "")


def knob_stops(base: Plan, knob: str, vals: list[float], info: KnobInfo) -> tuple[list[Plan], list[str], int | None]:
    """One plan per value of `knob`, every other knob as in `base`. Also the labels, and the stop nearest the value
    the knob has now (None when that is outside the range)."""
    param = KnobId.parse(knob).param.split("/")[-1]
    step = min((abs(b - a) for a, b in zip(vals, vals[1:])), default=0.0)
    labels = [label(v, info, step) for v in vals]
    plans = [Plan(base.kit, {**base.knobs, knob: v}, f"{param} {lab}") for v, lab in zip(vals, labels)]
    current = base.knobs.get(knob, info.base)
    lo, hi = min(vals), max(vals)
    now = None
    if lo - 1e-9 <= current <= hi + 1e-9:
        now = min(range(len(vals)), key=lambda i: abs(vals[i] - current))
    return plans, labels, now


def line_stops(a: Plan, b: Plan, n: int, info: dict[str, KnobInfo]) -> tuple[list[Plan], list[str]]:
    """n plans from A to B, every knob moved in step. Labels: A, the way along in percent, B."""
    if a.kit != b.kit:
        raise ValueError(f"A and B are on different kits: {a.kit}, {b.kit}")
    knobs = sorted(set(a.knobs) | set(b.knobs))
    if not knobs:
        raise ValueError("A and B set no knobs: there is no line between them")

    def at(p: Plan, k: str) -> float:
        return p.knobs.get(k, info[k].base if k in info else 0.0)

    plans, labels = [], []
    for i in range(n):
        t = i / (n - 1)
        lab = "A" if i == 0 else "B" if i == n - 1 else f"{t:.0%}"
        plans.append(Plan(a.kit, {k: at(a, k) + (at(b, k) - at(a, k)) * t for k in knobs}, f"{lab} of A to B"))
        labels.append(lab)
    return plans, labels
