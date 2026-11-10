#!/usr/bin/env python3
"""Stage 4: find bar one.

grid.py locks a beat grid (tempo, phase) but does not know which beat starts
the bar, nor which bar starts the phrase. This does both from novelty: in
techno, things change on the downbeat and, more so, at the start of an
eight-bar phrase (a kick drops out or returns, a hat pattern starts, a stab
enters). So:

  1. per-beat energy vector, six bands, log scale
  2. novelty per beat = distance between the mean of the 4 beats before and
     the 4 beats after (a change that lasts, not a fill)
  3. beat offset o in 0..3 = the one whose beats carry the most novelty,
     counted over the top 10% of novelty peaks; that is beat one
  4. bar offset in 0..7 likewise over bars: the phrase start
The strength of each vote (share of big changes landing on the winner versus
chance, 1/4 and 1/8) is returned so weak calls can be discounted.

Validation: python3 -m analysis.downbeat --synth renders an arrangement with
known bar lines, cuts a random number of beats off the front, and checks the
finder recovers the offset.
"""
import sys, json, numpy as np
from analysis import grid


def beat_energy(env, bpm, ph):
    beat = grid.FR * 60 / bpm
    n = int((env.shape[1] - ph) // beat)
    idx = np.floor((np.arange(env.shape[1]) - ph) / beat).astype(int)
    ok = (idx >= 0) & (idx < n)
    E = np.stack([np.bincount(idx[ok], weights=env[b][ok], minlength=n) for b in range(env.shape[0])])
    return np.log10(E / (E.max(axis=1, keepdims=True) + 1e-12) + 1e-4)   # 6 x n_beats


def novelty(E, w=4):
    """How much beat i differs from the w beats before it: peaks exactly on
    the first beat of a new section, and falls off over the beats after."""
    n = E.shape[1]; nov = np.zeros(n)
    for i in range(w, n):
        nov[i] = np.abs(E[:, i] - E[:, i - w:i].mean(axis=1)).sum()
    return nov


def peaks_of(nov, win, top):
    """Local maxima (no higher value within `win` either side) above the top-`top` level."""
    th = np.quantile(nov[nov > 0], 1 - top) if (nov > 0).sum() > 8 else np.inf
    out = []
    for i in range(win, len(nov) - win):
        if nov[i] >= th and nov[i] == nov[i - win:i + win + 1].max():
            out.append(i)
    return np.array(out, dtype=int)


def vote(nov, period, win, top, min_peaks=3):
    if len(nov) < 4 * period: return 0, 0.0
    peaks = peaks_of(nov, win, top)
    if len(peaks) < min_peaks: return 0, 0.0
    hist = np.bincount(peaks % period, weights=nov[peaks], minlength=period)
    o = int(hist.argmax()); share = float(hist[o] / (hist.sum() + 1e-12))
    return o, round(share * period, 2)   # 1.0 = chance, `period` = every big change on the winner


def find(env, bpm, ph):
    E = beat_energy(env, bpm, ph)
    nov_b = novelty(E, 4)
    o_beat, s_beat = vote(nov_b, 4, 3, 0.10)
    # bars from that downbeat, then phrase offset over bars
    nb = (E.shape[1] - o_beat) // 4
    Eb = E[:, o_beat:o_beat + nb * 4].reshape(6, nb, 4).mean(axis=2)
    nov_bar = novelty(Eb, 4)
    # sections are 4, 8 or 16 bars: settle the 4-bar group first, then which of its two 8-bar phases
    o4, s4 = vote(nov_bar, 4, 2, 0.20, 2)
    peaks = peaks_of(nov_bar, 2, 0.20)
    w8 = np.bincount(peaks % 8, weights=nov_bar[peaks], minlength=8) if len(peaks) else np.zeros(8)
    o_bar = o4 if w8[o4] >= w8[(o4 + 4) % 8] else (o4 + 4) % 8
    s8 = round(float(max(w8[o4], w8[(o4 + 4) % 8]) / (w8[o4] + w8[(o4 + 4) % 8] + 1e-12) * 2), 2) if len(peaks) else 0.0
    return dict(beat_one=o_beat, beat_one_strength=s_beat, group4_bar=o4, group4_strength=s4,
                phrase_bar=o_bar, phrase8_strength=s8, n_beats=int(E.shape[1]))


def _synth_arrangement(sr=44100):
    from synth import presets, engine as E
    parts = [("core", 8), ("full", 8), ("breakdown", 4), ("buildup", 1), ("drop", 8), ("core", 4), ("breakdown", 8), ("drop", 8)]
    out = []
    for v, bars in parts:
        m, _ = presets.hard_techno_bar(150, v)
        if v == "buildup": out.append(m)          # already 4 bars
        else:
            bar_n = int(round(16 * (60 / 150) / 4 * sr))
            out.append(np.tile(m[:bar_n], bars))
    return E.normalize(np.concatenate(out)), sr


if __name__ == "__main__":
    if sys.argv[1:2] == ["--synth"]:
        import librosa
        y, sr = _synth_arrangement()
        y = librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=grid.SR)
        beat_n = int(grid.SR * 60 / 150)
        ok = 0; trials = 12
        for cut in range(trials):
            yy = y[cut * beat_n:]
            env, atk = grid.envelopes(yy)
            _, bpm, ph = grid.lock(atk[0], 150.0)
            r = find(env, bpm, ph)
            # truth: the file's downbeats are at 4*k - cut beats (0.4 s each); map one onto the locked grid
            beat_fr = grid.FR * 60 / bpm
            k = 4 * ((cut + 3) // 4) - cut             # first downbeat at or after the file start, in beats
            t_fr = k * grid.SR * 60 / 150 / grid.FRAME  # frames at 250 Hz
            want = int(round((t_fr - ph) / beat_fr)) % 4
            phrase_k = (cut + 31) // 32 * 32 - cut      # first phrase (8-bar) start in beats
            want_bar = (int(round((phrase_k * grid.SR * 60 / 150 / grid.FRAME - ph) / beat_fr)) - r["beat_one"]) // 4 % 8
            good = r["beat_one"] == want; good_bar = r["phrase_bar"] % 4 == want_bar % 4
            ok += good
            print(f"cut {cut:2d} beats: beat_one {r['beat_one']} (want {want}) str {r['beat_one_strength']}  phrase_bar {r['phrase_bar']} (want {want_bar}) str4 {r['group4_strength']} str8 {r['phrase8_strength']} {'ok' if good else 'MISS'} {'ok4' if good_bar else 'MISS4'}")
        print(f"{ok}/{trials} downbeats right")
    else:
        print("use --synth, or call find(env,bpm,ph) from the pipeline")
