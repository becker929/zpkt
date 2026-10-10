"""A/B every bar: two renders of the same section become one file.

Each is set to the same loudness (BS.1770 integrated, -14 LUFS, then one shared gain so the louder peak sits at
-1 dBFS at most), the first bar is dropped (it carries the previous pattern's tail), and bars alternate A, B, A, B
with 10 ms crossfades at every join. The result is what present_music's `ab` describes: bar length, bars, which side
starts, labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

TARGET_LUFS = -14.0
PEAK = 0.89                 # -1 dBFS
XF_S = 0.010


@dataclass
class AbFile:
    path: Path
    bar_seconds: float
    bars: int
    first: str
    every: int
    loudness: dict[str, float]          # each side's integrated loudness before matching (LUFS)

    def present(self, a: str, b: str) -> dict[str, Any]:
        """The `ab` argument for studio's present_music."""
        return {"bar_seconds": self.bar_seconds, "bars": self.bars, "first": self.first, "every": self.every,
                "a": a, "b": b}


def read(path: Path) -> tuple[Any, int]:
    import soundfile as sf
    x, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return x, sr


def integrated(x: Any, sr: int) -> float:
    import pyloudnorm
    return float(pyloudnorm.Meter(sr).integrated_loudness(x))


def build(a_path: Path, b_path: Path, out: Path, bar_seconds: float, *, first: str = "A", every: int = 1,
          drop_bars: int = 1, max_bars: int | None = None) -> AbFile:
    import numpy as np

    a, sr = read(a_path)
    b, sr_b = read(b_path)
    if sr != sr_b:
        raise ValueError(f"sample rates differ: {sr} and {sr_b}")
    bar = int(round(bar_seconds * sr))
    a, b = a[drop_bars * bar:], b[drop_bars * bar:]
    bars = min(len(a), len(b)) // bar
    if max_bars:
        bars = min(bars, max_bars)
    if bars < 2:
        raise ValueError(f"too short for an A/B: {bars} bar(s) of {bar_seconds} s after dropping {drop_bars}")
    a, b = a[:bars * bar], b[:bars * bar]
    la, lb = integrated(a, sr), integrated(b, sr)
    a = a * 10 ** ((TARGET_LUFS - la) / 20)
    b = b * 10 ** ((TARGET_LUFS - lb) / 20)
    peak = max(float(np.max(np.abs(a))), float(np.max(np.abs(b))))
    if peak > PEAK:
        a, b = a * PEAK / peak, b * PEAK / peak
    sides = {"A": a, "B": b}
    second = "B" if first == "A" else "A"
    xf = int(XF_S * sr)
    ramp = np.linspace(0.0, 1.0, xf)[:, None]
    y = np.zeros_like(a)
    for k in range(bars):
        src = sides[first if (k // every) % 2 == 0 else second]
        s, e = k * bar, (k + 1) * bar
        seg = src[s:min(e + xf, len(src))].copy()
        if k > 0:
            seg[:xf] *= ramp                              # fade in over the previous bar's fade out
        if e + xf <= len(src):
            seg[-xf:] *= ramp[::-1]
        y[s:s + len(seg)] += seg
    y[:xf] *= ramp
    y[-xf:] *= ramp[::-1]
    out.parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf
    sf.write(str(out), y.astype(np.float32), sr, subtype="PCM_24" if out.suffix == ".flac" else "FLOAT")
    return AbFile(out, round(bar / sr, 6), bars, first, every, {"A": round(la, 2), "B": round(lb, 2)})
