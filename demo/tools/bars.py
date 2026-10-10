"""Per-bar energy map of a 160 BPM render whose bar 1 starts at t=0.

Prints, for every bar: overall RMS, sub/kick band (<120 Hz), mids (1-3.2 kHz)
and highs (>5 kHz), in dB. Used to pick the sections of the edit.
"""
import subprocess
import sys

import numpy as np

SR = 44100
BAR = 60 / 160 * 4  # seconds


def load(path: str) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def band_db(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    m = (freqs >= lo) & (freqs < hi)
    return 10 * np.log10(spec[m].sum() + 1e-12)


def main(path: str) -> None:
    x = load(path)
    n = int(BAR * SR)
    bars = len(x) // n
    print("bar   t(s)    rms   sub   mid   hi")
    for b in range(bars):
        seg = x[b * n:(b + 1) * n]
        rms = 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        freqs = np.fft.rfftfreq(len(seg), 1 / SR)
        print(f"{b + 1:3d} {b * BAR:6.1f} {rms:6.1f} {band_db(spec, freqs, 20, 120):5.0f}"
              f" {band_db(spec, freqs, 1000, 3200):5.0f} {band_db(spec, freqs, 5000, 16000):5.0f}")


if __name__ == "__main__":
    main(sys.argv[1])
