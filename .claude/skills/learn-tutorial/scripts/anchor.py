"""Find where a loop starts in the audio, and where its other playbacks line up.

    run anchor.py WAV --bpm 123 --start-near 19.4                       # playback start (first sound)
    run anchor.py WAV --bpm 123 --ref 19.396 --align 73.2 77.1          # same loop elsewhere, to the sample
    run anchor.py WAV --bpm 123 --ref 73.255 --align 108.8 --band low   # align on the bass only
    run anchor.py WAV --bpm 123 --ref 19.396 --period                   # pass 2 vs pass 1: real loop length

A DAW loop repeats sample for sample, so cross-correlating one pass against another is a better
anchor than the first onset (run 1: onset anchors were off by 0.14-0.2 beat; correlation got the
loop start to the millisecond). Fix beat 0 once, on the kick of a playback with drums
(--start-near T --band low): the first sound of a playback can be a mouse or key click (run 1: a
loud click 57 ms before the loop). Then --align every other playback to it. --band restricts the
match to what two playbacks share (perc solo vs perc + bass: full; perc + bass vs bass + drums: low).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import band, detect_onsets, parse_band, read_audio, write_json


def align(x: np.ndarray, sr: int, ref_t: float, near_t: float, n: int, search_s: float) -> dict:
    """The time near near_t where x best matches the n samples at ref_t (normalised correlation)."""
    from scipy import signal

    r0 = int(round(ref_t * sr))
    ref = x[r0:r0 + n]
    s = int(search_s * sr)
    c0 = max(0, int(round(near_t * sr)) - s)
    cand = x[c0:c0 + n + 2 * s]
    if len(cand) < n or len(ref) < n:
        raise SystemExit(f"segment at {near_t} s runs past the file")
    xc = signal.correlate(cand, ref, mode="valid", method="fft")
    e = np.concatenate([[0.0], np.cumsum(cand * cand)])
    norm = np.sqrt((e[n:n + len(xc)] - e[:len(xc)]) * (ref @ ref)) + 1e-12
    nc = xc / norm
    k = int(np.argmax(nc))
    d = 0.0
    if 0 < k < len(nc) - 1:
        a, b, g = nc[k - 1], nc[k], nc[k + 1]
        d = 0.5 * (a - g) / (a - 2 * b + g) if (a - 2 * b + g) != 0 else 0.0
    t = (c0 + k + d) / sr
    seg = x[c0 + k:c0 + k + n]
    gain = float(seg @ ref / (ref @ ref + 1e-12))
    return {"near": near_t, "t": round(t, 4), "corr": round(float(nc[k]), 3), "gain_vs_ref": round(gain, 3)}


def start_near(x: np.ndarray, sr: int, t: float, search_s: float) -> dict:
    """The strongest energy jump within +-search_s of t (x already band-passed if wanted)."""
    a = max(0, int((t - search_s) * sr))
    seg = x[a:int((t + search_s) * sr)]
    ons = detect_onsets(seg, sr, half_ms=5.0, min_jump_db=10.0, floor_db=-50.0)
    if not ons:
        raise SystemExit(f"no onset within {search_s} s of {t}")
    best = max(ons, key=lambda o: o["jump_db"])
    return {"near": t, "t": round(a / sr + best["t"], 4), "jump_db": round(best["jump_db"], 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--loop-beats", type=float, default=8.0)
    ap.add_argument("--start-near", type=float, help="approximate playback start, s")
    ap.add_argument("--ref", type=float, help="loop start of the reference pass, s")
    ap.add_argument("--align", type=float, nargs="*", default=[], help="approximate starts of other passes, s")
    ap.add_argument("--period", action="store_true", help="measure the loop length from the next pass")
    ap.add_argument("--band", default="full", help="low|mid|high|full|NAME=LO-HI: match on this band")
    ap.add_argument("--search", type=float, default=0.3, help="+- search, s")
    ap.add_argument("--json")
    a = ap.parse_args()

    x, sr = read_audio(a.wav)
    loop_s = a.loop_beats * 60 / a.bpm
    out: dict = {"wav": a.wav, "bpm": a.bpm, "band": a.band, "loop_s": round(loop_s, 4)}
    _, lo, hi = parse_band(a.band)
    y = band(x, sr, lo, hi)
    if a.start_near is not None:
        out["start"] = start_near(y, sr, a.start_near, a.search)
        print(f"strongest {a.band}-band onset near {a.start_near}: {out['start']['t']:.4f} s "
              f"(jump {out['start']['jump_db']} dB)")
    if a.ref is not None:
        n = int(round(loop_s * sr))
        out["ref"] = a.ref
        out["aligned"] = [align(y, sr, a.ref, t, n, a.search) for t in a.align]
        for r in out["aligned"]:
            print(f"pass near {r['near']}: {r['t']:.4f} s  corr {r['corr']}  gain vs ref {r['gain_vs_ref']}  "
                  f"({(r['t'] - a.ref) / loop_s:.3f} loops after ref)")
        if a.period:
            p = align(y, sr, a.ref, a.ref + loop_s, n, min(a.search, 0.1))
            out["period_s"] = round(p["t"] - a.ref, 4)
            out["period_bpm"] = round(a.loop_beats * 60 / (p["t"] - a.ref), 3)
            print(f"next pass at {p['t']:.4f} s: loop {out['period_s']} s = {out['period_bpm']} BPM (corr {p['corr']})")
    if a.json:
        write_json(a.json, out)


if __name__ == "__main__":
    main()
