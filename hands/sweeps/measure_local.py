"""Provisional local measurer — a faithful, dependency-light stand-in for `ears`.

The real lab (`ears`) is not on this machine, so this fills the sweep's `measure`
column now. The `sub_share` / band-energy math is copied VERBATIM from the
canonical `ears` (`src/ears/loudness.py`: `BANDS`, `_band_energy`, and the
total-normalized `band_energy` dict) so the numbers match the lab, not a
reinvention. Extras (peak/rms/crest) are clearly non-canonical conveniences.

Interface matches what `assemble_curve.py` calls:
    <this> analyze <wav> --json   ->   prints one JSON object to stdout

When a real `ears` arrives, drop this and pass `--ears-cmd "ears"` instead.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np

# --- verbatim from ears/loudness.py -----------------------------------------
BANDS = {
    "sub":  (20,    150),
    "low":  (150,   600),
    "mid":  (600,   4000),
    "high": (4000,  12000),
    "air":  (12000, 20000),
}


def _band_energy(audio: np.ndarray, sr: int, lo: float, hi: float) -> float:
    n = len(audio)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    mask = (freqs >= lo) & (freqs < hi)
    return float(np.sum(spectrum[mask]))
# ----------------------------------------------------------------------------


def _load_mono(path: str) -> tuple[np.ndarray, int]:
    import soundfile as sf
    audio, sr = sf.read(path, always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float64), int(sr)


def measure(path: str) -> dict:
    audio, sr = _load_mono(path)

    # Canonical band shares (== ears band_energy).
    total = sum(_band_energy(audio, sr, lo, hi) for lo, hi in BANDS.values()) + 1e-10
    band_energy = {name: _band_energy(audio, sr, lo, hi) / total for name, (lo, hi) in BANDS.items()}

    # Non-canonical conveniences (transparent, clearly labelled).
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    crest_db = float(20.0 * math.log10(peak / rms)) if rms > 0 and peak > 0 else None

    return {
        "measurer": "measure_local (provisional; sub_share/band math == canonical ears)",
        "band_energy": band_energy,
        "sub_share": band_energy["sub"],
        "low_share": band_energy["low"],
        "mid_share": band_energy["mid"],
        "high_share": band_energy["high"],
        "air_share": band_energy["air"],
        "peak_dbfs": (float(20.0 * math.log10(peak)) if peak > 0 else None),
        "rms_dbfs": (float(20.0 * math.log10(rms)) if rms > 0 else None),
        "crest_db": crest_db,  # non-canonical
        "sample_rate": sr,
        "duration_seconds": float(len(audio) / sr) if sr else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="Measure one audio file and print JSON.")
    a.add_argument("wav")
    a.add_argument("--json", action="store_true", help="(always JSON; accepted for ears compatibility)")
    args = parser.parse_args()

    if args.cmd == "analyze":
        try:
            print(json.dumps(measure(args.wav)))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"error": str(exc)}))
            sys.exit(1)


if __name__ == "__main__":
    main()
