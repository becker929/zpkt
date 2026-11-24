"""The kick design page's data (static/kick.html): the kicks, the references' kicks, and every kick's spectrum frame by
frame, worked out here so the page only draws and plays.

Anthony (13 Nov 2026): "a separate kick design app. It should be ABC switching, kicks only, no full mixes. Optimized
for mobile ... a pre rendered EQ animated curve centered in the page. Not static."

Kicks: HW002's kick options from kickfuzz.py (loops through HW002's own chain, 4 bars at 160 BPM), and from each
HW002 reference two bars where its kick plays nearly alone, cut on its own beat and played as released. Those bars
are found by the beat: every beat must start with a kick (40-150 Hz at the onset), and the score is how quiet the
rest of each beat is above 300 Hz (hats, synths between the kicks), so the kick's own fuzz is not held against it.

    uv run --project ears python contrib/arranger/kickdesign.py

Writes DATA/kickdesign/kicks.json, frames/<id>.json and ref-<id>.flac.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import hw002
import kickiso  # its onset finder
import numpy as np
import pyloudnorm as pl
import soundfile as sf

DATA = hw002.DATA
OUT = DATA / "kickdesign"
REF_WAVS = hw002.REFERENCE_WAVS
NB, F0, F1 = 72, 25.0, 16000.0
EDGES = F0 * (F1 / F0) ** (np.arange(NB + 1) / NB)
CENTRES = np.sqrt(EDGES[:-1] * EDGES[1:])
FPS = 86.0
FLOOR = 90.0  # dB below the loop's total that the page's curve bottoms out at

HW002 = [  # (id, title, file in DATA/kickfuzz, what)
    ("base", "As it is", "base.flac", "HW002's kick chain as it is: the mid-highs are a click that is gone in 8 ms"),
    (
        "mf1",
        "Body fuzz → KSMS",
        "solo-mf1.flac",
        "Body fuzz, then an EQ Eight fitted to KSMS's isolated kick (40 Hz +8, 2.5 kHz +4, 160 and 320 Hz cut)",
    ),
    (
        "t-f1",
        "Body fuzz",
        "t-f1.flac",
        "The kick group's Roar clips the kick's low band (Tri Fold, 24 dB drive) and keeps only what that adds above 600 Hz, 35 % under the clean kick, compressed: fuzz that lives as long as the body, like KSMS's",
    ),
    ("mmtf12", "Punch fuzz → KSMS", "solo-mmtf12.flac", "Punch fuzz, then an EQ Eight fitted to KSMS's isolated kick"),
    (
        "t-mtf12",
        "Punch fuzz",
        "t-mtf12.flac",
        "The kick group's Roar folds only its mid band (200 Hz-2 kHz, the kick's punch): dense like KSMS's, shorter",
    ),
    ("t-t3tf", "Body fuzz, louder", "t-t3tf.flac", "Body fuzz at 50 % wet, +6 dB: KSMS's density, 3 dB more of it"),
    ("b6", "052 +6", "b6.flac", "The 052 click layer +6 dB (the earlier round): more highs, but a tick, not fuzz"),
    ("mb6", "052 +6 matched", "solo-mb6.flac", "052 +6, then an EQ Eight fitted to the four references' average"),
]


def mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def frames_of(x: np.ndarray, r: int) -> tuple[np.ndarray, np.ndarray]:
    """Power per log band for each frame (FPS a second, 2048-point at 44.1 kHz scaled to the rate), and the average."""
    m = mono(x)
    n = int(2 ** round(np.log2(2048 * r / 44100)))
    win = np.hanning(n)
    f = np.fft.rfftfreq(n, 1 / r)
    idx = [np.where((f >= EDGES[k]) & (f < EDGES[k + 1]))[0] for k in range(NB)]
    near = [int(np.argmin(abs(f - c))) for c in CENTRES]
    out = []
    t = 0.0
    pad = np.concatenate([np.zeros(n // 2), m, np.zeros(n)])
    while t * r < len(m):
        a = round(t * r)
        S = np.abs(np.fft.rfft(pad[a : a + n] * win)) ** 2
        out.append(
            [
                S[i].sum() if len(i) else S[near[k]] * (EDGES[k + 1] - EDGES[k]) / (f[1] - f[0])
                for k, i in enumerate(idx)
            ]
        )
        t += 1 / FPS
    P = np.array(out)
    return P, P.mean(axis=0)


def encode(P: np.ndarray, total: float) -> str:
    """Frames as dB below the loop's average total, FLOOR..0 to 0..255, one byte per band."""
    db = 10 * np.log10(P / total + 1e-30)
    q = np.clip((db + FLOOR) / FLOOR * 255, 0, 255).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode()


