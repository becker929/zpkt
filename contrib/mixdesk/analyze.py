"""Measure the desk's A/B/C sources once and cache it for the page.

    .venv/bin/python contrib/mixdesk/analyze.py        # the repo's venv (uv sync --all-extras); needs numpy, scipy, soundfile, pyloudnorm

Reads sources.json; writes 16-bit PCM WAVs (what the browser decodes reliably) and analysis.json to its "dir".
This is measurement only: nothing here changes a sound. The page plays the WAVs, and draws these numbers.

Per source: 1/6-octave spectrum of the mid signal for the build and the drop (dB, before any loudness match), a
1 s timeline of short-term loudness, crest, width and bass correlation, a waveform envelope, and the totals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import welch

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "sources.json").read_text())
OUT = Path(CFG["dir"]).expanduser()
BUILD_END = float(CFG["build_end_s"])

CENTERS = 20.0 * 2.0 ** (np.arange(0, 61) / 6.0)  # 20 Hz .. ~20 kHz, 1/6 octave
EDGES_LO = CENTERS / 2.0 ** (1 / 12)
EDGES_HI = CENTERS * 2.0 ** (1 / 12)
BASS_HZ, HIGH_HZ = 150.0, 4000.0


def band_db(x: np.ndarray, sr: int) -> list[float]:
    """Mean power per 1/6-octave band of a mono signal, in dB (full-scale sine = -3 dB)."""
    if len(x) < 8192:
        return [-120.0] * len(CENTERS)
    f, p = welch(x, fs=sr, nperseg=16384, noverlap=8192, window="hann", scaling="spectrum")
    out = []
    for lo, hi in zip(EDGES_LO, EDGES_HI, strict=False):
        m = (f >= lo) & (f < hi)
        out.append(float(10 * np.log10(p[m].sum() + 1e-12)) if m.any() else -120.0)
    return out


def corr(a: np.ndarray, b: np.ndarray) -> float:
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 1e-12 else 1.0


def lowpass_fft(x: np.ndarray, sr: int, hz: float) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    X[f > hz] = 0
    return np.fft.irfft(X, len(x))


def measure(path: Path, is_ref: bool) -> tuple[dict, np.ndarray, int]:
    x, sr = sf.read(str(path), always_2d=True)
    x = x[:, :2] if x.shape[1] >= 2 else np.repeat(x, 2, axis=1)
    meter = pyln.Meter(sr)
    n = len(x)
    dur = n / sr
    mid, side = x.sum(1) / 2, (x[:, 0] - x[:, 1]) / 2
    cut = int(min(BUILD_END, dur) * sr) if not is_ref else 0
    secs = {"drop": (cut, n)} if is_ref else {"build": (0, cut), "drop": (cut, n)}
    sections = {}
    for name, (a, b) in secs.items():
        seg = x[a:b]
        lufs = float(meter.integrated_loudness(seg)) if len(seg) > sr else None
        sections[name] = {
            "from_s": a / sr,
            "to_s": b / sr,
            "lufs": lufs,
            "spec": band_db(mid[a:b], sr),
            "side_spec": band_db(side[a:b], sr),
            "peak_db": float(20 * np.log10(np.abs(seg).max() + 1e-12)),
            "crest_db": float(20 * np.log10(np.abs(seg).max() + 1e-12) - 10 * np.log10((seg**2).mean() + 1e-12)),
            "width_db": float(10 * np.log10(((side[a:b]) ** 2).sum() / (((mid[a:b]) ** 2).sum() + 1e-12) + 1e-12)),
        }
        bass = lowpass_fft(seg[:, 0], sr, BASS_HZ), lowpass_fft(seg[:, 1], sr, BASS_HZ)
        sections[name]["bass_corr"] = corr(*bass)
    # timeline, 1 s hop, 3 s window (short-term loudness)
    tl: dict[str, list[float]] = {"t": [], "lufs": [], "crest": [], "width": [], "bass_corr": []}
    for t in np.arange(0, dur - 0.5, 1.0):
        a, b = int(t * sr), int(min(dur, t + 3.0) * sr)
        w = x[a:b]
        if len(w) < int(0.5 * sr):
            continue
        loud = meter.integrated_loudness(w) if len(w) >= int(0.4 * sr) else -70.0
        tl["t"].append(float(t + 1.5))
        tl["lufs"].append(float(max(loud, -70.0)))
        tl["crest"].append(float(20 * np.log10(np.abs(w).max() + 1e-12) - 10 * np.log10((w**2).mean() + 1e-12)))
        m, s = w.sum(1) / 2, (w[:, 0] - w[:, 1]) / 2
        tl["width"].append(float(10 * np.log10((s**2).sum() / ((m**2).sum() + 1e-12) + 1e-12)))
        tl["bass_corr"].append(corr(lowpass_fft(w[:, 0], sr, BASS_HZ), lowpass_fft(w[:, 1], sr, BASS_HZ)))
    # three-band energy over time (low <150 Hz, mid, high >4 kHz), dB, 1 s hop, 1 s window
    bands: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
    for t in np.arange(0, dur - 0.5, 1.0):
        a, b = int(t * sr), int(min(dur, t + 1.0) * sr)
        sp = np.abs(np.fft.rfft(mid[a:b] * np.hanning(b - a))) ** 2
        f = np.fft.rfftfreq(b - a, 1 / sr)
        tot = sp.sum() + 1e-12
        for k, m in (("low", f < BASS_HZ), ("mid", (f >= BASS_HZ) & (f < HIGH_HZ)), ("high", f >= HIGH_HZ)):
            bands[k].append(float(10 * np.log10(sp[m].sum() / tot + 1e-12)))
    # envelope, 20 per second, peak of the mid signal
    step = max(1, sr // 20)
    env = [float(np.abs(mid[i : i + step]).max()) for i in range(0, n, step)]
    info = {
        "duration_s": dur,
        "sr": sr,
        "sections": sections,
        "timeline": tl,
        "bands": bands,
        "env": env,
        "peak_db": float(20 * np.log10(np.abs(x).max() + 1e-12)),
    }
    return info, x, sr


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "build_end_s": BUILD_END,
        "ref_align_s": float(CFG["ref_align_s"]),
        "centers": [round(float(c), 2) for c in CENTERS],
        "sources": {},
    }
    for kind, items in (("mix", CFG["mixes"]), ("ref", CFG["refs"])):
        for it in items:
            src = Path(it["file"]).expanduser()
            if not src.exists():
                print(f"missing {src}", file=sys.stderr)
                continue
            info, x, sr = measure(src, kind == "ref")
            wav = OUT / f"{it['id']}.wav"
            sf.write(str(wav), x.astype(np.float32), sr, subtype="PCM_16")
            info.update(
                {
                    "id": it["id"],
                    "label": it["label"],
                    "what": it["what"],
                    "kind": kind,
                    "file": str(src),
                    "wav": f"/media/{it['id']}.wav",
                }
            )
            result["sources"][it["id"]] = info
            d = info["sections"]["drop"]
            print(
                f"{it['id']:3} {it['label']:10} {info['duration_s']:6.1f}s drop {d['lufs']:.1f} LUFS crest {d['crest_db']:.1f}",
                flush=True,
            )
    (OUT / "analysis.json").write_text(json.dumps(result, separators=(",", ":")))
    print("wrote", OUT / "analysis.json")


if __name__ == "__main__":
    main()
