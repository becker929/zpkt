"""Shared helpers for the learn-tutorial scripts: audio input, band filters, the onset detector,
note names and musical positions.

The onset detector is the one every audio script uses (onsets, anchor, measure_render) and the one
selftest.py calibrates. It finds a jump in band energy: for every sample, the power of the band's
envelope over `half_ms` after it against the power over `half_ms` before it. A step in energy
peaks at the sample where it happens, so there is no STFT frame offset to correct. Run 1 lost a
version to such an offset (a spectral-flux frame index runs about 21 ms ahead of its onset).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Bands for "label every strong onset class": kick/bass bodies, claps/snares/hand drums, hats/shakers.
BANDS = {"low": (30.0, 200.0), "mid": (400.0, 3000.0), "high": (3000.0, 16000.0)}
# Half-window per band: long enough to smooth the envelope of its lowest frequencies.
HALF_MS = {"low": 5.0, "mid": 3.0, "high": 2.0, "full": 2.0}


def read_audio(path: str | Path, mono: bool = True) -> tuple[np.ndarray, int]:
    """Float64 samples and the sample rate. Mono is the mean of the channels."""
    import soundfile as sf

    x, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return (x.mean(axis=1) if mono else x), int(sr)


def parse_band(text: str) -> tuple[str, float | None, float | None]:
    """'low' | 'mid' | 'high' | 'full' | 'NAME=LO-HI' (Hz; an empty side is open)."""
    if text in BANDS:
        return text, *BANDS[text]
    if text == "full":
        return "full", None, None
    name, _, rng = text.partition("=")
    lo, _, hi = (rng or name).partition("-")
    return (name if rng else text), (float(lo) if lo else None), (float(hi) if hi else None)


def band(x: np.ndarray, sr: int, lo: float | None = None, hi: float | None = None, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth band-, low- or high-pass (sosfiltfilt: no time shift)."""
    from scipy import signal

    if hi is not None and hi >= 0.95 * sr / 2:
        hi = None
    if lo and hi:
        sos = signal.butter(order, [lo, hi], "band", fs=sr, output="sos")
    elif lo:
        sos = signal.butter(order, lo, "high", fs=sr, output="sos")
    elif hi:
        sos = signal.butter(order, hi, "low", fs=sr, output="sos")
    else:
        return x
    return signal.sosfiltfilt(sos, x, axis=0)


def envelope(y: np.ndarray) -> np.ndarray:
    """Magnitude of the analytic signal: smooth for a tone, so its power does not ripple at 2f."""
    from scipy import fft, signal

    n = len(y)
    return np.abs(signal.hilbert(y, fft.next_fast_len(n))[:n])


def jump_curve(y: np.ndarray, sr: int, half_ms: float, before_ms: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(after, before): mean envelope power over half_ms after every sample and over before_ms
    (default 4 x half_ms) before it. The longer 'before' keeps flicker inside a decaying tail from
    reading as a new onset; the short 'after' keeps the timing sharp."""
    p = envelope(y) ** 2
    h = max(1, int(round(half_ms * sr / 1000)))
    hb = max(1, int(round((before_ms or 4 * half_ms) * sr / 1000)))
    c = np.concatenate([[0.0], np.cumsum(p)])
    i = np.arange(len(p))
    after = (c[np.minimum(i + h, len(p))] - c[i]) / h
    before = (c[i] - c[np.maximum(i - hb, 0)]) / hb
    return after, before


def detect_onsets(y: np.ndarray, sr: int, *, half_ms: float = 3.0, min_jump_db: float = 10.0,
                  floor_db: float = -45.0, min_gap_ms: float = 50.0, local_gate_db: float = 12.0) -> list[dict]:
    """Onsets in an already band-passed signal: [{t, jump_db, level_db}], sorted by time.

    level_db is the after-window power in dBFS. Two gates keep flicker out: the after-window must
    be within floor_db of the loudest one in the file (noise-floor ratios are big out of nothing),
    and within local_gate_db of the loudest one in the next 60 ms (a filter's pre-ringing before a
    loud hit is not an onset).
    """
    from scipy import ndimage, signal

    after, before = jump_curve(y, sr, half_ms)
    level = 10 * np.log10(after + 1e-15)
    floor = level.max() + floor_db
    tiny = 10 ** ((floor - 20) / 10)
    jump = 10 * np.log10((after + tiny) / (before + tiny))
    w = max(1, int(0.06 * sr))
    ahead = ndimage.maximum_filter1d(after, size=w, origin=-(w // 2), mode="nearest")
    ok = (level >= floor) & (after >= ahead * 10 ** (-local_gate_db / 10))
    score = np.where(ok, jump, 0.0)
    peaks, _ = signal.find_peaks(score, height=min_jump_db, distance=max(1, int(min_gap_ms * sr / 1000)))
    return [{"t": float(k / sr), "jump_db": float(jump[k]), "level_db": float(level[k])} for k in peaks]


def best_jump_near(after: np.ndarray, before: np.ndarray, sr: int, t: float, win_ms: float = 25.0,
                   gate_db: float = -20.0) -> tuple[float, float, float]:
    """The strongest energy jump within +-win_ms of t: (time s, jump dB, after-level dBFS).

    Only points whose after-power is within gate_db of the local peak count, so a quiet
    flicker just before a loud hit cannot win. Returns (t, 0, level) when nothing qualifies.
    """
    a = max(1, int((t - win_ms / 1000) * sr))
    b = min(len(after) - 1, int((t + win_ms / 1000) * sr))
    if b <= a:
        return t, 0.0, -150.0
    seg_a, seg_b = after[a:b], before[a:b]
    peak = seg_a.max()
    ok = seg_a >= peak * 10 ** (gate_db / 10)
    ratio = np.where(ok, (seg_a + 1e-15) / (seg_b + 1e-15), 0.0)
    k = int(np.argmax(ratio))
    return (a + k) / sr, float(10 * np.log10(max(ratio[k], 1e-15))), float(10 * np.log10(seg_a[k] + 1e-15))


def rms_db(x: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(np.square(x)) + 1e-15)) if len(x) else -150.0


def hz_to_midi(f: float) -> float:
    return 69 + 12 * math.log2(f / 440.0)


def midi_to_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def note_names(midi: int) -> dict:
    """Both naming conventions: Live calls MIDI 60 C3, scientific pitch calls it C4."""
    n = NOTES[midi % 12]
    return {"midi": midi, "live": f"{n}{midi // 12 - 2}", "sci": f"{n}{midi // 12 - 1}"}


def describe_hz(f: float) -> dict:
    """{hz, midi, cents, live, sci} for a frequency."""
    m = hz_to_midi(f)
    k = int(round(m))
    return {"hz": round(f, 2), **note_names(k), "cents": round(100 * (m - k))}


def position(beat: float, start_bar: int = 1, beats_per_bar: int = 4) -> str:
    """Live's bar.beat.sixteenth for a beat counted from 0 at start_bar (quarter-note beats).

    Off the 16th grid the remainder is appended in 16ths, e.g. '1.2.3+0.40'.
    """
    bar = start_bar + int(beat // beats_per_bar)
    in_bar = beat - (bar - start_bar) * beats_per_bar
    q = int(in_bar // 1)
    s16 = (in_bar - q) * 4
    k = int(math.floor(s16 + 1e-6))
    rest = s16 - k
    pos = f"{bar}.{q + 1}.{k + 1}"
    return pos if rest < 1e-3 else f"{pos}+{rest:.2f}"


def write_json(path: str | Path, obj) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def fmt_time(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"
