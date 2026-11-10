"""What a render sounds like, as numbers and plain flags for the composer (measure.json).

No agent can listen, so the bot's one render-side revision round acts on these: a silent or clipped render, sections
that never change in level (v8's "flat and smooshed"), a low end that vanishes on a phone speaker. The meters are
ears' (pyloudnorm's BS.1770, a 4x oversampled true peak), kept small here so the booth needs no models.
"""

from __future__ import annotations

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

FLAGS = {
    "silent": "the render is silent",
    "clipping": "the true peak is over -0.5 dBTP",
    "too_quiet": "it is quieter than -20 LUFS even after the master",
    "no_contrast": "every section is within 1.5 LU of the others; nothing builds or drops",
    "lost_on_phone": "most of it is below 180 Hz, so a phone speaker plays little of it",
}


def highpass(y: np.ndarray, sr: int, hz: float) -> np.ndarray:
    """A brick-wall high-pass in the frequency domain: the phone model (a phone speaker gives almost nothing below
    150-200 Hz; SH001 round 3)."""
    spec = np.fft.rfft(y, axis=0)
    spec[np.fft.rfftfreq(len(y), 1 / sr) < hz] = 0
    return np.fft.irfft(spec, len(y), axis=0)


def true_peak_db(y: np.ndarray) -> float:
    n = len(y)
    up = np.zeros((n * 4, y.shape[1]))
    for c in range(y.shape[1]):
        spec = np.fft.rfft(y[:, c])
        up[:, c] = np.fft.irfft(spec, n * 4) * 4
    peak = float(np.max(np.abs(up))) if n else 0.0
    return 20 * np.log10(peak) if peak > 0 else -120.0


def measure(path, sections: list[tuple[str, float, float]]) -> dict:
    """`sections` are (label, start s, end s). Returns {lufs, true_peak_db, phone_db, sections: [...], flags: [...]}."""
    y, sr = sf.read(str(path), always_2d=True)
    meter = pyln.Meter(sr)
    rms = float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
    out: dict = {"seconds": round(len(y) / sr, 2), "sample_rate": sr}
    if rms < 1e-5:
        out.update(lufs=None, true_peak_db=None, phone_db=None, sections=[], flags=["silent"])
        return out
    lufs = float(meter.integrated_loudness(y))
    out["lufs"] = round(lufs, 1)
    out["true_peak_db"] = round(true_peak_db(y), 1)
    phone = highpass(y, sr, 180.0)
    out["phone_db"] = round(10 * np.log10((np.mean(phone ** 2) + 1e-12) / (np.mean(y ** 2) + 1e-12)), 1)
    secs = []
    for label, a, b in sections:
        seg = y[int(a * sr):int(b * sr)]
        level = float(meter.integrated_loudness(seg)) if len(seg) > sr * 0.5 else float("-inf")
        secs.append({"label": label, "start_s": round(a, 2), "end_s": round(b, 2),
                     "lufs": round(level, 1) if np.isfinite(level) else None})
    out["sections"] = secs
    flags = []
    if out["true_peak_db"] > -0.5:
        flags.append("clipping")
    if lufs < -20:
        flags.append("too_quiet")
    levels = [s["lufs"] for s in secs if s["lufs"] is not None]
    if len(levels) >= 2 and max(levels) - min(levels) < 1.5:
        flags.append("no_contrast")
    if out["phone_db"] < -10:
        flags.append("lost_on_phone")
    out["flags"] = flags
    return out


def levels(path, windows: list[tuple[float, float]]) -> list[tuple[float | None, float | None]]:
    """(LUFS, sample peak dBFS) of each (start s, end s) window; None for a silent one (`booth survey --listen`)."""
    y, sr = sf.read(str(path), always_2d=True)
    meter = pyln.Meter(sr)
    out = []
    for a, b in windows:
        seg = y[int(a * sr):int(b * sr)]
        peak = float(np.max(np.abs(seg))) if len(seg) else 0.0
        if peak < 1e-4 or len(seg) < sr * 0.5:
            out.append((None, None))
            continue
        lufs = float(meter.integrated_loudness(seg))
        out.append((round(lufs, 1) if np.isfinite(lufs) else None, round(20 * np.log10(peak), 1)))
    return out


def explain(flags: list[str]) -> list[str]:
    return [FLAGS[f] for f in flags if f in FLAGS]
