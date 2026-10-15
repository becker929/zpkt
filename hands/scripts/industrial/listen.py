"""Measure a render of the industrial short: loudness per bar, the band balance per section, against references.

  cd hands && uv run python scripts/industrial/listen.py RENDER.wav [--refs]
  cd hands && uv run python scripts/industrial/listen.py kick RENDER.wav ...      # the kick's profile vs the refs

Bands are third-octave sums grouped as sub (<60 Hz), low (60-150), low-mid (150-500), mid (500-2k), presence (2-6k),
air (>6k), each in dB relative to the section's total, so the balance compares across levels. A reference's "drop"
is its loudest 16 bars (by RMS over a sliding window at its own tempo, 4-beat bars assumed).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
import parts as P  # noqa: E402

BANDS = [("sub", 20, 60), ("low", 60, 150), ("lowmid", 150, 500), ("mid", 500, 2000), ("pres", 2000, 6000),
         ("air", 6000, 16000)]
REFS = Path("~/_agent_scratch/refs/HW002").expanduser()


def mono(path):
    x, sr = sf.read(path, always_2d=True)
    return x.mean(1), sr


def balance(x, sr) -> dict:
    n = 1 << 15
    S = np.zeros(n // 2 + 1)
    for k in range(0, len(x) - n, n // 2):
        S += np.abs(np.fft.rfft(x[k:k + n] * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    tot = S[(f > 20) & (f < 16000)].sum()
    return {name: 10 * np.log10(S[(f >= lo) & (f < hi)].sum() / tot + 1e-12) for name, lo, hi in BANDS}


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def show(label, b):
    print(f"{label:28s} " + "  ".join(f"{k} {v:6.1f}" for k, v in b.items()))


def main() -> None:
    x, sr = mono(sys.argv[1])
    spb = 60.0 / P.BPM
    bar = int(4 * spb * sr)
    print("bar dB (RMS):", " ".join(f"{rms_db(x[i * bar:(i + 1) * bar]):.0f}" for i in range(P.BARS)))
    for name, (a, b) in (("intro", P.INTRO), ("build", P.BUILD), ("break", P.BREAK), ("drop", P.DROP)):
        seg = x[a * bar:b * bar]
        show(f"{name} ({rms_db(seg):.1f} dB)", balance(seg, sr))
    if "--refs" in sys.argv:
        for ref in sorted(REFS.glob("*.wav")):
            r, rsr = mono(ref)
            win = int(16 * 4 * 60 / 150 * rsr)                 # ~16 bars near 150
            hop = rsr
            best = max(range(0, max(1, len(r) - win), hop), key=lambda k: np.mean(r[k:k + win:16] ** 2))
            seg = r[best:best + win]
            show(f"{ref.stem[:20]} ({rms_db(seg):.1f})", balance(seg, rsr))




# ---- the kick, heard from the mix ---------------------------------------------------------------------------------------
KICK_BANDS = [("sub 40-80", 40, 80), ("body 80-200", 80, 200), ("box 200-500", 200, 500), ("mid 0.5-1.5k", 500, 1500),
              ("bite 1.5-4k", 1500, 4000), ("fizz 4-10k", 4000, 10000)]


def kick_onsets(x, sr, bpm: float | None = None) -> list[int]:
    """Kick hits: peaks of the 40-120 Hz envelope's rise, at least 0.3 beat apart."""
    from numpy.fft import irfft, rfft
    n = len(x)
    X = rfft(x)
    f = np.fft.rfftfreq(n, 1 / sr)
    low = irfft(X * ((f > 40) & (f < 120)), n)
    hop = int(0.005 * sr)
    env = np.sqrt(np.convolve(low ** 2, np.ones(hop) / hop, "same"))[::hop]
    rise = np.maximum(np.diff(env, prepend=env[0]), 0)
    gap = int((60 / (bpm or 150) * 0.6) / 0.005)
    thr = np.percentile(rise, 99) * 0.25
    out = []
    for i in np.argsort(-rise):
        if rise[i] < thr:
            break
        if all(abs(i - j) > gap for j in out):
            out.append(i)
    return sorted(k * hop for k in out)


