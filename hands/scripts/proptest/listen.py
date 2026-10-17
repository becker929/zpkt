"""Measure a render against what the piece needs, per section (parts.SECTIONS):

- loudness: the mix's short-term LUFS (median per section) and the spread across sections: the form should rise
  and fall (D and F quieter, E the loudest), not sit at one level (the industrial short's lesson);
- speech: the voice stem against the music stem in 1-4 kHz (where consonants are), per section; the narration is
  the point of the video, so the music must stay under it there;
- grid: how far the bed's hits (their 0.8-5 kHz attacks; its sub-bass onsets lag ~30 ms) sit from the kick grid,
  per section, in the bed as placed (the source cut and nudged by parts.BED_CLIPS: the rendered bed is ducked by
  the kick, which would put the kick's own grid into the measure);
- kick: peak-to-RMS per hit and the attack, from the kick stem (the punch the industrial v8 lost).

  cd hands && uv run python scripts/proptest/listen.py [renders/proptest-v1.wav]   # stems from renders/stems/
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).parent))
import ops  # noqa: E402
import parts as P  # noqa: E402

STEMS = ops.SCRATCH / "renders" / "stems"


def mono(path: Path) -> tuple[np.ndarray, int]:
    y, sr = sf.read(path, always_2d=True)
    return y.mean(1), sr


def t_of_beat(beat: float) -> float:
    return (beat - P.ORIGIN) * P.SPB


def section_spans() -> dict[str, tuple[float, float]]:
    out = {}
    for s, (a, b) in P.SECTIONS.items():
        out[s] = (max(0.0, t_of_beat(P.bar(a))), min(P.VIDEO_S, t_of_beat(P.bar(b)) if s != "H" else P.VIDEO_S))
    return out


def short_term(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """ffmpeg's ebur128 short-term loudness (3 s window), every 0.1 s."""
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=metadata=1,"
                          "ametadata=print:key=lavfi.r128.S:file=-", "-f", "null", "-"],
                         capture_output=True, text=True, check=False)
    ts, vs = [], []
    t = None
    for line in run.stdout.splitlines():
        if line.startswith("frame:"):
            t = float(line.split("pts_time:")[1])
        elif line.startswith("lavfi.r128.S=") and t is not None:
            ts.append(t)
            vs.append(float(line.split("=")[1]))
    return np.array(ts), np.array(vs)


def band_db(y: np.ndarray, sr: int, lo: float, hi: float, a: float, b: float) -> float:
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    seg = sosfiltfilt(sos, y[int(a * sr):int(b * sr)])
    return 10 * np.log10(np.mean(seg ** 2) + 1e-12)


def onset_env(y: np.ndarray, sr: int, hop: int = 64, band=(800, 5000)) -> tuple[np.ndarray, float]:
    """Spectral-flux onsets in a band: the rise of log magnitude summed over the band, per hop (1024-point frames)."""
    from scipy.signal import stft
    f, _, Z = stft(y, fs=sr, nperseg=1024, noverlap=1024 - hop, boundary=None, padded=False)
    e = np.log(np.abs(Z[(f >= band[0]) & (f < band[1])]).sum(0) + 1e-6)
    return np.maximum(np.diff(e, prepend=e[0]), 0), sr / hop


def grid_offset(bed: np.ndarray, kick: np.ndarray, sr: int, a: float, b: float) -> tuple[float, float]:
    """Where the bed's hits sit against the rendered kick (ms, + is the bed late), from their onset patterns folded
    on two beats and cross-correlated within +-60 ms; and how strongly they agree (correlation)."""
    period = 2 * P.SPB
    hb, fr = onset_env(bed, sr)
    hk, _ = onset_env(kick, sr, band=(30, 5000))
    t = np.arange(min(len(hb), len(hk))) / fr
    m = (t >= a) & (t < b)
    n = int(round(period * fr))
    idx = (((t[m] - P.GRID_T0) % period) * fr).astype(int) % n

    def fold(d):
        h = np.zeros(n)
        c = np.zeros(n)
        np.add.at(h, idx, d[: len(t)][m])
        np.add.at(c, idx, 1)
        h = h / np.maximum(c, 1)
        return (h - h.mean()) / (h.std() + 1e-12)
    fb, fk = fold(hb), fold(hk)
    lags = np.arange(-int(0.06 * fr), int(0.06 * fr) + 1)
    xc = np.array([np.dot(np.roll(fk, k), fb) / n for k in lags])
    k = int(np.argmax(xc))
    return lags[k] / fr * 1000, float(xc[k])


