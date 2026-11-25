"""Sum saved arrangements the way the page plays them and print the level above 6 kHz and 10 kHz for each 4 bars (the median bar
of the four).

    uv run --extra audio python contrib/arranger/measure.py short-8 short-8a ...     # arrangements by id
    uv run --extra audio python contrib/arranger/measure.py --clips                  # every clip on its own

Measured, not heard: it says where the top end rises, not whether the rise is the right one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

import hw002

DATA = hw002.DATA


class Loops:
    """loops.json and the clips' audio, read once each."""

    def __init__(self, data: Path) -> None:
        self.data = data
        self.index = json.loads((data / "loops.json").read_text())
        self.clips = {c["id"]: c for c in self.index["clips"]}
        self.rate = self.index["rate"]
        self.bar = round(self.index["barSeconds"] * self.rate)
        self._audio: dict[str, np.ndarray] = {}

    def audio(self, name: str) -> np.ndarray:
        if name not in self._audio:
            self._audio[name] = sf.read(self.data / "audio" / name, dtype="float32", always_2d=True)[0]
        return self._audio[name]


def render(arr: dict, loops: Loops) -> np.ndarray:
    """As scheduleBar in the page: loops by the bar, one-shots whole, a loop's tail when nothing follows it on its
    lane, and what rings past the end brought round to bar 1, as when the page loops."""
    bar = loops.bar
    n = arr["bars"] * bar
    out = np.zeros((n + 4 * bar, 2), dtype="float32")

    def add(x: np.ndarray, at: int) -> None:
        m = min(len(x), len(out) - at)
        out[at : at + m] += x[:m]

    for r in arr["regions"]:
        if r["lane"] in arr.get("mutes", []):
            continue
        c, at, end = loops.clips[r["clip"]], r["start"] * bar, (r["start"] + r["len"]) * bar
        a = loops.audio(c["file"])
        if c["kind"] == "once":
            add(a, at)
            continue
        for i in range(r["len"]):
            ph = (i + r.get("off", 0)) % c["bars"]
            add(a[ph * bar : (ph + 1) * bar], at + i * bar)
        follows = any(
            o["lane"] == r["lane"] and o["start"] == (r["start"] + r["len"]) % arr["bars"] for o in arr["regions"]
        )
        if c.get("tail") and not follows:
            add(loops.audio(c["tail"]), end)
    out[: len(out) - n] += out[n:]
    return out[:n]


def band_db(x: np.ndarray, lo: float, rate: int) -> float:
    """Level (dB re full scale, RMS) of everything above `lo` Hz."""
    m = x.mean(axis=1)
    p = np.abs(np.fft.rfft(m)) ** 2
    f = np.fft.rfftfreq(len(m), 1 / rate)
    return float(10 * np.log10(2 * p[f >= lo].sum() / len(m) ** 2 + 1e-12))


def clip_report(loops: Loops) -> list[str]:
    lines = []
    for c in loops.index["clips"]:
        a = loops.audio(c["file"])[: c["bars"] * loops.bar]
        lines.append(
            f"{c['id']:18s} {c['kind']:5s} {c['bars']:2d} bars   above 6 kHz {band_db(a, 6000, loops.rate):6.1f}"
            f"   above 10 kHz {band_db(a, 10000, loops.rate):6.1f}"
        )
    return lines


def arrangement_report(arr: dict, loops: Loops) -> list[str]:
    x = render(arr, loops)
    bars = [x[i * loops.bar : (i + 1) * loops.bar] for i in range(arr["bars"])]

    def row(lo: float) -> str:  # the median bar of each four, so one crash does not stand for its block
        v = [band_db(b, lo, loops.rate) for b in bars]
        return " ".join(f"{np.median(v[i : i + 4]):6.1f}" for i in range(0, len(v), 4))

    return [
        f"{arr['name']}   peak {np.abs(x).max():.2f}, samples over full scale {int((np.abs(x) > 1).sum())}",
        "  bars       " + " ".join(f"{i + 1:>3d}-{i + 4:<2d}" for i in range(0, arr["bars"], 4)),
        "  above 6k   " + row(6000),
        "  above 10k  " + row(10000),
        "  all        " + row(20),
    ]


def main(argv: list[str]) -> None:
    loops = Loops(DATA)
    if argv == ["--clips"]:
        print("\n".join(clip_report(loops)))
        return
    for key in argv:
        print("\n".join(arrangement_report(json.loads((DATA / "arrangements" / f"{key}.json").read_text()), loops)))


if __name__ == "__main__":
    main(sys.argv[1:])
