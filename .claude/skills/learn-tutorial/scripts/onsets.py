"""Onsets per frequency band, as times and as beats, and per-16th hit strengths on a loop grid.

    run onsets.py WAV --bpm 123 --from 19.0 --to 26.0 --anchor 19.396
    run onsets.py WAV --bpm 123 --anchor 19.396 --grid --passes 1 --bands body=40-1500,hats=5000-16000
    run onsets.py WAV --bpm 123 --anchor 0 --grid --passes 2 --json analysis/perc_grid.json

List mode prints every onset in each band (default low 30-200 Hz, mid 400-3000, high 3000+):
time, beat from the anchor, position in the loop, jump (dB over the 'before' window) and level
(dBFS of the band just after it). Label every strong class you find (kick, clap, hats, bass), not
only the ones you expected: run 1 missed a backbeat clap that its own high band showed.

Grid mode reads each 16th (or --step) of the loop over --passes passes: the strongest jump within
+-25 ms of the grid point, its timing error, and the band's RMS over the 30 ms after it. A hit whose
low/body band leads its hats band by 10 dB or more is a body hit; hats lead or tie at hat
positions (run 1: +17..+28 dB at drum hits, -7..+1 dB at shaker/hat hits).

The detector is common.detect_onsets (energy jump, no frame offset); selftest.py checks its bias.
Without --anchor, beat 0 is the window start: find the loop start with anchor.py first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    HALF_MS,
    band,
    best_jump_near,
    detect_onsets,
    jump_curve,
    parse_band,
    position,
    read_audio,
    rms_db,
    write_json,
)


def band_onsets(x: np.ndarray, sr: int, spec: str, **kw) -> tuple[str, list[dict]]:
    name, lo, hi = parse_band(spec)
    kw.setdefault("half_ms", HALF_MS.get(name, 3.0))
    return name, detect_onsets(band(x, sr, lo, hi), sr, **kw)


def grid_strengths(x: np.ndarray, sr: int, spec: str, *, t0: float, bpm: float, loop_beats: float,
                   passes: int, step: float = 0.25, win_ms: float = 25.0) -> tuple[str, list[dict]]:
    """Per grid point: mean jump dB, mean level dBFS (30 ms after the onset), mean timing error."""
    name, lo, hi = parse_band(spec)
    y = band(x, sr, lo, hi)
    after, before = jump_curve(y, sr, HALF_MS.get(name, 3.0))
    spb = 60.0 / bpm
    rows = []
    for k in range(int(round(loop_beats / step))):
        beat = k * step
        jumps, levels, errs = [], [], []
        for p in range(passes):
            t = t0 + (p * loop_beats + beat) * spb
            ft, jdb, _ = best_jump_near(after, before, sr, t, win_ms)
            a = int(ft * sr)
            jumps.append(jdb)
            levels.append(rms_db(y[a:a + int(0.03 * sr)]))
            errs.append((ft - t) * 1000)
        rows.append({"beat": round(beat, 4), "jump_db": round(float(np.mean(jumps)), 1),
                     "level_db": round(float(np.mean(levels)), 1), "err_ms": round(float(np.median(errs)), 1)})
    return name, rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--from", dest="t_from", type=float, default=0.0, help="window start, s")
    ap.add_argument("--to", dest="t_to", type=float, default=None, help="window end, s")
    ap.add_argument("--anchor", type=float, default=None, help="time of beat 0, s (default: --from)")
    ap.add_argument("--loop-beats", type=float, default=8.0, help="loop length in beats (2 bars of 4/4 = 8)")
    ap.add_argument("--bands", default="low,mid,high", help="comma list: low|mid|high|full|NAME=LO-HI")
    ap.add_argument("--min-jump", type=float, default=6.0, help="dB")
    ap.add_argument("--floor", type=float, default=-45.0, help="dB under the band's loudest point")
    ap.add_argument("--min-gap", type=float, default=50.0, help="ms between onsets in one band")
    ap.add_argument("--grid", action="store_true", help="per-step strengths instead of an onset list")
    ap.add_argument("--passes", type=int, default=1, help="grid: loop passes to average")
    ap.add_argument("--step", type=float, default=0.25, help="grid: step in beats")
    ap.add_argument("--json", help="also write the result here")
    a = ap.parse_args()

    x, sr = read_audio(a.wav)
    anchor = a.t_from if a.anchor is None else a.anchor
    spb = 60.0 / a.bpm
    out = {"wav": a.wav, "sr": sr, "bpm": a.bpm, "anchor_s": anchor, "loop_beats": a.loop_beats, "bands": {}}
    specs = [s for s in a.bands.split(",") if s]

    if a.grid:
        for spec in specs:
            name, rows = grid_strengths(x, sr, spec, t0=anchor, bpm=a.bpm, loop_beats=a.loop_beats,
                                        passes=a.passes, step=a.step)
            out["bands"][name] = rows
        names = list(out["bands"])
        print(f"grid from {anchor:.3f} s, {a.passes} pass(es), {a.bpm} BPM; per band: jump dB / level dBFS")
        print("beat    pos      " + "".join(f"{n:>18s}" for n in names))
        for i, row in enumerate(out["bands"][names[0]]):
            cells = "".join(f"{out['bands'][n][i]['jump_db']:8.1f} /{out['bands'][n][i]['level_db']:7.1f} " for n in names)
            print(f"{row['beat']:6.2f}  {position(row['beat']):8s} {cells}")
    else:
        a0 = int(a.t_from * sr)
        a1 = len(x) if a.t_to is None else int(a.t_to * sr)
        seg = x[a0:a1]
        print(f"window {a.t_from:.3f}-{a1 / sr:.3f} s, {a.bpm} BPM, beat {spb:.4f} s, anchor {anchor:.3f} s")
        for spec in specs:
            name, ons = band_onsets(seg, sr, spec, min_jump_db=a.min_jump, floor_db=a.floor, min_gap_ms=a.min_gap)
            rows = []
            for o in ons:
                t = o["t"] + a.t_from
                b = (t - anchor) / spb
                rows.append({"t": round(t, 4), "beat": round(b, 3), "loop_beat": round(b % a.loop_beats, 3),
                             "jump_db": round(o["jump_db"], 1), "level_db": round(o["level_db"], 1)})
            out["bands"][name] = rows
            print(f"--- {name} ({spec}): {len(rows)} onsets")
            for r in rows:
                print(f"t {r['t']:9.3f}  beat {r['beat']:8.3f}  loop {r['loop_beat']:6.3f}  "
                      f"jump {r['jump_db']:5.1f} dB  level {r['level_db']:6.1f} dBFS")
    if a.json:
        write_json(a.json, out)


if __name__ == "__main__":
    main()
