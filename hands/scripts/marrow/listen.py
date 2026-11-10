"""Stand-ins for listening (no agent can hear the renders): measure each stem and the mix.

  cd hands && uv run python scripts/marrow/listen.py stems     # every stem: loudness, bands, phone share, pitch
  cd hands && uv run python scripts/marrow/listen.py mix [wav] # the mix: loudness per section, bands, phone share
  cd hands && uv run python scripts/marrow/listen.py pic [wav] # a spectrogram PNG beside the WAV
  cd hands && uv run python scripts/marrow/listen.py chroma    # each pitched stem's notes heard, per section
  cd hands && uv run python scripts/marrow/listen.py masking [--phone]  # each part heard over the rest (raw stems)

Pitch: for each note a track holds alone (nothing else starting under it), the strongest harmonic-product-spectrum
peak in its first 250 ms against the note's own frequency: "ok" within half a semitone, "octave" a whole number of
octaves off, else "off". Chords: the share of chroma on the chord's pitch classes. Phone: the share of a stem's
energy above 180 Hz (a phone speaker gives almost nothing below).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import parts as P  # noqa: E402

SR = 44100
RENDERS = Path("~/_agent_scratch/marrow/renders").expanduser()
SPB = 60.0 / P.BPM
CHORDS = {"organ", "brass"}                 # judged by chroma, not single pitches
PITCHED = {"bass", "guitar", "organ", "lead", "accordion", "brass", "metal"}


def load(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def lufs(path: Path, start: float | None = None, dur: float | None = None) -> float:
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}"]
    cmd += ["-i", str(path), "-af", "ebur128", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    tail = err[err.rfind("Summary:"):]
    for line in tail.splitlines():
        if line.strip().startswith("I:"):
            return float(line.split()[1])
    return float("nan")


def bands(x: np.ndarray) -> dict:
    n = 8192
    frames = x[: len(x) // n * n].reshape(-1, n) * np.hanning(n)
    spec = (np.abs(np.fft.rfft(frames, axis=1)) ** 2).sum(axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    tot = spec.sum() + 1e-20
    edges = {"sub<60": (0, 60), "low60-180": (60, 180), "mid180-2k": (180, 2000), "hi2k-6k": (2000, 6000),
             "air>6k": (6000, SR / 2)}
    return {k: round(float(100 * spec[(f >= lo) & (f < hi)].sum() / tot), 1) for k, (lo, hi) in edges.items()}


def peak_f(seg: np.ndarray) -> float:
    n = 1 << 16
    mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    f = np.fft.rfftfreq(n, 1 / SR)
    band = (f > 25) & (f < 2000)
    return f[band][int(np.argmax(mag[band]))]


def hps_f0(seg: np.ndarray) -> float:
    n = 1 << 15
    w = np.hanning(len(seg))
    mag = np.abs(np.fft.rfft(seg * w, n))
    f = np.fft.rfftfreq(n, 1 / SR)
    prod = mag.copy()
    for k in (2, 3, 4):
        d = mag[::k]
        prod[: len(d)] *= d
    lo, hi = np.searchsorted(f, 25), np.searchsorted(f, 2000)
    return f[lo + int(np.argmax(prod[lo:hi]))]


def pitch_check(name: str, x: np.ndarray) -> str:
    t = next(t for t in P.TRACKS if t["name"] == name)
    notes = sorted({(round(b, 4), p, d, v) for b, p, d, v in t["notes"]()})
    starts = [b for b, *_ in notes]
    if name in CHORDS:
        return chroma_check(notes, x)
    ok = octave = off = 0
    for b, p, d, v in notes:
        if d < 0.3 or v < 70 or sum(1 for s in starts if b - 0.01 <= s < b + d) > 1:
            continue
        i0 = int((b * SPB + 0.03) * SR)
        seg = x[i0: i0 + int(min(d * SPB - 0.03, 0.25) * SR)]
        if len(seg) < SR * 0.08 or np.sqrt(np.mean(seg ** 2)) < 1e-4:
            continue
        want = 440 * 2 ** ((p - 69) / 12)
        cands = [12 * np.log2(hps_f0(seg) / want), 12 * np.log2(peak_f(seg) / want)]
        semis = min(cands, key=abs)          # HPS can lock an octave under a bass; the plain peak can sit on a harmonic
        if abs(semis) < 0.5:
            ok += 1
        elif abs(semis - 12 * round(semis / 12)) < 0.5:
            octave += 1
        else:
            off += 1
    n = ok + octave + off
    return f"pitch ok {ok}/{n}, octave {octave}, off {off}" if n else "pitch: no lone notes"


def chroma_check(notes: list, x: np.ndarray) -> str:
    by_start: dict = {}
    for b, p, d, v in notes:
        by_start.setdefault(b, []).append((p, d))
    shares = []
    for b, ps in by_start.items():
        d = min(dd for _, dd in ps)
        i0 = int((b * SPB + 0.01) * SR)
        seg = x[i0: i0 + int(max(0.08, min(d * SPB, 0.2)) * SR)]
        if len(seg) < 1024 or np.sqrt(np.mean(seg ** 2)) < 1e-4:
            continue
        n = 1 << 15
        mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n)) ** 2
        f = np.fft.rfftfreq(n, 1 / SR)
        keep = (f > 60) & (f < 4000)
        pc = np.round(12 * np.log2(f[keep] / 440) + 69).astype(int) % 12
        chroma = np.bincount(pc, weights=mag[keep], minlength=12)
        want = {p % 12 for p, _ in ps}
        shares.append(chroma[list(want)].sum() / (chroma.sum() + 1e-20))
    return f"chord tones {100 * np.median(shares):.0f}% of chroma (median of {len(shares)})" if shares else "no chords"


def expected_chroma(notes: list, t0: float, t1: float) -> np.ndarray:
    """What the notes should put in each pitch class: duration in the window times harmonics 1-6 (weight 1/k)."""
    c = np.zeros(12)
    for b, p, d, v in notes:
        dur = max(0.0, min(b + d, t1) - max(b, t0))
        for k in range(1, 7):
            c[int(round(p + 12 * np.log2(k))) % 12] += dur * v / k
    return c


def measured_chroma(x: np.ndarray, s0: float, s1: float, lo: float = 60, hi: float = 2500) -> np.ndarray:
    n = 1 << 14
    seg = x[int(s0 * SR): int(s1 * SR)]
    seg = seg[: len(seg) // n * n].reshape(-1, n) * np.hanning(n)
    mag = (np.abs(np.fft.rfft(seg, axis=1)) ** 2).sum(axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    keep = (f > lo) & (f < hi)
    pc = np.round(12 * np.log2(f[keep] / 440) + 69).astype(int) % 12
    return np.bincount(pc, weights=mag[keep], minlength=12)


def chroma_sections() -> None:
    """Per pitched track and section: cosine of the measured chroma with the notes' (harmonics included), and the
    three strongest pitch classes heard against the three the notes should give."""
    names = "C C# D D# E F F# G G# A A# B".split()
    for t in P.TRACKS:
        if t["name"] not in PITCHED:
            continue
        x = load(RENDERS / "stems" / f"stem-{t['name']}.wav")
        notes = t["notes"]()
        for sec, bars, _ in P.SECTIONS:
            b0, b1 = P.START[sec], P.START[sec] + bars * 4
            e = expected_chroma(notes, b0, b1)
            if e.sum() == 0:
                continue
            m = measured_chroma(x, b0 * SPB, b1 * SPB)
            cos = float(e @ m / (np.linalg.norm(e) * np.linalg.norm(m) + 1e-20))
            top = lambda c: " ".join(names[i] for i in np.argsort(c)[::-1][:3])
            print(f"{t['name']:10s} {sec:9s} cos {cos:.2f}   heard {top(m):12s} notes {top(e)}")


def band_power(x: np.ndarray, n: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Power per third-octave band (40 Hz-16 kHz) per frame of n samples (46 ms), and the bands' centres."""
    frames = x[: len(x) // n * n].reshape(-1, n) * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    centres = 1000 * 2 ** (np.arange(-14, 13) / 3)            # 40 Hz ... 16 kHz
    out = np.stack([spec[:, (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))].sum(axis=1) for c in centres], axis=1)
    return out, centres


