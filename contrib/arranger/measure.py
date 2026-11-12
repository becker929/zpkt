"""Sum saved arrangements the way the page plays them and print the level above 6 kHz and 10 kHz for each 4 bars (the median bar
of the four).

    uv run --project ears python contrib/arranger/measure.py short-8 short-8a ...     # arrangements by id
    uv run --project ears python contrib/arranger/measure.py --clips                  # every clip on its own

Measured, not heard: it says where the top end rises, not whether the rise is the right one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

DATA = Path("~/_agent_scratch/arranger").expanduser()
INDEX = json.loads((DATA / "loops.json").read_text())
CLIPS = {c["id"]: c for c in INDEX["clips"]}
RATE = INDEX["rate"]
BAR = round(INDEX["barSeconds"] * RATE)
_cache: dict[str, np.ndarray] = {}


def audio(name: str) -> np.ndarray:
    if name not in _cache:
        _cache[name] = sf.read(DATA / "audio" / name, dtype="float32", always_2d=True)[0]
    return _cache[name]


def render(arr: dict) -> np.ndarray:
    """As scheduleBar in the page: loops by the bar, one-shots whole, a loop's tail when nothing follows it on its lane."""
    n = arr["bars"] * BAR
    out = np.zeros((n + 4 * BAR, 2), dtype="float32")

    def add(x: np.ndarray, at: int) -> None:
        m = min(len(x), len(out) - at)
        out[at:at + m] += x[:m]

    for r in arr["regions"]:
        if r["lane"] in arr.get("mutes", []):
            continue
        c, at, end = CLIPS[r["clip"]], r["start"] * BAR, (r["start"] + r["len"]) * BAR
        a = audio(c["file"])
        if c["kind"] == "once":
            add(a, at)
            continue
        for i in range(r["len"]):
            ph = (i + r.get("off", 0)) % c["bars"]
            add(a[ph * BAR:(ph + 1) * BAR], at + i * BAR)
        follows = any(o["lane"] == r["lane"] and o["start"] == (r["start"] + r["len"]) % arr["bars"] for o in arr["regions"])
        if c.get("tail") and not follows:
            add(audio(c["tail"]), end)
    out[:len(out) - n] += out[n:]       # what rings past the end comes round to bar 1, as when the page loops
    return out[:n]


def band_db(x: np.ndarray, lo: float) -> float:
    """Level (dB re full scale, RMS) of everything above `lo` Hz."""
    m = x.mean(axis=1)
    p = np.abs(np.fft.rfft(m)) ** 2
    f = np.fft.rfftfreq(len(m), 1 / RATE)
    return float(10 * np.log10(2 * p[f >= lo].sum() / len(m) ** 2 + 1e-12))


def main() -> None:
    if sys.argv[1:] == ["--clips"]:
        for c in INDEX["clips"]:
            a = audio(c["file"])[:c["bars"] * BAR]
            print(f"{c['id']:18s} {c['kind']:5s} {c['bars']:2d} bars   above 6 kHz {band_db(a, 6000):6.1f}   above 10 kHz {band_db(a, 10000):6.1f}")
        return
    for key in sys.argv[1:]:
        arr = json.loads((DATA / "arrangements" / f"{key}.json").read_text())
        x = render(arr)
        bars = [x[i * BAR:(i + 1) * BAR] for i in range(arr["bars"])]

        def row(lo: float) -> str:   # the median bar of each four, so one crash does not stand for its block
            v = [band_db(b, lo) for b in bars]
            return " ".join(f"{np.median(v[i:i + 4]):6.1f}" for i in range(0, len(v), 4))

        print(f"{arr['name']}   peak {np.abs(x).max():.2f}, samples over full scale {int((np.abs(x) > 1).sum())}")
        print("  bars       " + " ".join(f"{i + 1:>3d}-{i + 4:<2d}" for i in range(0, arr["bars"], 4)))
        print("  above 6k   " + row(6000))
        print("  above 10k  " + row(10000))
        print("  all        " + row(20))


if __name__ == "__main__":
    main()
