#!/usr/bin/env python3
"""Where each band's energy and attacks sit in the bar, and when the kick is off.

Per track:
  1. six time-domain band envelopes at 250 Hz (RMS in 4 ms frames), so a
     kick's attack stays inside one 16th-step instead of smearing across it
  2. an "attack" envelope per band: the half-wave rectified rise of the log
     envelope -- transients, not sustained energy
  3. tempo: a coarse estimate refined so the low-band (60-150 Hz) attacks fold
     as sharply as possible onto a beat grid; phase likewise
  4. two 6 x 16 profiles: where each band's ENERGY sits, and where its
     ATTACKS sit, folded over all bars
  5. kick-on / kick-off bars from per-bar low energy; runs; returns; and how
     consistent the return bars are modulo 8 and 16
Writes out/grid.json.   python3 analysis/grid.py corpus/wav
"""
import json, sys, glob, os
import numpy as np, librosa
from scipy.signal import butter, sosfiltfilt

BANDS = [("sub", 20, 60), ("low", 60, 150), ("lowmid", 150, 400), ("mid", 400, 2000), ("high", 2000, 6000), ("air", 6000, 10500)]
SR = 22050
FR = 250.0
FRAME = int(SR / FR)


def envelopes(y):
    """Hilbert envelopes per band, smoothed, at 250 Hz -- plus an attack track.

    A short RMS window wobbles at twice the band frequency on low bands, which
    made every half-cycle look like an onset. The analytic-signal envelope is
    instantaneous; a light low-pass then keeps the onset shape and drops the
    ripple. Attacks are rises of the log envelope steeper than 2 dB per frame.
    """
    from scipy.signal import hilbert
    from scipy.fft import next_fast_len
    n = len(y) // FRAME
    env = np.zeros((6, n)); atk = np.zeros((6, n))
    N = next_fast_len(len(y))   # hilbert is an FFT; an awkward length made some tracks take minutes
    for i, (_, lo, hi) in enumerate(BANDS):
        sos = butter(4, [lo, min(hi, SR / 2 - 1)], "bandpass", fs=SR, output="sos")
        b = sosfiltfilt(sos, y)
        e = np.abs(hilbert(b, N=N)[: len(b)])
        del b
        # smooth: ~one cycle of the band's low edge, never below 4 ms nor above 25 ms
        cut = float(np.clip(lo, 40, 250))
        e = sosfiltfilt(butter(2, cut, "low", fs=SR, output="sos"), e)
        e = np.clip(e, 1e-7, None)[: n * FRAME].reshape(n, FRAME).mean(axis=1)
        env[i] = e ** 2
        le = 20 * np.log10(e)
        d = np.diff(le, prepend=le[0])
        atk[i] = np.where(d > 2.0, d, 0.0)
    env /= env.max(axis=1, keepdims=True) + 1e-12
    atk /= atk.max(axis=1, keepdims=True) + 1e-12
    return env, atk


def coarse_tempo(y):
    oenv = librosa.onset.onset_strength(y=y, sr=SR)
    t, _ = librosa.beat.beat_track(onset_envelope=oenv, sr=SR, start_bpm=150, tightness=400)
    t = float(np.atleast_1d(t)[0])
    while t < 125: t *= 2
    while t > 180: t /= 2
    return t


def fold(sig, bpm, ph):
    step = FR * 60 / bpm / 4
    idx = (np.arange(len(sig)) - ph) / step
    ok = idx >= 0
    bins = np.floor(idx[ok]).astype(int) % 16
    p = np.bincount(bins, weights=sig[ok], minlength=16)
    return p / (p.sum() + 1e-12)


