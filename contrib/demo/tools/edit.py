"""Cut a soundtrack from the full HW002 render and analyse it.

  uv run python tools/edit.py          # the 33-second demo  -> out/demo/
  uv run python tools/edit.py long     # the 102-second cut  -> out/

The source is hw002_121_full_aligned.wav: 160 BPM, bar 1 starts at t=0, so
bar n starts at (n - 1) * 1.5 s. Every cut lands on a bar line.

Writes, into the cut's folder:
  soundtrack.wav   the edit, peaks limited to -1 dBTP (the bar-81 hit is
                   about 9 dB above the kicks), not otherwise mastered
  analysis.js      per-frame band energies + the section map, loaded by
                   demo.html / reel.html as window.ANALYSIS
"""
import json
import pathlib
import subprocess
import sys

import numpy as np

SRC = pathlib.Path.home() / "_agent_scratch/renders/hw002_121_full_aligned.wav"
OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
SR = 44100
BAR = 60 / 160 * 4
BAR_N = int(round(BAR * SR))  # 66150 samples
FPS = 30

# (first bar, last bar inclusive, section id), in playing order
LONG = [
    (89, 96, "genesis"),    # end of the main break, rising into the drop
    (97, 108, "body"),      # the drop: the four members arrive
    (121, 124, "trickster"),  # kick scoop
    (125, 140, "factory"),  # the peak
    (81, 88, "peace"),      # the bar-81 hit, then the break
    (93, 96, "ascent"),     # the riser again
    (141, 152, "elves"),    # end of the peak
    (177, 180, "amen"),     # the track's own ending
]
DEMO = [
    (93, 96, "intro"),      # the riser at the end of the break
    (97, 104, "drop"),      # the kick comes back
    (121, 124, "scoop"),    # kick scooped out for two bars, then back
    (125, 128, "peak"),     # new hats at 125
    (177, 178, "end"),      # the track's last hit and its decay
]
CUTS = {"demo": (DEMO, OUT / "demo"), "long": (LONG, OUT)}
EDIT = LONG  # footage.py's default
FADE = int(0.006 * SR)  # 6 ms join fades, no clicks


def load_stereo(path: pathlib.Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def cut(x: np.ndarray, edit: list) -> tuple[np.ndarray, list[dict]]:
    parts, sections, t = [], [], 0.0
    ramp = np.linspace(0, 1, FADE, dtype=np.float32)[:, None]
    for first, last, sid in edit:
        seg = x[(first - 1) * BAR_N:last * BAR_N].copy()
        if len(seg) < (last - first + 1) * BAR_N:  # the tail runs past the file end
            seg = np.pad(seg, ((0, (last - first + 1) * BAR_N - len(seg)), (0, 0)))
        if parts:
            seg[:FADE] *= ramp
            parts[-1][-FADE:] *= ramp[::-1]
        parts.append(seg)
        dur = len(seg) / SR
        sections.append({"id": sid, "start": round(t, 4), "end": round(t + dur, 4),
                         "src_bars": [first, last]})
        t += dur
    y = np.concatenate(parts)
    tail = int(1.2 * SR)  # final fade over the last 1.2 s
    y[-tail:] *= np.linspace(1, 0, tail, dtype=np.float32)[:, None] ** 2
    return y, sections


def write_wav(y: np.ndarray, path: pathlib.Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
         "-af", "alimiter=limit=0.89:attack=1:release=60:level=disabled",
         "-c:a", "pcm_s24le", str(path)],
        input=y.astype(np.float32).tobytes(), check=True,
    )


def analyse(y: np.ndarray, sections: list[dict]) -> dict:
    mono = y.mean(axis=1)
    hop = SR // FPS
    win = 4096
    window = np.hanning(win).astype(np.float32)
    padded = np.pad(mono, (win // 2, win))
    freqs = np.fft.rfftfreq(win, 1 / SR)
    edges = np.geomspace(30, 16000, 33)  # 32 log bands
    band_idx = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in zip(edges[:-1], edges[1:])]
    frames = len(mono) // hop
    bands = np.zeros((frames, 32), dtype=np.float32)
    rms = np.zeros(frames, dtype=np.float32)
    for f in range(frames):
        seg = padded[f * hop:f * hop + win] * window
        p = np.abs(np.fft.rfft(seg)) ** 2
        bands[f] = [10 * np.log10(p[i].mean() + 1e-10) if len(i) else -100 for i in band_idx]
        core = mono[f * hop:f * hop + hop]
        rms[f] = 20 * np.log10(np.sqrt(np.mean(core ** 2)) + 1e-9)

    def norm(v: np.ndarray, lo_pct: float = 5, hi_pct: float = 99.5) -> np.ndarray:
        lo, hi = np.percentile(v, lo_pct), np.percentile(v, hi_pct)
        return np.clip((v - lo) / (hi - lo + 1e-9), 0, 1)

    # per-band normalisation, so every band uses the full 0..1 range
    nb = np.stack([norm(bands[:, b]) for b in range(32)], axis=1)
    low = norm(bands[:, 0:6].mean(axis=1))     # ~30-90 Hz: kick
    mid = norm(bands[:, 14:22].mean(axis=1))   # ~0.6-3 kHz
    high = norm(bands[:, 24:32].mean(axis=1))  # ~5-16 kHz: hats
    return {
        "fps": FPS,
        "bpm": 160,
        "duration": round(len(mono) / SR, 4),
        "frames": frames,
        "sections": sections,
        "rms": [round(float(v), 3) for v in norm(rms)],
        "low": [round(float(v), 3) for v in low],
        "mid": [round(float(v), 3) for v in mid],
        "high": [round(float(v), 3) for v in high],
        "bands": [[round(float(v), 2) for v in row] for row in nb],
    }


def main() -> None:
    edit, out = CUTS[sys.argv[1] if len(sys.argv) > 1 else "demo"]
    out.mkdir(parents=True, exist_ok=True)
    x = load_stereo(SRC)
    y, sections = cut(x, edit)
    write_wav(y, out / "soundtrack.wav")
    data = analyse(y, sections)
    (out / "analysis.js").write_text("window.ANALYSIS = " + json.dumps(data, separators=(",", ":")) + ";\n")
    for s in sections:
        print(f"{s['id']:10s} {s['start']:7.2f} – {s['end']:7.2f}  bars {s['src_bars']}")
    print(f"duration {data['duration']} s, {data['frames']} frames")


if __name__ == "__main__":
    main()
