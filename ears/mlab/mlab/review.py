"""One-shot premaster review: premaster checklist + measurement sheet + delivery
+ reference comparison + a plain-language feedback list.

    python3 -m mlab review audio/inbox/<premaster>.wav [--refs audio/refs] [--bpm 160]

Writes reports/review-<name>.md and .json. Feedback rules are deliberately simple
and each one names the number it rests on, so Anthony can argue with it.
"""
from __future__ import annotations

import glob
import os

import numpy as np

from . import io as aio, measure, premaster, spectrum as S
from .util import db, r

AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a")


def peak_events(x, sr, bpm=160.0, top=5):
    """Loudest beats vs the typical beat. An outlier event will drive the master limiter."""
    m = np.max(np.abs(x), axis=1)
    b = max(1, int(sr * 60 / bpm))
    k = len(m) // b
    if k < 8:
        return None
    pk = db(m[:k * b].reshape(k, b).max(axis=1))
    live = pk > pk.max() - 40
    med = float(np.median(pk[live]))
    order = np.argsort(pk)[::-1][:top]
    return {"median_beat_peak_dbfs": r(med), "p90_beat_peak_dbfs": r(np.percentile(pk[live], 90)),
            "top": [{"t_s": r(i * b / sr, 2), "peak_dbfs": r(pk[i]), "above_median_db": r(pk[i] - med)} for i in order]}


def ref_rows(refdir):
    rows, tonal = {}, []
    if not refdir or not os.path.isdir(refdir):
        return rows, None
    for p in sorted(glob.glob(os.path.join(refdir, "*"))):
        if os.path.splitext(p)[1].lower() not in AUDIO_EXT:
            continue
        a = aio.load(p)
        rows[os.path.splitext(os.path.basename(p))[0][:24]] = measure.flat(measure.sheet(a))
        tonal.append(np.array([v for _, v in S.third_octave(a.x, a.sr)]))
    return rows, tonal


def feedback(pm, fl, peaks, refs):
    fb = []
    for row in pm["checks"]:
        if row["status"] in ("FAIL", "WARN"):
            fb.append(f"[{row['status']}] {row['check']} = {row['value']}: {row['why']}")
    if peaks and peaks["top"] and peaks["top"][0]["above_median_db"] and peaks["top"][0]["above_median_db"] > 3:
        t = peaks["top"][0]
        fb.append(f"[NOTE] loudest beat at {t['t_s']} s is {t['above_median_db']} dB above the typical beat "
                  f"({peaks['median_beat_peak_dbfs']} dBFS): the master limiter will work mostly there (L-010)")
    if fl.get("word_length.dc_steady") and (fl.get("word_length.dc_max_dbfs") or -999) > -60:
        fb.append(f"[NOTE] steady DC {fl['word_length.dc_max_dbfs']} dBFS: high-pass ~15 Hz first in the master chain (L-011)")
    if refs:
        keys = ["loudness.plr", "dynamics.crest_db", "dynamics.transient_contrast_median_db", "loudness.lra",
                "tonal.slope_db_per_oct"] + [f"tonal.group.{g}" for g in S.GROUPS]
        for k in keys:
            vals = [v.get(k) for v in refs.values() if isinstance(v.get(k), (int, float))]
            t = fl.get(k)
            if len(vals) < 2 or not isinstance(t, (int, float)):
                continue
            lo, hi, med = min(vals), max(vals), float(np.median(vals))
            if t < lo or t > hi:
                fb.append(f"[REF] {k} = {t}, outside the references' range {r(lo)}..{r(hi)} (median {r(med)})")
    return fb


def run(path, refdir=None, bpm=160.0, codecs=True):
    a = aio.load(path)
    sh = measure.sheet(a, codecs=codecs)
    fl = measure.flat(sh)
    pm = premaster.run(a)
    peaks = peak_events(a.x, a.sr, bpm)
    refs, tonal = ref_rows(refdir)
    tonal_diff = None
    if tonal:
        mine = np.array([v for _, v in S.third_octave(a.x, a.sr)])
        n = min(len(mine), *(len(t) for t in tonal))
        norm = lambda v: v[:n] - 10 * np.log10(np.sum(10 ** (v[:n] / 10)))
        med = np.median(np.vstack([norm(t) for t in tonal]), axis=0)
        cs = [c for c, _ in S.third_octave(a.x, a.sr)][:n]
        tonal_diff = [(r(c, 0), r(d)) for c, d in zip(cs, norm(mine) - med)]
    fb = feedback(pm, fl, peaks, refs)
    name = os.path.splitext(os.path.basename(path))[0]
    lab = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(lab, "reports", f"review-{name}")
    md = [f"# Premaster review — {name}", "", f"Premaster checklist: **{pm['overall']}**", "",
          "## Feedback", "", *(f"- {x}" for x in (fb or ["nothing flagged"])), "",
          "## Checklist", "", "| check | status | value | why |", "|---|---|---|---|",
          *(f"| {c['check']} | {c['status']} | {c['value']} | {c['why']} |" for c in pm["checks"]), ""]
    if peaks:
        md += ["## Loudest beats", "", f"Median beat peak {peaks['median_beat_peak_dbfs']} dBFS; "
               f"90th percentile {peaks['p90_beat_peak_dbfs']} dBFS.", "", "| time s | peak dBFS | above median dB |",
               "|---|---|---|", *(f"| {p['t_s']} | {p['peak_dbfs']} | {p['above_median_db']} |" for p in peaks["top"]), ""]
    if refs:
        from .compare import refs_table
        md += ["## Against the references", "", refs_table(fl, refs, measure.CORE_KEYS)]
    if tonal_diff:
        md += ["## Tonal difference vs reference median (1/3 octave, dB, shape only)", "",
               " ".join(f"{int(c)}:{d:+}" for c, d in tonal_diff), ""]
    md += ["## Full sheet", "", measure.markdown(sh, name)]
    os.makedirs(os.path.dirname(base), exist_ok=True)
    with open(base + ".md", "w") as f:
        f.write("\n".join(md))
    aio.dump_json({"premaster": pm, "sheet": sh, "peaks": peaks, "feedback": fb, "tonal_diff": tonal_diff}, base + ".json")
    return base + ".md", fb
