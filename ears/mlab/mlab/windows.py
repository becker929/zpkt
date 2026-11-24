"""Windows: the stretches of a track that target and eqfit measure, placed in seconds from its drop.

A window is a name and a (start_s, end_s) span. The default layout is the one HW002 was tuned on: the build is the
16 bars before the drop and the drop is the 16 bars from it. Bar offsets from the drop place every window, so the
same layout fits a reference with its own drop time and tempo (references.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BARS = 16  # build and drop: 16 bars each
LAYOUT: dict[str, tuple[int, int]] = {"build": (-BARS, 0), "drop": (0, BARS)}  # bar offsets from the drop
MIN_BARS = 4  # a window clipped below 4 bars is skipped
MIN_SECONDS = 0.4  # and any window under one 400 ms loudness block
DEFAULT_DROP_S = 24.0  # HW002, the track this was built for: the drop is bar 17, at 24 s
DEFAULT_BAR_S = 1.5  # one bar of 4/4 at 160 BPM

Span = tuple[float, float]


def windows(
    drop_s: float, bar_s: float, layout: Mapping[str, tuple[float, float] | None] | None = None
) -> dict[str, Span]:
    """{name: (start_s, end_s)}: build = 16 bars before the drop, drop = 16 bars from it.

    `layout` adds or replaces windows as bar offsets from the drop, e.g.
    {"drop2": (16, 24)}; a value of None removes a default window."""
    lay: dict[str, tuple[float, float] | None] = dict(LAYOUT)
    lay.update(layout or {})
    return {k: (float(drop_s + v[0] * bar_s), float(drop_s + v[1] * bar_s)) for k, v in lay.items() if v is not None}


def segments(
    x: Any, sr: float, wins: Mapping[str, Span], bar_s: float | None = None
) -> tuple[dict[str, tuple[Span, Any]], dict[str, str]]:
    """Clip each window to the file. Returns ({name: (span, samples)}, {name: why skipped})."""
    dur = len(x) / sr
    min_s = max(MIN_BARS * bar_s if bar_s else 0.0, MIN_SECONDS)
    keep: dict[str, tuple[Span, Any]] = {}
    skipped: dict[str, str] = {}
    for name, (a, b) in wins.items():
        a2, b2 = max(0.0, float(a)), min(dur, float(b))
        if b2 - a2 < min_s - 1e-6:
            skipped[name] = f"{max(0.0, b2 - a2):.2f} s inside the file, needs {min_s:.2f} s" + (
                f" ({MIN_BARS} bars)" if bar_s else ""
            )
            continue
        keep[name] = ((a2, b2), x[round(a2 * sr) : round(b2 * sr)])
    return keep, skipped