def masking(phone: bool = False) -> None:
    """How much of each part is heard over the rest, per section: the share of a stem's energy in the (frame, band)
    cells where it is no more than 6 dB under everything else together. From the raw stems (Main's dynamics off), which
    sum to the raw mix. phone: only the bands from 200 Hz to 8 kHz count (a phone speaker's)."""
    folder = RENDERS / "raw"
    pw = {}
    for t in P.TRACKS:
        pw[t["name"]], centres = band_power(load(folder / f"stem-{t['name']}.wav"))
    keep = (centres >= 200) & (centres <= 8000) if phone else np.ones(len(centres), bool)
    total = sum(pw.values())
    fps = SR / 2048
    print(("phone " if phone else "") + "heard % (stem's energy where it is within 6 dB of the rest):")
    print(" " * 10 + "".join(f"{n[:8]:>9s}" for n, _, _ in P.SECTIONS))
    for t in P.TRACKS:
        row = []
        for sec, bars, _ in P.SECTIONS:
            a, b = int(P.START[sec] * SPB * fps), int((P.START[sec] + bars * 4) * SPB * fps)
            e = pw[t["name"]][a:b][:, keep]
            rest = total[a:b][:, keep] - e
            if e.sum() < 1e-3 * total[a:b][:, keep].sum() / len(P.TRACKS):
                row.append("        .")
                continue
            heard = e >= 0.25 * rest
            row.append(f"{100 * e[heard].sum() / e.sum():9.0f}")
        print(f"{t['name']:10s}" + "".join(row))


