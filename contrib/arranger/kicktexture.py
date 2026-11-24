"""The texture of a kick's mid-highs: fuzz or a soft noise.

Anthony (13 Nov 2026), on the kick page: "KSMS is the canonical reference. All of the options add some high freq info
but it's basically a soft noise, like an echo of a stick hit. The reference is fuzzy and compressed. Try
characterizing the texture of the mid highs of the reference and matching that specifically".

Per kick, over the median beat (every beat lined up on its kick onset, as kickiso.py does), in the mid-high band
(1-6 kHz) against the body (40-150 Hz):

- hold: how long the mid-highs stay within 12 dB of their peak, against how long the body does. Fuzz made by
  clipping the body lasts as long as the body; the tick of a stick hit is gone in a few milliseconds.
- lock: how much the mid-highs' envelope moves with the body's waveform (correlation of the band's envelope with the
  rectified body, in the body's first 250 ms). A clipped sine bursts at every peak of the wave, so its harmonics pulse
  at the kick's pitch; noise does not.
- flatness: how noise-like the band's spectrum is (geometric over arithmetic mean of power, 0 a pure set of
  harmonics, 1 white noise), 30-200 ms after the onset.
- crest: peak over RMS of the band's envelope across the beat, in dB. Compressed is low.
- level: the band's share of the kick's energy, in dB.

    uv run --extra audio python contrib/arranger/kicktexture.py [file ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import hw002
import numpy as np
import soundfile as sf
from scipy.signal import butter, hilbert, sosfiltfilt

DATA = hw002.DATA
MH = (1000, 6000)
BODY = (40, 150)


def median_beat(m: np.ndarray, r: int, starts: list[float], beat: float) -> np.ndarray:
    n = int(beat * r)
    segs = [m[int(s * r) - int(0.005 * r) : int(s * r) - int(0.005 * r) + n] for s in starts]
    segs = [s for s in segs if len(s) == n]
    return np.array(segs)


def env(x: np.ndarray, r: int, ms: float = 2.0) -> np.ndarray:
    e = np.abs(hilbert(x))
    k = max(1, int(ms / 1000 * r))
    return np.convolve(e, np.ones(k) / k, mode="same")


def hold_ms(e: np.ndarray, r: int, drop_db: float = 12.0) -> float:
    db = 20 * np.log10(e + 1e-12)
    p = int(np.argmax(db))
    below = np.where(db[p:] < db[p] - drop_db)[0]
    return 1000 * (below[0] if len(below) else len(db) - p) / r


def fast(v: np.ndarray, r: int) -> np.ndarray:
    """The fast movement only (an 8 ms moving average taken out), so two envelopes do not correlate by a shared decay."""
    k = int(0.008 * r)
    return v - np.convolve(v, np.ones(k) / k, mode="same")


def texture(path: Path, bpm: float, t0: float | None = None, exact: bool = False) -> dict:
    x, r = sf.read(path, always_2d=True)
    m = x.mean(axis=1)
    beat = 60 / bpm
    n = int(len(m) / r / beat)
    if exact:  # bounced on the grid: the beats are where the grid says (a search would lock onto the rumble's swell)
        starts = [0.005 + k * beat for k in range(n)]
    else:  # a reference: the grid from its cut, each beat moved to the steepest rise of 30-300 Hz within 8 ms
        from scipy.signal import butter as _b
        from scipy.signal import sosfilt as _sf

        lo = _sf(_b(4, [30, 300], btype="band", fs=r, output="sos"), m)
        e = np.convolve(np.abs(lo), np.ones(int(0.001 * r)) / int(0.001 * r), mode="same")
        d = np.diff(e, prepend=e[0])
        w = int(0.008 * r)
        starts = []
        for k in range(n):
            c = int(((t0 if t0 is not None else 0.003) + k * beat) * r)
            if c - w >= 0 and c + w < len(m):
                starts.append((c - w + int(np.argmax(d[c - w : c + w]))) / r)
    segs = median_beat(m, r, starts, beat)
    mh_f = butter(6, MH, btype="band", fs=r, output="sos")
    bo_f = butter(4, BODY, btype="band", fs=r, output="sos")
    out: dict[str, list[float]] = {k: [] for k in ("holdMh", "holdBody", "lock", "flatness", "crest", "level")}
    for s in segs:
        mh, bo = sosfiltfilt(mh_f, s), sosfiltfilt(bo_f, s)
        emh, ebo = env(mh, r, 1.0), env(bo, r, 4.0)
        out["holdMh"].append(hold_ms(env(mh, r, 3.0), r))
        out["holdBody"].append(hold_ms(ebo, r))
        a, b = int(0.01 * r), int(0.25 * r)
        rect, e1 = fast(np.abs(bo), r)[a:b], fast(emh, r)[a:b]
        best = 0.0
        for lag in range(-int(0.012 * r), int(0.012 * r) + 1, max(1, int(0.0002 * r))):  # within a cycle of the body
            best = max(best, abs(np.corrcoef(np.roll(e1, lag), rect)[0, 1]))
        out["lock"].append(best)
        a, b = int(0.03 * r), int(0.2 * r)
        S = np.abs(np.fft.rfft(mh[a:b] * np.hanning(b - a))) ** 2
        f = np.fft.rfftfreq(b - a, 1 / r)
        band = S[(f >= MH[0]) & (f < MH[1])] + 1e-30
        out["flatness"].append(float(np.exp(np.mean(np.log(band))) / np.mean(band)))
        out["crest"].append(20 * np.log10(np.max(emh) / np.sqrt(np.mean(emh**2)) + 1e-12))
        out["level"].append(10 * np.log10(np.sum(mh**2) / np.sum(s**2) + 1e-20))
    res = {k: round(float(np.median(v)), 3 if k in ("lock", "flatness") else 1) for k, v in out.items()}
    # hold, crest and tail from the median envelope over the beats (one beat's envelope is too noisy to read)
    mh_f6 = mh_f
    E = np.median([env(sosfiltfilt(mh_f6, s), r, 3.0) for s in segs], axis=0)
    Eb = np.median([env(sosfiltfilt(bo_f, s), r, 4.0) for s in segs], axis=0)
    res["holdMh"] = round(hold_ms(E, r), 1)
    res["holdBody"] = round(hold_ms(Eb, r), 1)
    db = 20 * np.log10(E + 1e-12) - 20 * np.log10(E.max() + 1e-12)
    res["tail"] = round(
        float(np.mean(db[int(0.100 * r) : int(0.170 * r)])), 1
    )  # the mid-highs 100-170 ms after the hit (before an offbeat at half a beat)
    res["crest"] = round(float(20 * np.log10(E.max() / np.sqrt(np.mean(E**2)))), 1)
    res["holdRatio"] = round(res["holdMh"] / max(1.0, res["holdBody"]), 2)
    res["beats"] = len(segs)
    return res


def main(files: list[str]) -> None:
    rows = []
    kd = json.loads((DATA / "kickdesign" / "kicks.json").read_text())
    for k in kd["kicks"]:
        p = DATA / k["url"].lstrip("/")  # the page's url is the file's place under DATA
        rows.append((k["title"], texture(p, k["bpm"], exact=k["group"] == "HW002")))
    for f in files:
        rows.append((Path(f).stem, texture(Path(f), hw002.TEMPO_BPM, exact=True)))
    ks = dict(rows)["KSMS"]

    def dist(r):  # how far from KSMS's texture: hold in octaves, flatness per 0.05, crest per 2 dB, level per 3 dB
        return round(
            float(
                np.sqrt(
                    np.log2(max(r["holdMh"], 1) / ks["holdMh"]) ** 2
                    + ((r["flatness"] - ks["flatness"]) / 0.05) ** 2
                    + ((r["crest"] - ks["crest"]) / 2) ** 2
                    + ((r["level"] - ks["level"]) / 3) ** 2
                    + ((r["tail"] - ks["tail"]) / 4) ** 2
                )
            ),
            2,
        )

    for _, r in rows:
        r["toKsms"] = dist(r)
    keys = ["toKsms", "tail", "holdMh", "holdBody", "holdRatio", "lock", "flatness", "crest", "level"]
    print(f"{'':22s}" + "".join(f"{k:>10s}" for k in keys))
    for t, r in rows:
        print(f"{t[:22]:22s}" + "".join(f"{r[k]:10}" for k in keys))
    (DATA / "kickdesign" / "texture.json").write_text(json.dumps({t: r for t, r in rows}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
