"""Premaster checklist (subject 4: Ch. 14).

Runs on the file you would hand to a mastering engineer (or to yourself).
Every check returns PASS / WARN / FAIL / INFO with the number behind it.
Thresholds live in CHECKS so a hypothesis can argue with them.
"""
from __future__ import annotations

import numpy as np

from . import loudness as L
from . import spectrum as S
from .util import db, dc_is_real, dc_offset_db, r, rms

CHECKS = {
    "min_bits": 24,                    # premaster should be 24-bit PCM or 32-bit float
    "peak_headroom_warn_dbfs": -1.0,   # sample peak above this: little room for mastering
    "peak_headroom_ideal_dbfs": -3.0,
    "clip_run": 3,                     # consecutive samples at |x| >= 0.9999 = clipped
    "plr_limited_db": 8.0,             # PLR under this looks already limited
    "dc_warn_dbfs": -60.0,
    "tail_warn_dbfs": -50.0,           # level of the last 10 ms: above = cut-off tail
    "head_warn_dbfs": -50.0,
    "low_corr_warn": 0.8,              # correlation 20-120 Hz under this: bass not mono
    "corr_fail": 0.0,
    "mono_loss_warn_lu": 3.0,          # LUFS drop when summed to mono
    "balance_warn_db": 1.5,
    "short_max_s": 180.0,              # YouTube Shorts length limit (3 min, since Oct 2024)
}


def _row(item, status, value, why):
    return {"check": item, "status": status, "value": value, "why": why}


def clip_runs(x, run=3, level=0.9999):
    hits = np.abs(x) >= level
    count = 0
    for c in range(x.shape[1]):
        h = hits[:, c].astype(np.int8)
        if not h.any():
            continue
        d = np.diff(np.concatenate([[0], h, [0]]))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        count += int(np.sum((ends - starts) >= run))
    return count


def run(audio, lres=None, checks=None):
    C = dict(CHECKS, **(checks or {}))
    x, sr = audio.x, audio.sr
    lres = lres or L.analyze(x, sr)
    rows = []
    if not np.isfinite(lres.integrated):
        rows.append(_row("audible_content", "FAIL", None, "silent, or shorter than 400 ms: nothing to master"))
    # format
    if audio.lossy:
        rows.append(_row("format", "FAIL", audio.subtype, "lossy file; premaster must be PCM or float"))
    elif "FLOAT" in audio.subtype or "24" in audio.subtype or "32" in audio.subtype:
        rows.append(_row("format", "PASS", audio.subtype, "24-bit or float keeps the noise floor out of the way"))
    else:
        rows.append(_row("format", "WARN", audio.subtype, "export 24-bit or 32-bit float; dither once, at the very end"))
    rows.append(_row("sample_rate", "INFO", sr, "keep the project rate; convert only at delivery"))
    # peaks
    sp = lres.sample_peak
    st = "FAIL" if sp >= -0.01 else ("WARN" if sp > C["peak_headroom_warn_dbfs"] else "PASS")
    rows.append(_row("sample_peak_dbfs", st, r(sp), f"leave headroom; {C['peak_headroom_ideal_dbfs']} dBFS or lower is comfortable"))
    rows.append(_row("true_peak_dbtp", "WARN" if lres.true_peak > 0 else "PASS", r(lres.true_peak),
                     "above 0 dBTP the premaster already has inter-sample overs"))
    n = clip_runs(x, C["clip_run"])
    rows.append(_row("clipped_runs", "FAIL" if n else "PASS", n, f"runs of >= {C['clip_run']} full-scale samples"))
    # already mastered?
    rows.append(_row("plr_db", "INFO" if not np.isfinite(lres.plr) else ("WARN" if lres.plr < C["plr_limited_db"] else "PASS"), r(lres.plr),
                     "low PLR = limiter/clipper already on the main bus; bypass it for the premaster"))
    rows.append(_row("integrated_lufs", "INFO", r(lres.integrated), "premaster loudness is not a target; headroom matters more"))
    # DC
    dc = max(dc_offset_db(x, sr))
    real = dc_is_real(x, sr)
    rows.append(_row("dc_offset_dbfs", "WARN" if (dc > C["dc_warn_dbfs"] and real) else "PASS", r(dc),
                     "DC wastes headroom and thumps at edits" + ("" if real else " (mean is bass wander, not a steady offset)")))
    # head / tail
    k = max(1, int(0.01 * sr))
    head, tail = float(db(rms(x[:k]))), float(db(rms(x[-k:])))
    rows.append(_row("head_first_10ms_dbfs", "WARN" if head > C["head_warn_dbfs"] else "PASS", r(head),
                     "loud first samples = clipped start / missing pre-roll; also causes inter-sample overs"))
    rows.append(_row("tail_last_10ms_dbfs", "WARN" if tail > C["tail_warn_dbfs"] else "PASS", r(tail),
                     "loud last samples = reverb/delay tail cut off; extend the export length"))
    # stereo
    if x.shape[1] == 2:
        l, rr = x[:, 0], x[:, 1]
        den = np.sqrt(np.sum(l * l) * np.sum(rr * rr))
        corr = float(np.sum(l * rr) / den) if den else 1.0
        rows.append(_row("correlation", "FAIL" if corr < C["corr_fail"] else "PASS", r(corr, 3),
                         "negative overall correlation = polarity problem"))
        sb = S.stereo_by_band(x, sr, edges=(20, 120))
        lc = sb[0]["correlation"] if sb else 1.0
        rows.append(_row("low_end_correlation_20_120hz", "WARN" if lc < C["low_corr_warn"] else "PASS", lc,
                         "club systems and phones sum bass to mono; keep it near 1"))
        mono = x.mean(axis=1, keepdims=True).repeat(2, axis=1)
        drop = lres.integrated - L.integrated(mono, sr)
        rows.append(_row("mono_sum_loss_lu", "WARN" if drop > C["mono_loss_warn_lu"] else "PASS", r(drop),
                         "loudness lost when summed to mono (phone speaker, club)"))
        bal = float(db(rms(l)) - db(rms(rr)))
        rows.append(_row("lr_balance_db", "WARN" if abs(bal) > C["balance_warn_db"] else "PASS", r(bal), "L minus R RMS"))
    # length
    rows.append(_row("duration_s", "INFO" if audio.duration <= C["short_max_s"] else "WARN", r(audio.duration, 1),
                     f"YouTube Shorts: up to {int(C['short_max_s'])} s"))
    worst = "FAIL" if any(r_["status"] == "FAIL" for r_ in rows) else (
        "WARN" if any(r_["status"] == "WARN" for r_ in rows) else "PASS")
    return {"overall": worst, "checks": rows}