def lock(sig, bpm0):
    best = (-1, bpm0, 0.0)
    for bpm in np.linspace(bpm0 * 0.97, bpm0 * 1.03, 481):
        beat = FR * 60 / bpm
        for ph in np.linspace(0, beat, 16, endpoint=False):
            s = fold(sig, bpm, ph)[[0, 4, 8, 12]].sum()
            if s > best[0]: best = (s, bpm, ph)
    s0, b0, p0 = best
    for bpm in np.linspace(b0 * 0.9997, b0 * 1.0003, 61):
        beat = FR * 60 / bpm
        for ph in np.linspace(p0 - beat / 16, p0 + beat / 16, 17):
            s = fold(sig, bpm, ph)[[0, 4, 8, 12]].sum()
            if s > best[0]: best = (s, bpm, ph)
    return best


def analyse(path, y=None, env=None, atk=None):
    if y is None:
        y, _ = librosa.load(path, sr=SR, mono=True)
    if env is None:
        env, atk = envelopes(y)
    lowatk = atk[0]   # the sub band: where the kick body sits and nothing else rises sharply
    bpm0 = coarse_tempo(y)
    score, bpm, ph = lock(lowatk, bpm0)
    step = FR * 60 / bpm / 4
    n = env.shape[1]
    idx = (np.arange(n) - ph) / step
    ok = idx >= 0
    bins = np.floor(idx[ok]).astype(int) % 16
    bar_of = np.floor(idx[ok] / 16).astype(int)
    prof_e = [(lambda p: (p / (p.sum() + 1e-12)).tolist())(np.bincount(bins, weights=env[b][ok], minlength=16)) for b in range(6)]
    prof_a = [(lambda p: (p / (p.sum() + 1e-12)).tolist())(np.bincount(bins, weights=atk[b][ok], minlength=16)) for b in range(6)]
    nb = int(bar_of.max()) + 1
    cnt = np.bincount(bar_of, minlength=nb).clip(1)
    bar_low = np.bincount(bar_of, weights=env[1][ok], minlength=nb) / cnt
    ref = np.percentile(bar_low, 90) + 1e-12
    kick_on = (bar_low / ref) > 0.3
    if nb > 2: kick_on[0] = kick_on[1]; kick_on[-1] = kick_on[-2]
    runs, i = [], 0
    while i < nb:
        j = i
        while j < nb and kick_on[j] == kick_on[i]: j += 1
        runs.append((bool(kick_on[i]), i, j)); i = j
    offruns = [(s, e) for on, s, e in runs if not on and e - s >= 2]
    returns = [e for s, e in offruns if e < nb]
    def consistency(mod):
        if len(returns) < 2: return None
        _, c = np.unique(np.array(returns) % mod, return_counts=True)
        return float(c.max() / len(returns))
    bar_matrix = np.stack([np.bincount(bar_of, weights=env[b][ok], minlength=nb) / cnt for b in range(6)])
    return {
        "file": path, "tempo_coarse": round(bpm0, 2), "tempo": round(float(bpm), 3), "phase": round(float(ph), 3), "lock": round(float(score), 3),
        "n_bars": int(nb), "profile_energy": prof_e, "profile_attack": prof_a,
        "bar_low": bar_low.tolist(), "kick_on": kick_on.tolist(), "kick_off_runs": offruns,
        "longest_off_bars": max([e - s for s, e in offruns], default=0), "kick_off_share": round(float((~kick_on).sum() / nb), 3),
        "returns": returns, "return_consistency_mod8": consistency(8), "return_consistency_mod16": consistency(16),
        "bar_matrix": bar_matrix.round(4).tolist(),
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "corpus/wav"
    files = sorted(glob.glob(os.path.join(src, "*.wav"))) if os.path.isdir(src) else [src]
    out = []
    for f in files:
        r = analyse(f); out.append(r)
        print(f"{os.path.basename(f)[:40]:40s} bpm {r['tempo_coarse']:6.1f}->{r['tempo']:8.3f} lock {r['lock']:.2f} bars {r['n_bars']:4d} off {r['kick_off_share']:.2f} longest {r['longest_off_bars']:3d}", file=sys.stderr, flush=True)
    json.dump(out, open("out/grid.json", "w"))
    print(f"wrote out/grid.json ({len(out)} tracks)", file=sys.stderr)
