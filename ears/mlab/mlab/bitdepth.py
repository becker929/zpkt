"""Word length and dither forensics (subject 1: Ch. 15).

Answers, for a file:
- What container is it (PCM_16, PCM_24, FLOAT)?
- How many bits does the audio actually use? (a 24-bit file can hold 16-bit audio)
- Is there a dither noise floor, and is it flat or noise-shaped?
- Is there DC offset?

Reference noise floors for N-bit quantisation of full scale +/-1 (q = 2^(1-N)):
  rounding error only (no dither): q/sqrt(12) rms  -> 16 bit: -101.1 dBFS
  RPDF dither + rounding:           q/sqrt(6)       -> 16 bit:  -98.1 dBFS
  TPDF dither + rounding:           q/2             -> 16 bit:  -96.3 dBFS
"""
from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy import signal

from .util import db, dc_is_real, dc_offset_db, pdb, r, rms


def theoretical_floor_dbfs(bits, dither="tpdf"):
    q = 2.0 ** (1 - bits)
    k = {"none": np.sqrt(12), "rpdf": np.sqrt(6), "tpdf": 2.0}[dither]
    return float(db(q / k))


def effective_bits(x: np.ndarray, max_bits=32) -> int:
    """Smallest N such that every sample is a multiple of 2^(1-N) (full scale +/-1).
    32 means 'more than 24 bits of resolution used' (true float content)."""
    v = x[np.abs(x) > 0]
    if v.size == 0:
        return 0
    v = v[: 2_000_000]
    for n in range(1, max_bits + 1):
        s = v * 2.0 ** (n - 1)
        if np.all(np.abs(s - np.round(s)) < 1e-6 * np.maximum(1, np.abs(s)) + 1e-9):
            return n
    return max_bits


def quiet_blocks(x, sr, block_s=0.1, n=20):
    """RMS (dBFS) of the quietest non-silent blocks, and how many blocks are digital zero."""
    b = int(block_s * sr)
    k = len(x) // b
    if k == 0:
        return np.array([]), 0
    blocks = x[:k * b].reshape(k, b, -1)
    lv = db(np.sqrt(np.mean(blocks ** 2, axis=(1, 2))))
    zero = int(np.sum(np.all(blocks == 0, axis=(1, 2))))
    nz = np.sort(lv[lv > -300])
    return nz[:n], zero


def noise_shape_tilt(x, sr, mask):
    """High (>15 kHz) minus low (1-5 kHz) spectral density in the given samples, dB.
    Flat TPDF ~ 0 dB; noise-shaped dither is strongly positive (often +10..+30)."""
    seg = x[mask]
    if len(seg) < 4096 or sr < 36000:
        return None
    f, p = signal.welch(seg.mean(axis=1), sr, nperseg=4096)
    lo = p[(f > 1000) & (f < 5000)].mean()
    hi = p[(f > 15000) & (f < min(20000, sr / 2 * 0.95))].mean()
    return float(pdb(hi) - pdb(lo))


