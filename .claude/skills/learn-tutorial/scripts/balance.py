"""Compare level balance between the tutorial's audio and a practice render, section by section.

    run balance.py --bpm 123 --beats 8 --names perc perc+bass bass+drums \\
        --ref src/audio16k.wav --ref-at 19.396 73.255 108.864 \\
        --render practice/renders/A_raw.wav --render-at 0 7.805 15.610

Use it for levels the screen never shows (a synth's output, a drum bus, clip gain): set them so
the render's section-to-section and band-to-band differences match the tutorial's. Both signals
are reduced to mono 16 kHz (the tutorial audio's format). For each section (one --beats-long
loop pass starting at its --at time) it reports band RMS in dB relative to the first section's
full-band RMS, and what each section adds over the previous one per band (power difference, so
"bass added over perc" in the sub band is the bass's own level). The last table is render minus
tutorial: the dB to move. Kits differ, so no setting matches every cell; fit the cells the
technique depends on and say which.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import band, read_audio, write_json

BANDS = {"full": (None, None), "sub<120": (None, 120.0), "120-1k": (120.0, 1000.0), "1k-4k": (1000.0, 4000.0),
         "4k+": (4000.0, None)}
SR = 16000


def mono16k(path: str) -> np.ndarray:
    from scipy import signal

    x, sr = read_audio(path)
    return x if sr == SR else signal.resample_poly(x, SR, sr)


def table(x: np.ndarray, ats: list[float], seconds: float) -> dict:
    n = int(round(seconds * SR))
    powers = {b: [float(np.mean(band(x, SR, lo, hi)[int(t * SR):int(t * SR) + n] ** 2)) for t in ats]
              for b, (lo, hi) in BANDS.items()}
    ref = powers["full"][0] + 1e-15
    rel = {b: [round(10 * np.log10(p / ref + 1e-15), 1) for p in ps] for b, ps in powers.items()}
    added = {b: [None] + [round(10 * np.log10((ps[i] - ps[i - 1]) / ref), 1) if ps[i] > ps[i - 1] else "-"
                          for i in range(1, len(ps))] for b, ps in powers.items()}
    return {"relative_db": rel, "added_db": added}


def show(title: str, names: list[str], t: dict) -> None:
    print(f"\n{title}")
    print(f"{'band':10s}" + "".join(f"{n:>22s}" for n in names))
    for b in BANDS:
        cells = "".join(f"{v:>10}" + (f" (+{a:>6})" if a is not None else " " * 10) + "  "
                        for v, a in zip(t["relative_db"][b], t["added_db"][b]))
        print(f"{b:10s}{cells}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--beats", type=float, default=8.0, help="section length measured, beats")
    ap.add_argument("--names", nargs="+", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ref-at", type=float, nargs="+", required=True)
    ap.add_argument("--render", required=True)
    ap.add_argument("--render-at", type=float, nargs="+", required=True)
    ap.add_argument("--json")
    a = ap.parse_args()
    if not (len(a.names) == len(a.ref_at) == len(a.render_at)):
        ap.error("--names, --ref-at and --render-at need the same count")
    secs = a.beats * 60 / a.bpm
    tut, ren = table(mono16k(a.ref), a.ref_at, secs), table(mono16k(a.render), a.render_at, secs)
    diff = {b: [round(r - t, 1) for r, t in zip(ren["relative_db"][b], tut["relative_db"][b])] for b in BANDS}
    show("tutorial: dB re its first section (in brackets: what the section adds over the previous)", a.names, tut)
    show("render", a.names, ren)
    print("\nrender minus tutorial, dB")
    for b in BANDS:
        print(f"{b:10s}" + "".join(f"{v:>22}" for v in diff[b]))
    if a.json:
        write_json(a.json, {"names": a.names, "tutorial": tut, "render": ren, "render_minus_tutorial": diff})


if __name__ == "__main__":
    main()