def placed_bed() -> tuple[np.ndarray, int]:
    y, sr = mono(ops.SET_DIR / "Samples" / "Imported" / P.BED)
    out = np.zeros(int(P.VIDEO_S * sr) + sr)
    for f0, f1, sh, _gain in P.BED_CLIPS:
        seg = y[int(f0 * sr):int(f1 * sr)]
        d = int(round((f0 + sh) * sr))
        if d < 0:                                    # the first piece starts before the files' 0 s
            seg, d = seg[-d:], 0
        seg = seg[:len(out) - d]
        out[d:d + len(seg)] = seg
    return out, sr


def kick_hits(y: np.ndarray, sr: int) -> list[tuple[float, float, float]]:
    """Per kick (from the notes): peak-to-RMS over 120 ms (dB) and the time to its peak (ms)."""
    out = []
    beats = sorted({b for b, *_ in P.kick()})
    for beat in beats:
        t = t_of_beat(beat)
        if t < 0 or t + 0.12 > len(y) / sr:
            continue
        seg = y[int(t * sr): int((t + 0.12) * sr)]
        pk = np.max(np.abs(seg))
        out.append((t, 20 * np.log10(pk / (np.sqrt(np.mean(seg ** 2)) + 1e-12)), np.argmax(np.abs(seg)) / sr * 1000))
    return out


def main(mix_path: Path) -> None:
    spans = section_spans()
    ts, st = short_term(mix_path)
    voice, sr = mono(STEMS / "stem-voice.wav")
    music, _ = mono(STEMS / "stem-music.wav")
    bed, _ = placed_bed()
    kick, _ = mono(STEMS / "stem-kick.wav")
    print(f"{mix_path.name}")
    print("sec   time          mix S-LUFS (med/max)  voice-music 1-4k  bed vs kick ms (corr)")
    meds = {}
    for s, (a, b) in spans.items():
        m = (ts >= a + 1.0) & (ts < b)          # the 3 s window lags: skip its first second
        med = float(np.median(st[m])) if m.any() else float("nan")
        meds[s] = med
        vm = band_db(voice, sr, 1000, 4000, a, b) - band_db(music, sr, 1000, 4000, a, b)
        g, gs = grid_offset(bed, kick, sr, a, b)
        print(f"  {s}  {a:5.1f}-{b:5.1f}s   {med:6.1f} / {np.max(st[m]) if m.any() else float('nan'):6.1f}"
              f"        {vm:+5.1f} dB          {g:+5.0f} ({gs:.2f})")
    print(f"  section spread (max-min of medians): {max(meds.values()) - min(meds.values()):.1f} LU;"
          f" E - C: {meds['E'] - meds['C']:+.1f}, D - E: {meds['D'] - meds['E']:+.1f}, F - E: {meds['F'] - meds['E']:+.1f}")
    hits = kick_hits(kick, sr)
    crest = np.array([h[1] for h in hits])
    att = np.array([h[2] for h in hits])
    print(f"  kick: {len(hits)} hits, peak/RMS over 120 ms {np.median(crest):.1f} dB (p10 {np.percentile(crest, 10):.1f}),"
          f" time to peak {np.median(att):.1f} ms")
    lo = band_db(kick, sr, 30, 120, 0, P.VIDEO_S) - band_db(music, sr, 30, 120, 0, P.VIDEO_S)
    print(f"  kick share of the music's 30-120 Hz: {lo:+.1f} dB")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ops.SCRATCH / "renders" / "proptest-v1.wav")