def kick_profile(x, sr, onsets, win_s: float = 0.06) -> dict:
    """What the kick adds, heard from the mix: per band, the dB the 60 ms after each hit stand above the 60 ms just
    before it (the last kick's tail, rumble, bass, hats); 'flat' is the hit's spectral flatness 1-8 kHz (dB, nearer
    0 = noisier, harsher); 'mid' is the hit's 0.5-4 kHz share of its own energy (dB)."""
    n = int(win_s * sr)
    N = 1 << int(np.ceil(np.log2(n)))
    on, pre = np.zeros(N // 2 + 1), np.zeros(N // 2 + 1)
    hits = 0
    for o in onsets:
        a, b = x[o:o + n], x[o - n - int(0.005 * sr):o - int(0.005 * sr)]
        if len(a) < n or len(b) < n:
            continue
        on += np.abs(np.fft.rfft(a * np.hanning(n), N)) ** 2
        pre += np.abs(np.fft.rfft(b * np.hanning(n), N)) ** 2
        hits += 1
    f = np.fft.rfftfreq(N, 1 / sr)
    out = {}
    for name, lo, hi in KICK_BANDS:
        m = (f >= lo) & (f < hi)
        out[name] = 10 * np.log10(on[m].sum() / (pre[m].sum() + 1e-20) + 1e-20)
    h = on[(f > 1000) & (f < 8000)] + 1e-20
    out["flat"] = 10 * np.log10(np.exp(np.mean(np.log(h))) / np.mean(h))
    out["mid"] = 10 * np.log10(on[(f >= 500) & (f < 4000)].sum() / (on[(f >= 30) & (f < 16000)].sum() + 1e-20))
    out["hits"] = hits
    return out


def show_kick(label, k):
    print(f"{label:30s} rise " + " ".join(f"{n.split()[0]} {k[n]:5.1f}" for n, _, _ in KICK_BANDS)
          + f" | mid share {k['mid']:6.1f}  flat {k['flat']:5.1f}  ({k['hits']} hits)")


def kicks(paths: list[str]) -> None:
    """The kick, heard from each mix (drop only for our renders: bars 16-24), against the references' loudest stretch."""
    for p in paths:
        x, sr = mono(p)
        bar = int(4 * 60 / P.BPM * sr)
        a, b = P.DROP
        seg = x[a * bar:b * bar]
        show_kick(Path(p).stem[:30], kick_profile(seg, sr, kick_onsets(seg, sr, P.BPM)))
    for ref in sorted(REFS.glob("*.wav")):
        r, rsr = mono(ref)
        win = int(16 * 4 * 60 / 150 * rsr)
        best = max(range(0, max(1, len(r) - win), rsr), key=lambda k: np.mean(r[k:k + win:16] ** 2))
        seg = r[best:best + win]
        show_kick(ref.stem[:30], kick_profile(seg, rsr, kick_onsets(seg, rsr)))



THIRDS = [25 * 2 ** (k / 3) for k in range(28)]          # 25 Hz .. ~16 kHz


def third_octaves(x, sr) -> np.ndarray:
    n = 1 << 15
    S = np.zeros(n // 2 + 1)
    for k in range(0, len(x) - n, n // 2):
        S += np.abs(np.fft.rfft(x[k:k + n] * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    e = np.array([S[(f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))].sum() for c in THIRDS])
    return 10 * np.log10(e / e.sum() + 1e-12)


def kick_alone(r, sr, bpm: float = 150.0, bars: int = 2) -> np.ndarray:
    """The reference's loudest-kick stretch where little else plays: windows of `bars` bars, scored by low-band
    level minus how much sits above 2 kHz (hats, synths)."""
    win = int(bars * 4 * 60 / bpm * sr)
    best, score = 0, -1e9
    for k in range(0, len(r) - win, win // 4):
        seg = r[k:k + win]
        S = np.abs(np.fft.rfft(seg[::4])) ** 2
        f = np.fft.rfftfreq(len(seg[::4]), 4 / sr)
        low, high, tot = S[(f > 40) & (f < 150)].sum(), S[f > 2000].sum(), S.sum() + 1e-20
        sc = 10 * np.log10(low / tot) - 10 * np.log10(high / tot) + 0.3 * rms_db(seg)
        if sc > score:
            best, score = k, sc
    return r[best:best + win], best / sr


def kick_shapes(paths: list[str]) -> None:
    """Third-octave shape (dB of total) of our kick stems against the references' kick-alone bars, grouped."""
    groups = [("sub <63", 25, 63), ("body 63-160", 63, 160), ("box 160-400", 160, 400), ("mid 400-1k", 400, 1000),
              ("bite 1-2.5k", 1000, 2500), ("edge 2.5-6k", 2500, 6000), ("fizz >6k", 6000, 20000)]
    def grouped(t):
        lin = 10 ** (t / 10)
        return {g: 10 * np.log10(sum(e for c, e in zip(THIRDS, lin) if lo <= c < hi) + 1e-12) for g, lo, hi in groups}
    rows = []
    for p in paths:
        x, sr = mono(p)
        rows.append((Path(p).stem[:28], grouped(third_octaves(x, sr))))
    for ref in sorted(REFS.glob("*.wav")):
        r, rsr = mono(ref)
        seg, t = kick_alone(r, rsr)
        rows.append((f"{ref.stem[:20]} @{t:.0f}s", grouped(third_octaves(seg, rsr))))
    for label, g in rows:
        print(f"{label:28s} " + " ".join(f"{k.split()[0]} {v:6.1f}" for k, v in g.items()))


if __name__ == "__main__":
    if sys.argv[1] == "kick":
        kicks(sys.argv[2:])
    elif sys.argv[1] == "kickshape":
        kick_shapes(sys.argv[2:])
    else:
        main()
