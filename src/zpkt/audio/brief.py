"""A short measurement of an audio file: about twenty numbers, for a reader that must not load the audio.

An agent that bounced a track wants to know how loud it is, where its energy sits and how it moves over time, and it
must learn that from a few numbers: a WAV read into a conversation is megabytes of nothing. Three views, each of a
window of the file in seconds:

- `brief`: loudness (LUFS), true peak, sample peak, RMS, crest, the five bands the Monitor tab shows, and for stereo
  the correlation and the width.
- `spectrum`: the level of each third octave from 25 Hz to 16 kHz.
- `over_time`: RMS and peak of each step (a bar, a second), so a build, a drop or a dropout shows.

`difference` takes one result from another, number by number. Levels are dB relative to full scale, rounded to 0.1.
The band levels are parts of the RMS: their powers add up to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from zpkt.audio.loudness import true_peak_dbtp

# The Monitor tab's five bands (zpkt.app's page, MON_BANDS): name, from Hz, to Hz (None: to the top).
BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("sub", 0.0, 60.0),
    ("low", 60.0, 250.0),
    ("mid", 250.0, 2000.0),
    ("high", 2000.0, 6000.0),
    ("air", 6000.0, None),
)
THIRD_OCTAVES: tuple[float, ...] = (
    25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150,
    4000, 5000, 6300, 8000, 10000, 12500, 16000,
)  # fmt: skip
SILENCE_DB = -120.0
SILENT_BELOW_DB = -60.0  # an RMS under this is a silent render: the usual sign that the wrong thing was bounced
MAX_SECONDS = 1200.0  # one window; longer is measured in parts
MAX_STEPS = 64  # rows of over_time
NFFT = 16384


class BriefError(ValueError):
    """The file or the window cannot be measured; the message says why."""


def _db(power: float) -> float:
    return round(10.0 * float(np.log10(power)), 1) if power > 1e-12 else SILENCE_DB


def _amp_db(amp: float) -> float:
    return round(20.0 * float(np.log10(amp)), 1) if amp > 1e-6 else SILENCE_DB


def read(path: str | Path, start_s: float = 0.0, end_s: float | None = None) -> tuple[np.ndarray, int]:
    """The window [start_s, end_s) of the file as (frames, channels) floats, and its sample rate."""
    try:
        with sf.SoundFile(str(path)) as f:
            sr, frames = int(f.samplerate), int(f.frames)
            first = round(float(start_s) * sr)
            last = frames if end_s is None else min(frames, round(float(end_s) * sr))
            if not 0 <= first < last:
                raise BriefError(
                    f"{Path(path).name} is {frames / sr:.2f} s long: the window {start_s:g} to "
                    f"{'its end' if end_s is None else format(end_s, 'g')} s holds nothing"
                )
            if (last - first) / sr > MAX_SECONDS:
                raise BriefError(f"a window is at most {MAX_SECONDS:g} s; measure {Path(path).name} in parts")
            f.seek(first)
            x = f.read(last - first, dtype="float64", always_2d=True)
    except (RuntimeError, OSError) as exc:  # soundfile's own error is a RuntimeError
        raise BriefError(f"{Path(path).name}: not an audio file that can be read ({str(exc)[:80]})") from exc
    return np.nan_to_num(x), sr


def _powers(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """(frequencies, power in each): the mean over the channels, in parts that add up to the mean square."""
    n = len(x)
    pad = (-n) % NFFT
    padded = np.pad(x, ((0, pad), (0, 0))) if pad else x
    chunks = padded.T.reshape(x.shape[1], -1, NFFT)
    spec = np.abs(np.fft.rfft(chunks, axis=2)) ** 2
    spec[:, :, 1:-1] *= 2.0  # one side stands for both
    power = spec.sum(axis=1).mean(axis=0) / (NFFT * n)
    return np.fft.rfftfreq(NFFT, 1.0 / sr), power


def _lufs(x: np.ndarray, sr: int) -> float | None:
    if len(x) < 0.5 * sr:  # the meter needs a 400 ms block
        return None
    try:
        import pyloudnorm

        v = float(pyloudnorm.Meter(sr).integrated_loudness(x if x.shape[1] > 1 else x[:, 0]))
    except Exception:  # a meter that cannot say leaves the field empty; the other numbers stand
        return None
    return round(v, 1) if np.isfinite(v) else None


def brief(path: str | Path, start_s: float = 0.0, end_s: float | None = None) -> dict[str, Any]:
    """The short sheet of a window of the file."""
    x, sr = read(path, start_s, end_s)
    mean_square = float(np.mean(x**2))
    peak = float(np.max(np.abs(x)))
    freqs, power = _powers(x, sr)
    out: dict[str, Any] = {
        "seconds": round(len(x) / sr, 2),
        "lufs": _lufs(x, sr),
        "true_peak_db": None if (tp := true_peak_dbtp(x, sr)) is None else round(float(tp), 1),
        "peak_db": _amp_db(peak),
        "rms_db": _db(mean_square),
        "crest_db": round(_amp_db(peak) - _db(mean_square), 1) if peak > 1e-6 else 0.0,
        "bands_db": {
            name: _db(float(power[(freqs >= lo) & (freqs < (hi if hi is not None else 1e12))].sum()))
            for name, lo, hi in BANDS
        },
    }
    if x.shape[1] == 2:
        left, right = x[:, 0], x[:, 1]
        both = float(np.sqrt(np.sum(left**2) * np.sum(right**2)))
        mid, side = float(np.mean(((left + right) / 2) ** 2)), float(np.mean(((left - right) / 2) ** 2))
        out["stereo"] = {
            "correlation": round(float(np.sum(left * right)) / both, 2) if both > 1e-12 else 0.0,
            "side_vs_mid_db": round(_db(side) - _db(mid), 1) if mid > 1e-12 and side > 1e-12 else SILENCE_DB,
        }
    else:
        out["channels"] = int(x.shape[1])
    if out["rms_db"] < SILENT_BELOW_DB:
        out["silent"] = True
    return out


def spectrum(path: str | Path, start_s: float = 0.0, end_s: float | None = None) -> dict[str, float]:
    """The level of each third octave, {"25": dB, ..., "16000": dB}."""
    x, sr = read(path, start_s, end_s)
    freqs, power = _powers(x, sr)
    edge = 2.0 ** (1.0 / 6.0)
    return {
        f"{c:g}": _db(float(power[(freqs >= c / edge) & (freqs < c * edge)].sum()))
        for c in THIRD_OCTAVES
        if c * edge < sr / 2
    }


def over_time(
    path: str | Path, step_s: float, start_s: float = 0.0, end_s: float | None = None
) -> dict[str, list[float]]:
    """RMS and peak of each step of `step_s` seconds: {"rms_db": [...], "peak_db": [...]}. The last step may be
    short; at most MAX_STEPS steps (the caller makes the step longer)."""
    if not step_s > 0:
        raise BriefError("a step is longer than nothing")
    x, sr = read(path, start_s, end_s)
    size = max(1, round(step_s * sr))
    count = -(-len(x) // size)
    if len(x) - (count - 1) * size < size // 100:  # a few stray samples after the last whole step are not a step
        count -= 1
    if count > MAX_STEPS:
        raise BriefError(f"{count} steps: at most {MAX_STEPS} (make the step longer or the window shorter)")
    rms, peaks = [], []
    for i in range(count):
        part = x[i * size : (i + 1) * size]
        rms.append(_db(float(np.mean(part**2))))
        peaks.append(_amp_db(float(np.max(np.abs(part)))))
    return {"rms_db": rms, "peak_db": peaks}


def difference(a: Any, b: Any) -> Any:
    """`a` minus `b`, number by number, for what both hold (dicts and lists of the same shape); the rest is left
    out. Seconds and flags are not levels and are left out too."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = {
            k: d
            for k in a
            if k in b and k not in ("seconds", "silent", "channels")
            for d in [difference(a[k], b[k])]
            if d is not None
        }
        return out or None
    if isinstance(a, list) and isinstance(b, list):
        return [difference(p, q) for p, q in zip(a, b, strict=False)] if len(a) == len(b) else None
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(float(a) - float(b), 2)
    return None


__all__ = ["BANDS", "MAX_STEPS", "THIRD_OCTAVES", "BriefError", "brief", "difference", "over_time", "read", "spectrum"]
