"""The measurement sheet: every instrument on one file.

`sheet()` returns a nested dict; `flat()` flattens it to dotted keys
(e.g. 'loudness.integrated') which hypotheses use as metric names.
"""
from __future__ import annotations

import numpy as np

from . import bitdepth, delivery, dynamics, loudness as L, spectrum as S
from .util import r


def sheet(audio, codecs=False) -> dict:
    x, sr = audio.x, audio.sr
    lres = L.analyze(x, sr)
    f_p = S.psd(x, sr)
    tb = S.tonal_balance(x, sr, f_p)
    out = {
        "file": audio.meta(),
        "loudness": lres.summary(),
        "dynamics": dynamics.analyze(x, sr, lres),
        "tonal": {"slope_db_per_oct": tb["slope_db_per_oct"], "centroid_hz": r(S.centroid(x, sr, f_p), 0),
                  **{f"group.{k}": v for k, v in tb["groups_db_rel_total"].items()}},
        "third_octave": tb["third_octave"],
        "stereo": S.stereo_by_band(x, sr),
        "word_length": bitdepth.analyze(audio),
        "delivery": delivery.report(x, sr, lres, codecs=codecs),
    }
    return out


def flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flat(v, key + "."))
        elif isinstance(v, (int, float, str, bool)) or v is None:
            out[key] = v
    for i, row in enumerate(d.get("stereo", []) if isinstance(d.get("stereo"), list) else []):
        lo, hi = row["band_hz"]
        out[f"{prefix}stereo.corr_{lo}_{hi}"] = row["correlation"]
    return out


CORE_KEYS = [
    "loudness.integrated", "loudness.short_term_max", "loudness.lra", "loudness.true_peak",
    "loudness.plr", "loudness.psr_min", "dynamics.crest_db", "dynamics.block_crest_median_db",
    "dynamics.transient_contrast_median_db", "tonal.slope_db_per_oct", "tonal.centroid_hz",
    "tonal.group.sub", "tonal.group.bass", "tonal.group.low_mid", "tonal.group.mid",
    "tonal.group.upper_mid", "tonal.group.presence", "tonal.group.air", "stereo.corr_20_120",
]


def markdown(sh: dict, title=None) -> str:
    fl = flat(sh)
    m = sh["file"]
    lines = [f"# Measurement sheet — {title or m['path']}", "",
             f"{m['duration_s']} s · {m['sr']} Hz · {m['channels']} ch · {m['subtype']}", "",
             "## Loudness (Ch. 17-19)", "", "| measure | value |", "|---|---|"]
    for k, v in sh["loudness"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Dynamics (Ch. 5-7)", "", "| measure | value |", "|---|---|"]
    for k, v in sh["dynamics"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Tonal balance (Ch. 4)", "", "| measure | value |", "|---|---|"]
    for k, v in sh["tonal"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "1/3-octave levels (dB, relative):", "",
              " ".join(f"{int(c)}:{v}" for c, v in sh["third_octave"]), ""]
    if sh["stereo"]:
        lines += ["## Stereo", "", "| band Hz | correlation | side−mid dB |", "|---|---|---|"]
        for row in sh["stereo"]:
            lines.append(f"| {row['band_hz'][0]}–{row['band_hz'][1]} | {row['correlation']} | {row['side_minus_mid_db']} |")
        lines.append("")
    wl = sh["word_length"]
    lines += ["## Word length (Ch. 15)", "", f"- container: {wl.get('container')}",
              f"- effective bits: {wl.get('effective_bits', 'n/a')}", f"- verdict: {wl.get('verdict')}", ""]
    dv = sh["delivery"]
    lines += ["## Delivery (YouTube and others)", "", "| platform | gain dB | plays at LUFS | plays at dBTP | note |",
              "|---|---|---|---|---|"]
    for p, v in dv["normalization"].items():
        lines.append(f"| {p} | {v['gain_db']} | {v['playback_lufs']} | {v['playback_true_peak']} | {v['note']} |")
    if dv.get("codec_roundtrip"):
        lines += ["", "| codec | TP after | TP rise | samples > 0 dBFS |", "|---|---|---|---|"]
        for c, v in dv["codec_roundtrip"].items():
            lines.append(f"| {c} | {v.get('true_peak_after')} | {v.get('true_peak_rise_db')} | {v.get('samples_over_0dbfs')} |")
    if dv["advice"]:
        lines += ["", "Advice:", *[f"- {a}" for a in dv["advice"]]]
    return "\n".join(lines) + "\n"
