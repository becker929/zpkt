"""`harness lab-bars`: the arrange surface's bar library (static/lab/data/arrange-bars.json). Numbers only.

What it measures, from the same audio `harness lab-audio` serves (lab_audio's paths and decode()):

- the lab's 24-bar stems (the song's bars 121-144), bar by bar: loudness (LUFS, K-weighted per bar), the kick's
  low end under 130 Hz (scooped or full), the perc's highs, the splash, the ARC RAIDERS hit and the chord loop's
  8-bar cycle in the SFX stem,
- the canonical Short's stems (batch 4.3 track 1, 20 bars): which bars hold hat layers A, AB, ABC and ABCD, where
  its long and short splashes are, and how loud each is,
- the hat layers' masks: each layer's power per band (<2 kHz, 2-5, 5-9, 9+) and per 64th of a beat, from the
  canonical perc stem; the page masks a bar that holds all four with the sum of the layers it wants (for the
  layer sets the canonical Short has no bar of, like A+C, and for a build without the canonical stems),
- the splash sample (the set's clip on 6-2022-05-30-005) and a gain curve per 16th that shapes it into the
  canonical long splash (it swells for three beats, then decays),
- the whole song bar by bar (its break, the beats before its kick returns), and the four references at -14 LUFS
  bar by bar at their own tempo, with their breaks (docs/hw002/references.md).

Arrays are 0-based bars; the page labels them 1-based.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from .lab_audio import FULL, MAX_CLIP_S, RATE, SCRATCH, SET, SHAPE, STEMS, arrangement, decode

log = logging.getLogger(__name__)

OUT = Path(__file__).parent / "static" / "lab" / "data" / "arrange-bars.json"
REFS = SCRATCH / "refs" / "HW002" / "matched"
BAR_S = 1.5
BAR = int(RATE * BAR_S)
BEAT = BAR // 4
SPLITS = [2000.0, 5000.0, 9000.0]
SLOTS = 16                                    # mask slots per beat (64 per bar)
SPLASH_TRACK = "6-2022-05-30-005"
# batch 4.3 track 1 (plan43.json b43-01): A on bars 1-4, AB 5-8, ABC 9-12, ABCD 13-20; the long splash on bar 5
# (into bar 6), the short on bar 13. The clean bars of each set, 0-based (bar 6, 0-based 5, holds the long tail).
SHAPE_STATES = {"A": [0, 1, 2, 3], "AB": [6, 7], "ABC": [8, 9, 10, 11], "ABCD": [13, 14, 15, 16, 17, 18, 19]}
SHAPE_SPLASH = {"long": [4, 5], "short": [12]}
LEARN = {"A": [1, 2, 3], "AB": [6, 7], "ABC": [8, 9, 10, 11], "ABCD": [13, 14, 15, 16, 17, 18, 19]}
LAB_SOURCE_BAR = 12                           # a clean bar of the lab's perc stem (all four layers)
SHAPE_SOURCE_BAR = 15                         # a clean ABCD bar of the canonical perc stem
REFERENCES = [                                # name, file, BPM, breaks of 8+ bars or near bar 80 (references.md)
    ("HW002", "HW002 - full - -14LUFS.wav", 160, [[82, 96]]),
    ("BSLS", "BSLS - full - -14LUFS.wav", 160, [[98, 98], [117, 128]]),
    ("Hedon", "Hedon - full - -14LUFS.wav", 158, [[80, 87], [159, 175]]),
    ("KSMS", "KSMS - full - -14LUFS.wav", 155, [[82, 96], [98, 124]]),
    ("Patriotic", "Patriotic - full - -14LUFS.wav", 155, [[80, 96], [133, 152]]),
]


# --- filters as frequency responses (the page runs the same biquads in the time domain) -----------------------------
def _lowpass(f0: float, q: float = 0.7071067811865476):
    w = 2 * np.pi * f0 / RATE
    c, a = np.cos(w), np.sin(w) / (2 * q)
    b = np.array([(1 - c) / 2, 1 - c, (1 - c) / 2])
    den = np.array([1 + a, -2 * c, 1 - a])
    return b / den[0], den / den[0]


def _resp(ba, n: int) -> np.ndarray:
    b, a = ba
    z = np.exp(-1j * 2 * np.pi * np.fft.rfftfreq(n, 1 / RATE) / RATE)
    return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)


def _k_weight(n: int) -> np.ndarray:
    """|H|^2 of BS.1770's K-weighting at RATE, for n-point rfft bins."""
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / RATE)
    vh = 10 ** (g / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = (np.array([(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]),
             np.array([1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]))
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / RATE)
    a0 = 1 + k / q + k * k
    hp = (np.array([1.0, -2.0, 1.0]), np.array([1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]))
    return np.abs(_resp(shelf, n) * _resp(hp, n)) ** 2


def lufs(x: np.ndarray) -> float:
    """BS.1770 loudness of one block (stereo, or mono counted as both channels)."""
    x = x if x.ndim == 2 else x[:, None]
    if not len(x):
        return -70.0
    n = 1 << int(np.ceil(np.log2(len(x) * 2)))
    w = _k_weight(n)
    p = 0.0
    for c in range(x.shape[1]):
        X = np.fft.rfft(x[:, c], n)
        p += float(np.sum(np.abs(X) ** 2 * w) * 2 / n / len(x))
    if x.shape[1] == 1:
        p *= 2
    return float(-0.691 + 10 * np.log10(p + 1e-12))


def band_db(x: np.ndarray, lo: float, hi: float) -> float:
    n = 1 << int(np.ceil(np.log2(max(2, len(x)))))
    X = np.fft.rfft(x if x.ndim == 1 else x.mean(1), n)
    f = np.fft.rfftfreq(n, 1 / RATE)
    m = (f >= lo) & (f < hi)
    return float(10 * np.log10(np.sum(np.abs(X[m]) ** 2) * 2 / n / max(1, len(x)) + 1e-12))


def bandsplit(x: np.ndarray) -> list[np.ndarray]:
    """Four bands that add back up to x exactly: low pass (LR4), then low pass the rest, and so on."""
    n = 1 << int(np.ceil(np.log2(len(x) + RATE)))
    X = np.fft.rfft(x, n, axis=0)
    out, rest = [], X
    for f in SPLITS:
        h = _resp(_lowpass(f), n) ** 2
        lo = rest * (h[:, None] if X.ndim == 2 else h)
        out.append(lo)
        rest = rest - lo
    out.append(rest)
    return [np.fft.irfft(b, n, axis=0)[:len(x)] for b in out]


def _slot_power(bands: list[np.ndarray], bars: list[int]) -> np.ndarray:
    """Mean power per band per beat slot (16 a beat, the four beats averaged) over `bars`."""
    per = BAR // (4 * SLOTS)
    out = np.zeros((len(bands), 4 * SLOTS))
    for k, b in enumerate(bands):
        mono = b.mean(1) if b.ndim == 2 else b
        for bar in bars:
            seg = mono[bar * BAR: bar * BAR + per * 4 * SLOTS].astype(np.float64).reshape(4 * SLOTS, per)
            out[k] += np.mean(seg ** 2, axis=1)
        out[k] /= max(1, len(bars))
    return out.reshape(len(bands), 4, SLOTS).mean(axis=1)


def _bar(x: np.ndarray, i: int) -> np.ndarray:
    return x[i * BAR:(i + 1) * BAR]


def _bars(x: np.ndarray) -> int:
    return len(x) // BAR


def _masked(src: np.ndarray, layers: dict, ref: np.ndarray, name: str) -> np.ndarray:
    """`src` (one bar) masked to the layers in `name`, as the page does it."""
    per = BAR // (4 * SLOTS)
    g = np.sqrt(np.minimum(sum(layers[L] for L in name) / ref, 1.0))
    env = np.repeat(np.tile(g, (1, 4)), per, axis=1)
    env = np.pad(env, ((0, 0), (0, BAR - env.shape[1])), mode="edge")
    return sum(b * env[k][:, None] for k, b in enumerate(bandsplit(src)))


def _splash_clip(als: Path) -> tuple[str, Path] | None:
    """The splash sample's manifest id (lab_audio numbers the set's files src-1, src-2... in this order) and path."""
    _tempo, _tracks, clips = arrangement(als)
    ids: dict[str, str] = {}
    for c in clips:
        if c.file in ids or not Path(c.file).exists():
            continue
        ids[c.file] = f"src-{len(ids) + 1}"
    for c in clips:
        if c.track == SPLASH_TRACK and c.file in ids:
            return ids[c.file], Path(c.file)
    return None


def build(out_path: Path = OUT, als: Path = SET, stems: Path = STEMS, shape: Path = SHAPE, full: Path = FULL,
          refs: Path = REFS) -> dict:
    data: dict = {"about": "HW002's arrange surface: what each bar of the lab's stems holds. Made by `harness "
                           "lab-bars` (lab_bars.py). LUFS per bar, K-weighted; bars 0-based in arrays.",
                  "made": time.strftime("%Y-%m-%d %H:%M:%S"), "bar_seconds": BAR_S}

    # --- the lab's stems (the song's bars 121-144) ----------------------------------------------------------------
    st = {k: decode(stems / f"{k}.wav") for k in ("kick", "perc", "sfx")}
    n = min(_bars(x) for x in st.values())
    data["stem_song_bars"] = [121 + i for i in range(n)]
    rows: dict[str, list[dict]] = {}
    for k, x in st.items():
        rows[k] = [{"lufs": round(lufs(b), 2), "low": round(band_db(b, 20, 130), 2),
                    "hi": round(band_db(b, 6000, 20000), 2), "air": round(band_db(b, 10000, 20000), 2)}
                   for b in (_bar(x, i) for i in range(n))]
    lows = np.array([r["low"] for r in rows["kick"]])
    for i, r in enumerate(rows["kick"]):
        r["scooped"] = bool(lows[i] < np.median(lows) - 3)
    pl = np.array([r["lufs"] for r in rows["perc"]])
    for i, r in enumerate(rows["perc"]):
        r["splash"] = bool(pl[i] > np.median(pl) + 1)
        r["layers"] = "ABCD"                       # every bar of the song's peak holds all four (checked by shape)
    sl = np.array([r["lufs"] for r in rows["sfx"]])
    for i, r in enumerate(rows["sfx"]):
        r["arc"] = bool(sl[i] > np.median(sl) + 6)
        r["chordPhase"] = i % 8
    data["stems"] = rows

    # --- the canonical Short's stems: real hat-layer bars and splashes ----------------------------------------------
    perc_c = decode(shape / "perc.wav")
    kick_c = decode(shape / "kick.wav") if (shape / "kick.wav").exists() else None
    nc = _bars(perc_c)
    shp: dict = {"about": "Batch 4.3 track 1 (plan43 b43-01), the canonical Short: hats A on bars 1-4, AB 5-8, ABC "
                          "9-12, ABCD 13-20; a long splash on bar 5, a short one on 13. `states` lists its clean bars "
                          "of each layer set (0-based).",
                 "bars": nc, "states": {}, "splash": SHAPE_SPLASH, "perc": [], "kick": []}
    for i in range(nc):
        b = _bar(perc_c, i)
        state = next((s for s, bs in SHAPE_STATES.items() if i in bs), "AB" if i in (4, 5) else "ABCD")
        splash = next((kind for kind, bs in SHAPE_SPLASH.items() if i in bs), None)
        shp["perc"].append({"lufs": round(lufs(b), 2), "hi": round(band_db(b, 6000, 20000), 2), "layers": state,
                            "splash": splash})
        if kick_c is not None and i < _bars(kick_c):
            k = _bar(kick_c, i)
            shp["kick"].append({"lufs": round(lufs(k), 2), "low": round(band_db(k, 20, 130), 2)})
    for s, bs in SHAPE_STATES.items():
        seg = np.concatenate([_bar(perc_c, i) for i in bs])
        shp["states"][s] = {"bars": bs, "lufs": round(float(np.mean([shp["perc"][i]["lufs"] for i in bs])), 2),
                            "hi": round(band_db(seg, 6000, 20000), 2)}
    data["shape"] = shp

    # --- the hat masks, learned from the canonical perc stem ----------------------------------------------------
    cb = bandsplit(perc_c)
    P = {s: _slot_power(cb, bs) for s, bs in LEARN.items()}
    layers = {"A": P["A"], "B": np.maximum(P["AB"] - P["A"], 0), "C": np.maximum(P["ABC"] - P["AB"], 0),
              "D": np.maximum(P["ABCD"] - P["ABC"], 0)}
    ref = P["ABCD"]
    names = ["".join(L for j, L in enumerate("ABCD") if m >> j & 1) for m in range(1, 16)]
    lab_src, shape_src = _bar(st["perc"], LAB_SOURCE_BAR), _bar(perc_c, SHAPE_SOURCE_BAR)
    subsets, shape_subsets = {}, {}
    for name in names:
        y = _masked(lab_src, layers, ref, name) if name != "ABCD" else lab_src
        subsets[name] = {"lufs": round(lufs(y), 2), "hi": round(band_db(y, 6000, 20000), 2)}
        y = _masked(shape_src, layers, ref, name) if name != "ABCD" else shape_src
        shape_subsets[name] = {"lufs": round(lufs(y), 2), "hi": round(band_db(y, 6000, 20000), 2)}
    data["hats"] = {
        "about": "Each layer's power per band (<2k, 2-5k, 5-9k, 9k+) and per 16th of a 16th (16 slots a beat), in dB "
                 "against all four, learned from the canonical perc stem. The page masks a bar that holds all four "
                 "(the lab's perc bar `source_bar`, or the canonical one `shape_source_bar`) with the sum of the "
                 "layers it wants. `subsets` and `shape_subsets`: how loud each masked bar is.",
        "splits": SPLITS, "slots": SLOTS, "source_bar": LAB_SOURCE_BAR, "shape_source_bar": SHAPE_SOURCE_BAR,
        "masks": {L: np.round(10 * np.log10(layers[L] / ref + 1e-9), 1).clip(-60, 6).tolist() for L in layers},
        "subsets": subsets, "shape_subsets": shape_subsets,
    }

    # --- the splash sample, shaped into the canonical long splash --------------------------------------------------
    found = _splash_clip(als)
    if found:
        sid, path = found
        spl = decode(path, MAX_CLIP_S)
        mono = spl.mean(1).astype(np.float64)
        loud = np.flatnonzero(np.abs(mono) > 0.01)
        at = int(loud[0]) if len(loud) else 0
        s16 = BEAT // 4
        c16 = perc_c.mean(1).astype(np.float64)

        def p16(first: int, j: int) -> float:                          # power of 16th `j` from 16th `first`
            return float(np.mean(c16[(first + j) * s16:(first + j + 1) * s16] ** 2))

        hats = np.array([p16(6 * 16, j) for j in range(32)]).reshape(8, 4).mean(0)      # bars 7-8: AB, no splash
        tgt = np.array([10 * np.log10(max(p16(4 * 16, j) - hats[j % 4], 1e-9)) for j in range(32)])   # bars 5-6
        tgt = np.convolve(np.pad(tgt, 1, mode="edge"), [0.25, 0.5, 0.25], "valid")
        off = lufs(lab_src) - lufs(shape_src)                          # the lab's perc against the canonical one
        smp = np.array([10 * np.log10(np.mean(mono[at + j * s16: at + (j + 1) * s16] ** 2) + 1e-12) for j in range(32)])
        gain16 = np.clip(tgt + off - smp, -30, 30)
        shaped = np.concatenate([mono[at + j * s16: at + (j + 1) * s16] * 10 ** (gain16[j] / 20) for j in range(32)])
        data["splash"] = {"src": sid, "at": at, "gain16": np.round(gain16, 1).tolist(),
                          "beat_lufs": [round(lufs(shaped[j * BEAT:(j + 1) * BEAT]), 2) for j in range(8)],
                          "about": "The splash sample, shaped per 16th into the canonical long splash (gain16, dB); "
                                   "the page uses the canonical Short's own splash bars where they fit."}
    else:
        log.warning("no splash clip on %s in %s", SPLASH_TRACK, als)
        data["splash"] = {"src": None, "at": 0, "gain16": [0.0] * 32, "beat_lufs": [-70.0] * 8}

    # --- the whole song ------------------------------------------------------------------------------------------
    if full.exists():
        x = decode(full)
        nb = _bars(x)
        data["song"] = {"bars": nb, "lufs": [round(lufs(_bar(x, i)), 2) for i in range(nb)],
                        "break": [81, 96], "short": [121, 140], "peak": [125, 144],
                        "pre_kick_beats_lufs": [round(lufs(x[(96 * 4 - 8 + j) * BEAT:(96 * 4 - 7 + j) * BEAT]), 2)
                                                for j in range(8)]}
    else:
        log.warning("no whole song at %s", full)
        data["song"] = {"bars": 0, "lufs": [], "break": [81, 96], "short": [121, 140], "peak": [125, 144],
                        "pre_kick_beats_lufs": [-70.0] * 8}

    # --- the references --------------------------------------------------------------------------------------------
    data["refs"] = []
    for name, file, bpm, breaks in REFERENCES:
        path = refs / file
        if not path.exists():
            log.warning("no reference %s", path)
            continue
        x = decode(path)
        mono = np.abs(x.mean(1))
        start = int(np.flatnonzero(mono > 0.01)[0]) if np.any(mono > 0.01) else 0
        bl = int(round(RATE * 240 / bpm))
        nb = (len(x) - start) // bl
        data["refs"].append({"name": name, "bpm": bpm, "bars": nb, "breaks": breaks,
                             "lufs": [round(lufs(x[start + i * bl: start + (i + 1) * bl]), 1) for i in range(nb)]})

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, separators=(",", ":")))
    return data


def summary(d: dict) -> str:
    sh = d.get("shape") or {}
    st = sh.get("states", {})
    hs = d["hats"]["subsets"]
    lines = [f"{len(d['stem_song_bars'])} stem bars (the song's {d['stem_song_bars'][0]}-{d['stem_song_bars'][-1]})",
             "  scooped kick bars: " + ", ".join(str(i + 1) for i, r in enumerate(d["stems"]["kick"]) if r["scooped"]),
             f"  canonical Short: {sh.get('bars', 0)} bars; highs " +
             ", ".join(f"{s} {v['hi']:.1f} dB" for s, v in st.items()),
             "  masked on the lab's perc: highs " + ", ".join(f"{s} {hs[s]['hi']:.1f}" for s in st),
             f"  splash {d['splash']['src']}, song {d['song']['bars']} bars, {len(d['refs'])} references"]
    return "\n".join(lines)
