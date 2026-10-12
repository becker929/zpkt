"""Pitch of short notes: the strongest spectral peaks just after each onset, with MIDI numbers,
cents and both note-name conventions (Live C3 = 60, scientific C4 = 60).

    run pitch.py WAV --at 75.10 75.71 76.33                     # times in s
    run pitch.py WAV --bpm 123 --t0 73.255 --beats 1.5 2.75 4.5  # beats from t0
    run pitch.py WAV --bpm 123 --t0 73.255 --beats 1.5 --minus 19.396   # subtract the perc-only pass
    run pitch.py WAV --at 75.10 --track                         # trajectory, 60 ms windows every 15 ms

--minus REF_T0 subtracts a gain-matched copy of the same loop position from a playback that has
no bass (the perc solo), so the bass stands alone (run 1's verifier trick). Without it, read pitch
only where no kick or other low source sounds. A note is marked "impure" when a second peak within
3 dB is not a harmonic: call that pitch approximate in the recipe.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import describe_hz, read_audio, write_json

NFFT = 1 << 16


def peaks(seg: np.ndarray, sr: int, fmin: float, fmax: float, n: int = 3) -> list[tuple[float, float]]:
    """Top n (Hz, dB re the top) peaks of a Hann-windowed, zero-padded spectrum, parabolic-refined."""
    if len(seg) < 64:
        return []
    c = np.zeros(max(NFFT, len(seg)))
    c[:len(seg)] = seg * np.hanning(len(seg))
    sp = np.abs(np.fft.rfft(c))
    fr = np.fft.rfftfreq(len(c), 1 / sr)
    lo, hi = np.searchsorted(fr, fmin), np.searchsorted(fr, fmax)
    db = 20 * np.log10(sp + 1e-12)
    cand = [k for k in range(max(lo, 1), min(hi, len(db) - 1)) if db[k] > db[k - 1] and db[k] >= db[k + 1]]
    cand = sorted(cand, key=lambda k: -db[k])[:n]
    out = []
    for k in cand:
        a, b, g = db[k - 1], db[k], db[k + 1]
        d = 0.5 * (a - g) / (a - 2 * b + g) if (a - 2 * b + g) != 0 else 0.0
        out.append((float(fr[k] + d * (fr[1] - fr[0])), float(b)))
    if not out:
        return []
    top = out[0][1]
    return [(f, round(v - top, 1)) for f, v in out]


def analyse(x: np.ndarray, sr: int, t: float, *, delay: float, win: float, fmin: float, fmax: float) -> dict:
    a = int((t + delay) * sr)
    pk = peaks(x[a:a + int(win * sr)], sr, fmin, fmax)
    if not pk:
        return {"t": round(t, 4), "peaks": []}
    f0 = pk[0][0]
    impure = any(dv > -3 and abs(f / f0 - round(f / f0)) > 0.06 for f, dv in pk[1:])
    return {"t": round(t, 4), **describe_hz(f0), "impure": bool(impure),
            "peaks": [{"hz": round(f, 1), "db": dv, **{k: v for k, v in describe_hz(f).items() if k in ("live", "sci", "cents")}}
                      for f, dv in pk]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--at", type=float, nargs="*", default=[], help="note times, s")
    ap.add_argument("--beats", type=float, nargs="*", default=[], help="note positions in beats from --t0")
    ap.add_argument("--bpm", type=float)
    ap.add_argument("--t0", type=float, default=0.0, help="time of beat 0, s")
    ap.add_argument("--minus", type=float, help="time of beat 0 of a pass without the note's source")
    ap.add_argument("--loop-beats", type=float, default=8.0, help="with --minus: loop length to gain-match")
    ap.add_argument("--delay", type=float, default=0.01, help="skip the attack, s")
    ap.add_argument("--win", type=float, default=0.12, help="analysis window, s")
    ap.add_argument("--fmin", type=float, default=25.0)
    ap.add_argument("--fmax", type=float, default=400.0)
    ap.add_argument("--track", action="store_true", help="60 ms windows every 15 ms over 250 ms")
    ap.add_argument("--json")
    a = ap.parse_args()

    x, sr = read_audio(a.wav)
    times = list(a.at)
    if a.beats:
        if not a.bpm:
            ap.error("--beats needs --bpm")
        times += [a.t0 + b * 60 / a.bpm for b in a.beats]
    if a.minus is not None:
        if not a.bpm:
            ap.error("--minus needs --bpm")
        n = int(round(a.loop_beats * 60 / a.bpm * sr))
        m0, r0 = int(round(a.t0 * sr)), int(round(a.minus * sr))
        mix, ref = x[m0:m0 + n].copy(), x[r0:r0 + n]
        g = float(ref @ mix / (ref @ ref + 1e-12))
        x = np.zeros_like(x)
        x[m0:m0 + n] = mix - g * ref
        print(f"residual: loop at {a.t0:.3f} s minus {g:.3f} x loop at {a.minus:.3f} s")
    results = []
    for t in times:
        if a.track:
            steps = [analyse(x, sr, t, delay=ms / 1000, win=0.06, fmin=a.fmin, fmax=a.fmax) | {"offset_ms": ms}
                     for ms in range(0, 251, 15)]
            results.append({"t": round(t, 4), "track": steps})
            print(f"--- {t:.3f} s")
            for s in steps:
                if s["peaks"]:
                    print(f"  +{s['offset_ms']:3d} ms  {s['hz']:7.1f} Hz  {s['sci']:>4s} (Live {s['live']:>4s}) {s['cents']:+4d} c")
            continue
        r = analyse(x, sr, t, delay=a.delay, win=a.win, fmin=a.fmin, fmax=a.fmax)
        results.append(r)
        if not r["peaks"]:
            print(f"{t:9.3f} s  no peak")
            continue
        others = "  ".join(f"{p['hz']:.1f} Hz {p['db']:+.0f} dB" for p in r["peaks"][1:])
        flag = "  IMPURE (approximate)" if r["impure"] else ""
        print(f"{t:9.3f} s  {r['hz']:7.1f} Hz  MIDI {r['midi']:3d}  {r['sci']:>4s} sci / {r['live']:>4s} Live  "
              f"{r['cents']:+4d} c   next: {others}{flag}")
    if a.json:
        write_json(a.json, {"wav": a.wav, "notes": results})


if __name__ == "__main__":
    main()