def ref_kick_bars(path: Path, t_drop: float, bpm: float, bars: int = 2) -> tuple[np.ndarray, int, float]:
    """The reference's two bars where its kick plays most nearly alone, starting on a kick onset."""
    x, r = sf.read(path, always_2d=True)
    m = mono(x)
    beat = 60 / bpm
    first = t_drop - int(t_drop / beat) * beat
    grid = kickiso.onsets(m, r, first, beat, int((len(m) / r - first) / beat))
    from scipy.signal import butter, sosfilt

    low = sosfilt(butter(4, [40, 150], btype="band", fs=r, output="sos"), m)
    high = sosfilt(butter(4, 300, btype="high", fs=r, output="sos"), m)
    lo_db, gap_db = [], []
    for s in grid:
        a, b = int(s * r), int((s + 0.22 * beat) * r)
        c, d = int((s + 0.3 * beat) * r), int((s + 0.95 * beat) * r)
        if d > len(m):
            break
        lo_db.append(10 * np.log10(np.mean(low[a:b] ** 2) + 1e-20))
        gap_db.append(10 * np.log10(np.mean(high[c:d] ** 2) + 1e-20))
    low_db, high_db = np.array(lo_db), np.array(gap_db)
    kick_on = low_db > np.percentile(low_db, 60) - 6  # a kick at this onset
    n, best, at = bars * 4, -1e9, 0
    for k in range(0, len(low_db) - n, 4):  # windows on the bar line, as far as the grid tells
        if not kick_on[k : k + n].all():
            continue
        score = np.mean(low_db[k : k + n]) - np.mean(high_db[k : k + n])
        if score > best:
            best, at = score, k
    a = max(0, int((grid[at] - 0.003) * r))
    return x[a : a + int(n * beat * r)], r, grid[at]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frames").mkdir(exist_ok=True)
    kicks = []
    meter: dict[int, Any] = {}

    def add(kid, title, group, path: Path, url: str, bpm: float, what: str, extra: dict | None = None):
        x, r = sf.read(path, always_2d=True)
        P, avg = frames_of(x, r)
        total = avg.sum()
        meter.setdefault(r, pl.Meter(r))
        lufs = meter[r].integrated_loudness(x)
        (OUT / "frames" / f"{kid}.json").write_text(json.dumps({"fps": FPS, "n": len(P), "b64": encode(P, total)}))
        kicks.append(
            {
                "id": kid,
                "title": title,
                "group": group,
                "url": url,
                "bpm": bpm,
                "beats": round(len(x) / r / (60 / bpm)),
                "seconds": round(len(x) / r, 4),
                "lufs": round(float(lufs), 2),
                "what": what,
                "avg": [round(float(10 * np.log10(v / total + 1e-30)), 2) for v in avg],
                **(extra or {}),
            }
        )
        print(f"{kid:10s} {title:24s} {lufs:6.1f} LUFS {len(P)} frames", flush=True)

    for kid, title, f, what in HW002:
        p = DATA / "kickfuzz" / f
        if p.exists():
            add(kid, title, "HW002", p, f"/kickfuzz/{f}", hw002.TEMPO_BPM, what)
    refs = [x for x in json.loads((DATA / "refs" / "refs.json").read_text())["refs"] if x["set"] == "hw002"]
    for x in refs:
        wav = REF_WAVS / f"{x['title']}.wav"
        if not wav.exists():
            print("no", wav)
            continue
        y, r, t = ref_kick_bars(wav, x["start"] + x["drop"], x["bpm"])
        cut = OUT / f"ref-{x['id']}.flac"
        sf.write(cut, y, r, subtype="PCM_16")
        short = x["title"].split(" - ")[0]
        add(
            "ref-" + x["id"][:24],
            short,
            "Reference",
            cut,
            f"/kickdesign/ref-{x['id']}.flac",
            x["bpm"],
            f"{x['title']}: two bars from {int(t // 60)}:{t % 60:04.1f} where its kick plays most nearly alone, as released",
            {"from": round(float(t), 2)},
        )
    # the target: the references' kick bars, measured exactly as ours are (the whole loop's average shape)
    # KSMS is the canonical reference (Anthony, 13 Nov 2026): its kick is the line, the four make the band
    R = np.array([k["avg"] for k in kicks if k["group"] == "Reference"])
    tgt = np.array(next(k["avg"] for k in kicks if k["id"].startswith("ref-ksms")))
    tlo, thi = R.min(axis=0), R.max(axis=0)
    index = {
        "bands": {"n": NB, "f0": F0, "f1": F1, "centres": [round(float(c), 1) for c in CENTRES]},
        "floor": FLOOR,
        "fps": FPS,
        "target": [round(float(v), 2) for v in tgt],
        "targetLo": [round(float(v), 2) for v in tlo],
        "targetHi": [round(float(v), 2) for v in thi],
        "kicks": kicks,
        "kept": None,
    }
    (OUT / "kicks.json").write_text(json.dumps(index))
    print(OUT / "kicks.json")


if __name__ == "__main__":
    main()
