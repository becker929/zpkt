"""The references' kicks, isolated by the beat, and our kick against them.

Anthony (13 Nov 2026): "see if you can isolate kicks from the references and then spectrally match them". No
separation model is installed, so this isolates by repetition: in a drop the kick hits on every beat, so every beat
of the drop is lined up on its kick onset (found in the low band near the beat grid) and the median spectrogram over
the beats keeps what repeats every beat at that place (the kick and what rides with it) and drops what does not
(stabs, vocals, risers, fills). The kick is then the slice from the onset to just before the next sixteenth, where an
off-grid hat would start. The same method runs on our mix, so both sides carry the same leftovers (rumble, an on-beat
hat), and on our kick loop alone, where the answer is known: the difference is the method's own error.

    uv run --project ears python contrib/arranger/kickiso.py            # shapes, and the match curve
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import hw002
import numpy as np
import soundfile as sf

DATA = hw002.DATA
OUT = DATA / "kickiso"
N, HOP = 4096, 256
THIRDS = [25 * 2 ** (k / 3) for k in range(0, 30)]  # 25 Hz to about 16 kHz


def mono(path: Path) -> tuple[np.ndarray, int]:
    x, r = sf.read(path, always_2d=True)
    return x.mean(axis=1), r


def onsets(m: np.ndarray, r: int, t0: float, beat: float, n: int) -> list[float]:
    """The kick onset nearest each beat of the grid: the steepest rise of the 40-150 Hz envelope within 30 ms."""
    from scipy.signal import butter, sosfilt

    low = sosfilt(butter(4, [40, 150], btype="band", fs=r, output="sos"), m)
    env = np.convolve(np.abs(low), np.ones(int(0.002 * r)) / int(0.002 * r), mode="same")
    d = np.diff(env, prepend=env[0])
    out, w = [], int(0.03 * r)
    for k in range(n):
        c = int((t0 + k * beat) * r)
        if c - w < 0 or c + w >= len(m):
            continue
        out.append((c - w + int(np.argmax(d[c - w : c + w]))) / r)
    return out


def kick_spectrum(m: np.ndarray, r: int, starts: list[float], beat: float) -> tuple[np.ndarray, np.ndarray]:
    """Median over beats of each frame's power spectrum, for frames from the onset to 0.22 of a beat (before the
    next sixteenth); summed over those frames. Returns (frequencies, power)."""
    win = np.hanning(N)
    span = int(0.22 * beat * r)
    frames = list(
        range(-N // 4, span - N // 2, HOP)
    )  # frame starts relative to the onset (the first frame catches the attack)
    stack = []
    for s in starts:
        c = int(s * r)
        rows = []
        for f in frames:
            a = c + f
            seg = m[a : a + N] if a >= 0 and a + N <= len(m) else None
            if seg is None:
                break
            rows.append(np.abs(np.fft.rfft(seg * win)) ** 2)
        if len(rows) == len(frames):
            stack.append(rows)
    S = np.median(np.array(stack), axis=0)  # [frames, bins]: what repeats on every beat
    return np.fft.rfftfreq(N, 1 / r), S.sum(axis=0)


def thirds(f: np.ndarray, p: np.ndarray) -> np.ndarray:
    out = []
    for c in THIRDS:
        sel = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
        if not sel.any():  # a band narrower than a bin (the lowest): the bin it falls in, scaled to its width
            k = int(np.argmin(abs(f - c)))
            out.append(10 * np.log10(p[k] * (c * (2 ** (1 / 6) - 2 ** (-1 / 6))) / (f[1] - f[0]) + 1e-20))
            continue
        out.append(10 * np.log10(p[sel].sum() + 1e-20))
    out = np.array(out)
    return out - 10 * np.log10((10 ** (out / 10)).sum())  # dB of its own total: shape, not level


def shape_of(path: Path, drop: float, bpm: float, beats: int = 64) -> tuple[np.ndarray, int]:
    m, r = mono(path)
    beat = 60.0 / bpm
    st = onsets(m, r, drop, beat, beats)
    f, p = kick_spectrum(m, r, st, beat)
    return thirds(f, p), len(st)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    refs = [x for x in json.loads((DATA / "refs" / "refs.json").read_text())["refs"] if x["set"] == "hw002"]
    rows = {}
    for x in refs:
        rows[x["id"]], n = shape_of(DATA / "refs" / x["file"], x["drop"], x["bpm"])
        print(f"{x['title'][:34]:34s} {n} beats")
    ours, _ = shape_of(DATA / "spectral" / "before.flac", hw002.DROP_SECONDS, hw002.TEMPO_BPM)
    # our kick loop alone (4 bars, looped 4 times so there are 64 beats), through the same method: the method's error
    loop = sf.read(DATA / "kickfuzz" / "base.flac", always_2d=True)[0]
    tmp = OUT / "base-x4.wav"
    sf.write(tmp, np.concatenate([loop] * 5), hw002.RATE)
    alone, _ = shape_of(tmp, 6.0, hw002.TEMPO_BPM)
    # each kick option's loop (kickfuzz.py), through the same method: how far from the references' average,
    # over the range the method is clean in (40 Hz to 4 kHz)
    opts = {}
    for loopf in sorted((DATA / "kickfuzz").glob("*.flac")):
        if loopf.stem.startswith("mix-") or loopf.stem.endswith("-stem"):
            continue
        y = sf.read(loopf, always_2d=True)[0]
        sf.write(tmp := OUT / "opt-x4.wav", np.concatenate([y] * 5), hw002.RATE)
        opts[loopf.stem], _ = shape_of(tmp, 6.0, hw002.TEMPO_BPM)
    ref = np.array(list(rows.values()))
    mean, lo, hi = ref.mean(0), ref.min(0), ref.max(0)
    res = {
        "thirds": [round(c, 1) for c in THIRDS],
        "refs": {k: [round(float(v), 2) for v in s] for k, s in rows.items()},
        "titles": {x["id"]: x["title"] for x in refs},
        "refMean": [round(float(v), 2) for v in mean],
        "ours": [round(float(v), 2) for v in ours],
        "oursAlone": [round(float(v), 2) for v in alone],
        # what to add to our kick to reach the references' average, read off the mix (both sides isolated alike)
        "match": [round(float(v), 2) for v in mean - ours],
        "options": {k: [round(float(v), 2) for v in s] for k, s in opts.items()},
    }
    clean = (np.array(THIRDS) >= 40) & (np.array(THIRDS) <= 4100)
    print("distance to the references' average, 40 Hz-4 kHz (RMS dB), and the gap at 2-4 kHz:")
    for k, s_ in sorted(opts.items(), key=lambda kv: np.sqrt(np.mean((kv[1] - mean)[clean] ** 2))):
        d = s_ - mean
        print(
            f"  {k:5s} {np.sqrt(np.mean(d[clean] ** 2)):5.2f}  2-4k {np.mean(d[(np.array(THIRDS) >= 2000) & (np.array(THIRDS) <= 4100)]):+5.1f}"
            f"  80-200 {np.mean(d[(np.array(THIRDS) >= 79) & (np.array(THIRDS) <= 200)]):+5.1f}"
        )
    (OUT / "kickiso.json").write_text(json.dumps(res))
    print(f"\n{'Hz':>7s} {'ours':>6s} {'alone':>6s} {'error':>6s} {'refs':>6s} [{'lo':>6s} {'hi':>6s}] {'match':>6s}")
    for k, c in enumerate(THIRDS):
        print(
            f"{c:7.0f} {ours[k]:6.1f} {alone[k]:6.1f} {ours[k] - alone[k]:+6.1f} {mean[k]:6.1f} [{lo[k]:6.1f} {hi[k]:6.1f}] {mean[k] - ours[k]:+6.1f}"
        )


# ---- the match: an EQ Eight fitted to the gap ------------------------------------------------------------------------


def bell(f: np.ndarray, f0: float, g: float, q: float, fs: float = 44100.0) -> np.ndarray:
    """RBJ peaking filter's gain in dB at f (EQ Eight's bell is this shape, close enough to fit with)."""
    A, w0 = 10 ** (g / 40), 2 * np.pi * f0 / fs
    al = np.sin(w0) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w0), 1 - al * A])
    a = np.array([1 + al / A, -2 * np.cos(w0), 1 - al / A])
    z = np.exp(-1j * 2 * np.pi * f / fs)
    h = (b[0] + b[1] * z + b[2] * z**2) / (a[0] + a[1] * z + a[2] * z**2)
    return 20 * np.log10(np.abs(h))


def fit(gap: np.ndarray, lo: float = 30.0, hi: float = 4100.0, bands: int = 6, cap: float = 8.0) -> list[tuple]:
    """Up to `bands` bells, greedily, each at the largest remaining gap (in lo..hi), its Q chosen to shrink the gap
    most. Gains capped at +-cap dB. Returns [(freq, gain, q)]."""
    f = np.array(THIRDS)
    use = (f >= lo) & (f <= hi)
    r, out = np.where(use, gap, 0.0), []
    free = use.copy()  # one bell per region: no two within two thirds of an octave, so no frequency gets past +-cap
    for _ in range(bands):
        sm = np.convolve(r, [0.25, 0.5, 0.25], mode="same")
        if not free.any():
            break
        k = int(np.argmax(np.abs(sm) * free))
        free[max(0, k - 2) : k + 3] = False
        if abs(sm[k]) < 1.0:
            break
        g = float(np.clip(sm[k], -cap, cap))
        best = min((np.sqrt(np.mean((r - bell(f, f[k], g, q))[use] ** 2)), q) for q in (0.5, 0.7, 1.0, 1.4, 2.0, 3.0))
        out.append((round(float(f[k]), 1), round(g, 1), best[1]))
        r = r - bell(f, f[k], g, best[1])
    return out


MATCHES = [  # (name, the kick it starts from, the target: "mean" of the four references, or one reference's id)
    ("m0", "base", "mean"),
    ("mb6", "b6", "mean"),
    ("mf1", "t-f1", "ksms-roses-of-flesh-and-blood"),
    ("mf1s", "t-f1s", "ksms-roses-of-flesh-and-blood"),
    ("mmtf12", "t-mtf12", "ksms-roses-of-flesh-and-blood"),
]


def match() -> None:
    res = json.loads((OUT / "kickiso.json").read_text())
    out = {}
    for name, start, target in MATCHES:
        mean = np.array(res["refMean"] if target == "mean" else res["refs"][target])
        eq = fit(mean - np.array(res["options"][start]))
        after = np.array(res["options"][start]) + sum(bell(np.array(THIRDS), *b) for b in eq)
        clean = (np.array(THIRDS) >= 40) & (np.array(THIRDS) <= 4100)
        out[name] = {
            "from": start,
            "target": target,
            "bells": eq,
            "predictedRms": round(float(np.sqrt(np.mean((after - mean)[clean] ** 2))), 2),
        }
        print(name, start, eq, "predicted distance", out[name]["predictedRms"])
    (OUT / "match.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    match() if sys.argv[1:] == ["match"] else main()
