"""Checks and cuts on rendered audio, offline.

- check_audio: is a render there, finite, the right length and not silent? A Live with no audio
  clock, or a muted range, renders silence without any error, so every render is checked.
- slice_render: cut a packed render (hands.probe_kit) into one file per pattern.
- trim_take, best_lag, low_band, timeline_check: real-time takes (hands.live.record) start
  ~0.9 s off the song timeline; trim them at song beat 0 and check they stay on it.

Silence is judged by RMS, not loudness: loudness decisions use mlab.loudness (ears/mlab), the one
calibrated meter, and this only has to catch a render that did not happen.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

SILENCE_DB = -240.0


class AudioError(RuntimeError):
    """A render is unusable: unreadable, not finite, the wrong length, or silent."""


def _db(x: float) -> float:
    return float(20 * np.log10(x)) if x > 0 else SILENCE_DB


def stats(path: str | Path) -> dict:
    """Seconds, sample rate, channels, sample peak and RMS (dBFS), and whether all samples are finite."""
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    finite = bool(np.isfinite(x).all())
    level = x if finite else np.nan_to_num(x)
    return {"seconds": len(x) / sr, "sample_rate": sr, "channels": x.shape[1],
            "peak_dbfs": _db(float(np.max(np.abs(level), initial=0.0))),
            "rms_dbfs": _db(float(np.sqrt(np.mean(level ** 2)))) if len(x) else SILENCE_DB,
            "finite": finite}


def check_audio(path: str | Path, *, seconds: float, tol_s: float = 0.05, min_rms_dbfs: float = -60.0) -> dict:
    """Raise AudioError unless the file reads, is finite, lasts `seconds` (within tol_s) and its
    RMS is above min_rms_dbfs; return its stats."""
    try:
        s = stats(path)
    except (RuntimeError, OSError) as exc:  # soundfile's LibsndfileError is a RuntimeError
        raise AudioError(f"{path}: unreadable ({exc})") from exc
    if not s["finite"]:
        raise AudioError(f"{path}: has NaN or infinite samples")
    if abs(s["seconds"] - seconds) > tol_s:
        raise AudioError(f"{path}: {s['seconds']:.3f} s long, expected {seconds:.3f} s")
    if s["rms_dbfs"] < min_rms_dbfs:
        raise AudioError(f"{path}: silent (RMS {s['rms_dbfs']:.1f} dBFS < {min_rms_dbfs:g})")
    return s


def slice_render(path: str | Path, cuts_s: Sequence[float], out_dir: str | Path, *,
                 pattern: str = "pattern_{:02d}.wav", short_s: float = 0.01) -> list[Path]:
    """Cut a render into the pieces [cuts_s[k], cuts_s[k + 1]) and write each as 32-bit float WAV.

    The render may end up to `short_s` before the last cut (the last piece is then that much
    shorter); ending earlier means it is not the render the cuts were planned for.
    """
    x, sr = sf.read(path, always_2d=True, dtype="float32")
    edges = [int(t * sr) for t in cuts_s]
    if edges != sorted(edges):
        raise ValueError(f"cuts must increase: {list(cuts_s)}")
    if edges[-1] > len(x) + short_s * sr:
        raise AudioError(f"{path}: ends at {len(x) / sr:.3f} s, before the last cut at {cuts_s[-1]:.3f} s")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for k, (a, b) in enumerate(itertools.pairwise(edges)):
        files.append(out_dir / pattern.format(k))
        sf.write(files[-1], x[a:b], sr, subtype="FLOAT")
    return files


def trim_take(take: str | Path, *, lead_beats: float, length_beats: float,
              fade_in_s: float = 0.01, fade_out_s: float = 0.03) -> tuple[np.ndarray, int]:
    """The part of a real-time take from song beat `lead_beats` for `length_beats`, with short fades.

    Where song beat 0 sits in the take comes from <take>.timing.json, which record_arrangement
    writes from Live's own clip markers: it varies per take (0 s or ~0.9 s), and correlating the
    audio cannot find it reliably in a periodic low band.
    """
    timing = json.loads(Path(f"{take}.timing.json").read_text())
    x, sr = sf.read(take, always_2d=True, dtype="float64")
    spb = 60.0 / timing["tempo"]
    start = int(round(timing["song_zero_seconds"] * sr)) + int(lead_beats * spb * sr)
    y = x[start:start + int(round(length_beats * spb * sr))].copy()
    fi, fo = int(fade_in_s * sr), int(fade_out_s * sr)
    y[:fi] *= np.linspace(0, 1, fi)[:, None]
    y[len(y) - fo:] *= np.linspace(1, 0, fo)[:, None]
    return y, sr


def best_lag(a: np.ndarray, b: np.ndarray, center: int, span: int) -> tuple[int, float]:
    """Where `a` best matches `b` near `center` (within ±span samples): (lag in samples,
    normalised correlation). Mono arrays; b must reach center + span + len(a)."""
    lo = max(0, center - span)
    seg = b[lo:center + span + len(a)]
    n = len(seg) - len(a) + 1
    size = 1 << (len(seg) + len(a)).bit_length()
    corr = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(a, size)), size)[:n]
    energy = np.concatenate([[0.0], np.cumsum(seg * seg)])
    norm = np.sqrt(np.sum(a * a)) * np.sqrt(np.maximum(energy[len(a):] - energy[:n], 0.0))
    r = corr / (norm + 1e-12)
    k = int(np.argmax(r))
    return lo + k - center, float(r[k])


def low_band(x: np.ndarray, sr: int, hz: float = 150.0) -> np.ndarray:
    """Mono, zero-phase low-pass of x: the kick and bass, where a rewritten part (hats) cannot
    make a timeline check fail."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    spectrum = np.fft.rfft(mono)
    spectrum[np.fft.rfftfreq(len(mono), 1 / sr) > hz] = 0
    return np.fft.irfft(spectrum, len(mono))


def timeline_check(take: np.ndarray, reference: np.ndarray, sr: int, *, window_s: float = 0.25,
                   span_s: float = 0.15, jump_s: float = 0.035, min_corr: float = 0.6,
                   skip: Callable[[float], bool] | None = None) -> dict:
    """Does a take stay on its reference's timeline? Lags of consecutive windows against it.

    `take` and `reference` are mono and aligned at sample 0. Each window of the take is matched
    within ±span_s of the same place in the reference. A slip or stutter moves consecutive windows
    off the median lag by more than jump_s; one stray window with a weak match (corr < min_corr,
    e.g. between kick hits) is ambiguity, not a jump. `skip(t)` drops the window starting at t
    seconds (cuts, breakdowns). ok: no jumps and the median lag within 5 ms.
    """
    win, span = int(window_s * sr), int(span_s * sr)
    found = [best_lag(take[s:s + win], reference, s, span) for s in range(0, len(take) - 2 * win, win)]
    lags = np.array([lag / sr for lag, _ in found])
    corrs = np.array([c for _, c in found])
    median = float(np.median(lags))
    off = [i for i in np.flatnonzero(np.abs(lags - median) > jump_s) if not (skip and skip(i * window_s))]
    near = set(off)
    jumps = [round(i * window_s, 2) for i in off if i - 1 in near or i + 1 in near or corrs[i] >= min_corr]
    return {"median_lag_s": median, "jumps_s": jumps, "ok": not jumps and abs(median) <= 0.005}
