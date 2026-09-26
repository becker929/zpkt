"""What a platform does to a master (subjects 5 and 6).

PLATFORMS values are loudness-normalisation targets as publicly reported.
Source tiers matter here: YouTube publishes no spec. The -14 LUFS,
turn-down-only behaviour is observed ("Stats for nerds": content loudness)
and reported by engineers (tier 4-6). Treat it as a working assumption and
re-check with a real upload (see guides/youtube-short-delivery.md).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf

from . import loudness as L
from .util import db, r

PLATFORMS = {
    # name: (target LUFS, turns quiet content up?, note)
    "youtube":       (-14.0, False, "observed; applies to uploads incl. Shorts (assumed)"),
    "spotify":       (-14.0, True,  "documented by Spotify; up-gain limited by peak headroom"),
    "apple_music":   (-16.0, True,  "Sound Check; reported"),
    "tidal":         (-14.0, False, "reported"),
    "amazon_music":  (-14.0, False, "reported, varies"),
    "soundcloud":    (None,  False, "no normalisation reported"),
    "instagram":     (None,  False, "undocumented; measure a real upload"),
    "tiktok":        (None,  False, "undocumented; measure a real upload"),
}

CODECS = {
    # label: ffmpeg args. YouTube serves AAC-LC ~128 kb/s (itag 140) and Opus ~130-160 kb/s (itag 251).
    "aac128": ["-c:a", "aac", "-b:a", "128k"],
    "opus160": ["-c:a", "libopus", "-b:a", "160k"],
    "mp3_320": ["-c:a", "libmp3lame", "-b:a", "320k"],
}
EXT = {"aac128": "m4a", "opus160": "opus", "mp3_320": "mp3"}


def normalization(integrated_lufs, true_peak_dbtp):
    rows = {}
    if not np.isfinite(integrated_lufs):
        return {name: {"gain_db": None, "playback_lufs": None, "playback_true_peak": None,
                       "note": "silent or too short to measure"} for name in PLATFORMS}
    for name, (target, up, note) in PLATFORMS.items():
        if target is None:
            rows[name] = {"gain_db": 0.0, "playback_lufs": r(integrated_lufs),
                          "playback_true_peak": r(true_peak_dbtp), "note": note}
            continue
        g = target - integrated_lufs
        if g > 0 and not up:
            g = 0.0
        if g > 0 and up:   # platforms that turn up generally will not push peaks past ~-1 dBTP
            g = min(g, max(0.0, -1.0 - true_peak_dbtp))
        rows[name] = {"gain_db": r(g), "playback_lufs": r(integrated_lufs + g),
                      "playback_true_peak": r(true_peak_dbtp + g), "note": note}
    return rows


def codec_available(label):
    if not shutil.which("ffmpeg"):
        return False
    enc = CODECS[label][1]
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return f" {enc} " in out


def roundtrip(x, sr, label, keep_dir=None, name="master"):
    """Encode then decode with ffmpeg. Returns decoded float array (n, ch) at sr."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.wav")
        sf.write(src, x, sr, subtype="FLOAT")
        enc = os.path.join(keep_dir or d, f"{name}.{EXT[label]}")
        dec = os.path.join(d, "dec.wav")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, *CODECS[label], enc], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", enc, "-ar", str(sr),
                        "-c:a", "pcm_f32le", dec], check=True)
        y, _ = sf.read(dec, dtype="float64", always_2d=True)
    return _align_len(x, y)


def _align_len(x, y):
    """Codecs add priming delay. Find it by cross-correlation and trim."""
    from scipy import signal
    n = min(len(x), len(y), 200000)
    a, b = x[:n].mean(axis=1), y[:n].mean(axis=1)
    c = signal.correlate(b, a, mode="full", method="fft")
    lags = signal.correlation_lags(len(b), len(a), mode="full")
    m = np.abs(lags) < 5000
    lag = int(lags[m][np.argmax(c[m])])
    if lag > 0:
        y = y[lag:]
    return y[: len(x)]


def codec_report(x, sr, labels=("aac128", "opus160")):
    res = {}
    base_tp = L.true_peak(x, sr)
    base_i = L.integrated(x, sr)
    for lab in labels:
        if not codec_available(lab):
            res[lab] = {"skipped": "encoder not available in this ffmpeg"}
            continue
        y = roundtrip(x, sr, lab)
        tp = L.true_peak(y, sr)
        res[lab] = {"true_peak_after": r(tp), "true_peak_rise_db": r(tp - base_tp),
                    "samples_over_0dbfs": int(np.sum(np.abs(y) > 1.0)),
                    "integrated_after": r(L.integrated(y, sr)),
                    "integrated_change": r(L.integrated(y, sr) - base_i)}
    return res


def report(x, sr, lres=None, codecs=True):
    lres = lres or L.analyze(x, sr)
    out = {"integrated": r(lres.integrated), "true_peak": r(lres.true_peak),
           "normalization": normalization(lres.integrated, lres.true_peak)}
    if codecs:
        out["codec_roundtrip"] = codec_report(x, sr)
    yt = out["normalization"]["youtube"]
    advice = []
    if np.isfinite(lres.integrated) and lres.integrated > -14:
        advice.append(f"YouTube turns this down {abs(yt['gain_db'])} dB; loudness above -14 LUFS buys nothing there")
    if lres.true_peak > -1:
        advice.append("true peak above -1 dBTP: expect codec overs; lower the limiter ceiling")
    for lab, v in out.get("codec_roundtrip", {}).items():
        if v.get("samples_over_0dbfs", 0) > 0:
            advice.append(f"{lab}: {v['samples_over_0dbfs']} decoded samples clip")
    out["advice"] = advice
    return out
