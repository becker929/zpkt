#!/usr/bin/env python3
"""Stage 3: measure the pump.

The pump is the dip of the low band after each kick and its climb back before
the next one. Two numbers per track:

  pump_depth_db   how far the low band falls below its per-beat peak, median
                  over kick-on beats (0 = no pump)
  pump_return_ms  how long after the beat the low band is back within 3 dB of
                  the level it will reach just before the next beat

Method: the 60-150 Hz Hilbert envelope at 250 Hz (same as grid.py), folded
per beat with the tempo and phase grid.py locked. Within each beat, the kick
body is the first 90 ms; the rumble/bass level is read after that. The dip is
min(level after 90 ms) relative to the level at the end of the beat; the
return is the first frame after the dip within 3 dB of the end level.

    python3 analysis/pump.py corpus/wav               -> out/pump.json
    python3 analysis/pump.py --synth                  -> out/pump_synth.json (known ducking)
"""
import json, sys, glob, os
import numpy as np
from analysis import grid

KICK_MS = 90


def beat_curve(env_low, bpm, ph, kick_on_bars):
    beat = grid.FR * 60 / bpm
    nbeat = int(len(env_low) // beat)
    L = int(np.floor(beat))
    rows = []
    for b in range(nbeat):
        bar = int(b // 4)
        if bar >= len(kick_on_bars) or not kick_on_bars[bar]:
            continue
        s = int(round(ph + b * beat))
        if s + L > len(env_low): break
        seg = env_low[s:s + L]
        if seg.max() <= 0: continue
        rows.append(seg)
    if not rows:
        return None
    m = np.median(np.stack(rows), axis=0)
    return 10 * np.log10(m / (m.max() + 1e-12) + 1e-9)   # env is energy: 10 log10


def measure(curve_db, bpm):
    if curve_db is None: return dict(pump_depth_db=None, pump_return_ms=None)
    ms_per = 1000 / grid.FR
    k = int(KICK_MS / ms_per)
    if k >= len(curve_db) - 3: return dict(pump_depth_db=None, pump_return_ms=None)
    tail = curve_db[k:-5]   # drop the last 20 ms: the next kick's onset smears into it
    # the trough is the point with the biggest climb still to come after it;
    # a plain decay has no climb, so its depth is ~0 by construction
    later_max = np.maximum.accumulate(tail[::-1])[::-1]
    climb = later_max - tail
    i_min = int(climb.argmax()); depth = float(climb[i_min])
    after = tail[i_min:]
    back = np.where(after >= later_max[i_min] - 3.0)[0]
    ret = (k + i_min + int(back[0])) * ms_per if len(back) else None
    return dict(pump_depth_db=round(depth, 2), pump_return_ms=round(ret, 1) if ret is not None else None, curve_db=[round(float(v), 2) for v in curve_db])


def analyse_env(env, g):
    """Pump from envelopes already computed by grid.analyse (which now records the phase)."""
    c = beat_curve(env[1], g["tempo"], g["phase"], g["kick_on"])
    return measure(c, g["tempo"])


def analyse_file(path, g=None):
    import librosa
    y, _ = librosa.load(path, sr=grid.SR, mono=True)
    env, atk = grid.envelopes(y)
    if g is None:
        bpm0 = grid.coarse_tempo(y)
        _, bpm, ph = grid.lock(atk[0], bpm0)
        kick_on = [True] * 100000
    else:
        bpm, ph, kick_on = g["tempo"], g.get("phase", 0.0), g["kick_on"]
    c = beat_curve(env[1], bpm, ph, kick_on)
    r = dict(file=path, tempo=float(bpm)); r.update(measure(c, bpm)); return r


def synth_cases():
    """Loops where the ducking is known: rumble sidechained by the kick with
    different ducking times, and one loop with no sidechain at all."""
    from synth import engine as E
    import soundfile as sf
    os.makedirs("out/pump_synth", exist_ok=True)
    k = E.kick(); cases = []
    for duck in [None, 60, 120, 200, 300]:
        r = E.rumble(k, decay_ms=1200, sidechain_ms=0.001)  # long tail, no built-in duck
        tracks = {"kick": (k, [0, 4, 8, 12]), "rumble": (r, [0, 4, 8, 12]), "hat_closed": (E.hat(closed=True), [2, 6, 10, 14])}
        sc = {"rumble": ("kick", duck)} if duck else None
        mixed, _ = E.loop(150, 8, tracks=tracks, sidechain=sc)
        p = f"out/pump_synth/duck_{duck or 0}.wav"; sf.write(p, E.normalize(mixed), E.SR); cases.append((duck or 0, p))
    return cases


if __name__ == "__main__":
    if sys.argv[1:2] == ["--synth"]:
        out = []
        for duck, p in synth_cases():
            r = analyse_file(p); r["duck_ms"] = duck; out.append(r)
            print(f"duck {duck:4d} ms -> depth {r['pump_depth_db']} dB  return {r['pump_return_ms']} ms", file=sys.stderr)
        json.dump(out, open("out/pump_synth.json", "w"))
    else:
        src = sys.argv[1]; gj = sys.argv[2] if len(sys.argv) > 2 else "out/grid.json"
        byfile = {os.path.basename(g["file"]): g for g in json.load(open(gj))} if os.path.exists(gj) else {}
        out = []
        for f in sorted(glob.glob(os.path.join(src, "*.wav"))):
            r = analyse_file(f, byfile.get(os.path.basename(f))); out.append(r)
            print(f"{os.path.basename(f)[:40]:40s} depth {r['pump_depth_db']} dB return {r['pump_return_ms']} ms", file=sys.stderr, flush=True)
        json.dump(out, open("out/pump.json", "w"))
