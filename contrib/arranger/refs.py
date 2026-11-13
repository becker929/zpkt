"""What the mix page needs to compare against: the reference tracks, and the spectra of the arrangement's own sounds.

    uv run --project ears python contrib/arranger/refs.py          # writes ~/_agent_scratch/arranger/refs/

For each reference (the four HW002 references and the Klangkuenstler shorts): its tempo, its drop (the bar where
the low end comes back after the longest quiet stretch), the 16 bars before the drop and 24 after it as a FLAC (cut
only, at the file's own level and rate), its K-weighted power bar by bar (for the page's loudness match, a listening
aid), and a log-frequency spectrogram of that stretch. Tempo for the shorts is wav-timeline's tracks.json. For every loop and transition sound in the arrangement: its average
spectrum, for the page's suggested cuts. Measuring only: nothing here makes sound.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import numpy as np
import pyloudnorm as pl
import soundfile as sf

DATA = Path("~/_agent_scratch/arranger").expanduser()
OUT = DATA / "refs"
HW002 = Path("~/_agent_scratch/refs/HW002").expanduser()
KK = Path("~/Desktop/Klangkuenstler shorts").expanduser()
KK_TRACKS = Path("~/Desktop/wav-timeline/tracks.json").expanduser()
BANDS, FMIN, FMAX, FPS = 96, 20.0, 20000.0, 8
PRE, POST = 16, 24          # bars kept before and after the drop


def band_edges(rate: int, n_fft: int) -> list[np.ndarray]:
    f = np.fft.rfftfreq(n_fft, 1 / rate)
    edges = FMIN * (FMAX / FMIN) ** (np.arange(BANDS + 1) / BANDS)
    return [np.where((f >= a) & (f < b))[0] for a, b in zip(edges[:-1], edges[1:])]


def spectrogram(x: np.ndarray, rate: int) -> np.ndarray:
    """dB per log band, FPS frames a second, 0 dB = full-scale sine; bins too few for a low band borrow the nearest."""
    mono = x.mean(1)
    n_fft, hop = 8192, int(rate / FPS)
    win = np.hanning(n_fft)
    idx = band_edges(rate, n_fft)
    f = np.fft.rfftfreq(n_fft, 1 / rate)
    centers = FMIN * (FMAX / FMIN) ** ((np.arange(BANDS) + 0.5) / BANDS)
    idx = [i if len(i) else np.array([int(np.argmin(np.abs(f - c)))]) for i, c in zip(idx, centers)]
    frames = []
    for s in range(0, max(1, len(mono) - n_fft), hop):
        P = np.abs(np.fft.rfft(mono[s:s + n_fft] * win)) ** 2 * (4 / np.sum(win) ** 2)
        frames.append([10 * np.log10(P[i].mean() * len(i) + 1e-12) for i in idx])
    return np.array(frames)


def pack(db: np.ndarray) -> str:
    """uint8 per value, -100..0 dB, base64."""
    return base64.b64encode(np.clip((db + 100) / 100 * 255, 0, 255).astype(np.uint8).tobytes()).decode()


def kpower(x: np.ndarray, rate: int, bar_s: float) -> list[float]:
    """Mean K-weighted power (BS.1770 pre-filter) per bar, in dB."""
    m = pl.Meter(rate)
    y = x.astype(np.float64).copy()
    for f in m._filters.values():   # per channel, along time, as pyloudnorm's meter does
        for c in range(y.shape[1]):
            y[:, c] = f.apply_filter(y[:, c])
    p = (y ** 2).sum(1)
    n = int(round(bar_s * rate))
    return [round(float(10 * np.log10(p[i:i + n].mean() + 1e-12)), 2) for i in range(0, len(p) - n + 1, n)]


WT = Path("~/Desktop/wav-timeline").expanduser()


def wav_timeline(x: np.ndarray, rate: int) -> tuple[float, float]:
    """Drop (seconds) and BPM as wav-timeline finds them (its js/analysis.js, run in Node on a 16-bit copy), so the
    page lines up with the drops Anthony already uses there."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.wav"
        sf.write(f, x, rate, subtype="PCM_16")
        js = ("const fs=require('fs');const {detectDrop,estimateBpm}=require(process.argv[1]+'/js/analysis.js');"
              "const src=fs.readFileSync(process.argv[1]+'/test/analysis.js','utf8');"
              "const readWav=eval('('+src.match(/function readWav[\\s\\S]*?\\n}\\n/)[0]+')');"
              "const {chans,sr}=readWav(process.argv[2]);console.log(JSON.stringify([detectDrop(chans,sr),estimateBpm(chans,sr)]))")
        out = subprocess.run(["node", "-e", js, str(WT), str(f)], check=True, capture_output=True, text=True).stdout
    drop, bpm = json.loads(out.strip().splitlines()[-1])
    return float(drop), float(bpm)