def analyze(audio) -> dict:
    x, sr = audio.x, audio.sr
    out = {"container": audio.subtype, "sample_rate": sr, "lossy": audio.lossy}
    if audio.lossy:
        out["verdict"] = ("lossy file: word length and dither are not observable after "
                          "perceptual coding. Measure the WAV you exported instead.")
        out["dc_offset_dbfs"] = [r(v) for v in dc_offset_db(x, sr)]
        out["dc_max_dbfs"] = max(out["dc_offset_dbfs"])
        out["dc_steady"] = dc_is_real(x, sr)
        q, zeros = quiet_blocks(x, sr)
        out["digital_zero_blocks_100ms"] = zeros
        if q.size:
            out["quietest_blocks_dbfs"] = r(float(np.median(q)))
        return out
    eb = effective_bits(x)
    out["effective_bits"] = eb
    if eb == 0:
        out["verdict"] = "digital silence: nothing to analyse"
        out["dc_offset_dbfs"] = [None] * x.shape[1]
        out["dc_max_dbfs"] = None
        return out
    out["dc_offset_dbfs"] = [r(v) for v in dc_offset_db(x, sr)]
    out["dc_steady"] = dc_is_real(x, sr)
    out["dc_max_dbfs"] = max(out["dc_offset_dbfs"])
    q, zeros = quiet_blocks(x, sr)
    out["digital_zero_blocks_100ms"] = zeros
    if q.size:
        out["quietest_blocks_dbfs"] = r(float(np.median(q)))
    bits_for_ref = eb if 8 <= eb <= 24 else (24 if "24" in audio.subtype else 16)
    refs = {d: r(theoretical_floor_dbfs(bits_for_ref, d)) for d in ("none", "rpdf", "tpdf")}
    out["reference_floors_dbfs_at_%d_bits" % bits_for_ref] = refs
    # tilt measured on the quietest 10 % of 100 ms blocks (where only the floor remains)
    b = int(0.1 * sr)
    k = len(x) // b
    if k >= 10 and q.size:
        lv = db(np.sqrt(np.mean(x[:k * b].reshape(k, b, -1) ** 2, axis=(1, 2))))
        thr = np.percentile(lv[lv > -300], 10) if np.any(lv > -300) else -300
        mask = np.zeros(len(x), bool)
        for i in np.where((lv <= thr) & (lv > -300))[0]:
            mask[i * b:(i + 1) * b] = True
        out["quiet_region_tilt_db"] = r(noise_shape_tilt(x, sr, mask))
    out["verdict"] = _verdict(out, eb, audio.subtype)
    return out


def _verdict(o, eb, subtype):
    msgs = []
    if "FLOAT" in subtype and eb <= 24:
        msgs.append(f"float container holding {eb}-bit values: something upstream reduced word length")
    if "PCM_24" in subtype and eb <= 16:
        msgs.append("24-bit container holding 16-bit audio: re-exported from a 16-bit source?")
    q = o.get("quietest_blocks_dbfs")
    if q is not None and eb in (16, 24):
        tp = theoretical_floor_dbfs(eb, "tpdf")
        tilt = o.get("quiet_region_tilt_db")
        if o["digital_zero_blocks_100ms"] > 0 and q > tp + 20:
            msgs.append("digital silence present and no floor elsewhere: undithered, or dither gated in silence")
        elif abs(q - tp) < 3:
            msgs.append("quietest passages sit at the TPDF floor: dither likely present"
                        + (" and noise-shaped" if tilt and tilt > 8 else ""))
        elif q > tp + 3:
            msgs.append("programme never gets quiet enough to see the floor: dither not observable (masked)")
        else:
            msgs.append("floor below TPDF level: no dither, or rounding only")
    dc = max(o["dc_offset_dbfs"])
    if dc > -60 and o.get("dc_steady", True):
        msgs.append(f"DC offset {dc} dBFS: high-pass or DC-block before mastering")
    return "; ".join(msgs) or "nothing notable"


def truncation_distortion(original, reduced, sr, f0, tail_s=2.0):
    """Share of the reduction error at harmonics of f0 (dB re total error).
    Undithered truncation/rounding of a tone concentrates error at harmonics
    (correlated distortion); dither spreads it into noise (lower share)."""
    e = (reduced - original).mean(axis=1)[-int(tail_s * sr):]   # the quiet end, near the LSB
    e = e - e.mean()                                             # truncation's DC bias is not distortion
    w = np.hanning(len(e))
    S = np.abs(np.fft.rfft(e * w)) ** 2
    f = np.fft.rfftfreq(len(e), 1 / sr)
    harm = sum(S[np.abs(f - h * f0) < 3 * sr / len(e) + 1].sum() for h in range(2, 40) if h * f0 < sr / 2)
    return float(pdb(harm / max(S.sum(), 1e-30)))


def read_int_codes(path):
    """Raw integer samples of a PCM file (for histogram-level forensics)."""
    inf = sf.info(path)
    dt = {"PCM_16": "int16", "PCM_24": "int32", "PCM_32": "int32"}.get(inf.subtype)
    if not dt:
        return None
    x, _ = sf.read(path, dtype=dt, always_2d=True)
    return x >> 8 if inf.subtype == "PCM_24" else x