def stems() -> None:
    for t in P.TRACKS:
        path = RENDERS / "stems" / f"stem-{t['name']}.wav"
        if not path.exists():
            print(f"{t['name']:10s} (no stem)")
            continue
        x = load(path)
        b = bands(x)
        phone = round(100 - b["sub<60"] - b["low60-180"], 1)
        line = f"{t['name']:10s} {lufs(path):6.1f} LUFS  peak {20 * np.log10(np.abs(x).max() + 1e-12):5.1f}  {b}  phone {phone}%"
        if t["name"] in PITCHED:
            line += "  " + pitch_check(t["name"], x)
        print(line)


def mix(path: Path) -> None:
    x = load(path)
    print(path.name, f"{lufs(path):.1f} LUFS integrated", bands(x))
    for name, bars, _ in P.SECTIONS:
        s = P.START[name] * SPB
        print(f"  {name:9s} bars {int(P.START[name] // 4) + 1:3d}-{int(P.START[name] // 4) + bars:3d}  "
              f"{lufs(path, s, bars * 4 * SPB):6.1f} LUFS")


def pic(path: Path) -> Path:
    out = path.with_suffix(".png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-lavfi",
                    "showspectrumpic=s=1600x600:legend=1:scale=log:fscale=log:stop=8000", str(out)], check=True)
    return out


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    wav = Path(rest[0]) if rest and not rest[0].startswith("--") else RENDERS / "marrow-cumbia.wav"
    if cmd == "stems":
        stems()
    elif cmd == "chroma":
        chroma_sections()
    elif cmd == "masking":
        masking(phone="--phone" in rest)
    elif cmd == "mix":
        mix(wav)
    elif cmd == "pic":
        print(pic(wav))
    else:
        print(__doc__)