def reference(path: Path, set_: str, bpm: float | None, title: str) -> dict:
    x, rate = sf.read(path, dtype="float32", always_2d=True)
    drop, wt_bpm = wav_timeline(x, rate)
    bpm = bpm or wt_bpm
    bar = 4 * 60 / bpm
    a = max(0.0, drop - PRE * bar)
    b = min(len(x) / rate, drop + POST * bar)
    clip = x[int(a * rate):int(b * rate)]
    rid = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    sf.write(OUT / f"{rid}.flac", clip, rate, subtype="PCM_16")
    spec = spectrogram(clip, rate)
    (OUT / f"{rid}.spec.json").write_text(json.dumps({"fps": FPS, "bands": BANDS, "fMin": FMIN, "fMax": FMAX,
                                                     "frames": len(spec), "db": pack(spec)}))
    return {"id": rid, "title": title, "set": set_, "bpm": bpm, "barSeconds": round(bar, 5), "rate": rate,
            "file": f"{rid}.flac", "start": round(a, 4), "drop": round(drop - a, 4),
            "kBars": kpower(clip, rate, bar), "kBarsFrom": round(-((drop - a) / bar), 3)}


def sounds() -> dict:
    """Average spectrum (dB per band) of each loop and transition file the arrangement uses."""
    loops = json.loads((DATA / "loops.json").read_text())
    fx = json.loads((DATA / "fx" / "fx.json").read_text())
    arr = json.loads((DATA / "arrangements" / "short-8d2a2.json").read_text())
    clips = {c["id"]: c for c in loops["clips"]}
    cands = {c["id"]: c for c in fx["candidates"]}
    files = {clips[r["clip"]]["file"]: DATA / "audio" / clips[r["clip"]]["file"] for r in arr["regions"]}
    files |= {cands[t["id"]]["file"]: DATA / "fx" / "audio" / cands[t["id"]]["file"] for t in arr.get("transitions", [])}
    out = {}
    for name, p in files.items():
        x, rate = sf.read(p, dtype="float32", always_2d=True)
        s = spectrogram(x, rate)
        p_mean = (10 ** (s / 10)).mean(0)
        out[name] = [round(float(10 * np.log10(v + 1e-12)), 1) for v in p_mean]
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    refs = []
    for p in sorted(HW002.glob("*.wav")):
        title = p.stem
        refs.append(reference(p, "hw002", None, title))
        print(refs[-1]["title"], refs[-1]["bpm"], "drop at", round(refs[-1]["start"] + refs[-1]["drop"], 2), "s", flush=True)
    kk = json.loads(KK_TRACKS.read_text())
    for p in sorted(KK.glob("*.wav")):
        m = re.search(r"\[([\w-]{11})\]", p.name)
        info = kk.get(m[1], {}) if m else {}
        refs.append(reference(p, "kk", info.get("bpm"), "Klangkuenstler - " + info.get("title", p.stem)))
        print(refs[-1]["title"], refs[-1]["bpm"], "drop at", round(refs[-1]["start"] + refs[-1]["drop"], 2), "s", flush=True)
    (OUT / "refs.json").write_text(json.dumps({"refs": refs, "sounds": sounds(),
                                               "bands": {"n": BANDS, "fMin": FMIN, "fMax": FMAX}}))
    print(OUT / "refs.json")


if __name__ == "__main__":
    main()
