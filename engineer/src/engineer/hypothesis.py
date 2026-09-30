"""Hypothesis runner: YAML claim -> variants -> measurements -> verdict.

See engineer/hypotheses/TEMPLATE.yaml for the schema. Input paths are relative
to the lab data directory: $MLAB_DATA, or ears/mlab in this repo. Results go
to engineer/hypotheses/results.
Variants come from files (Ableton renders) or from Python ops (dsp.py).
"""
from __future__ import annotations

import datetime as dt
import json
import os

import numpy as np
import yaml

from mlab import compare, delivery, dsp, io as aio, loudness as L, measure
from mlab.util import lin, r

_HERE = os.path.dirname(os.path.abspath(__file__))
ENGINEER = os.path.dirname(os.path.dirname(_HERE))
REPO = os.path.dirname(ENGINEER)
LAB = os.environ.get("MLAB_DATA", os.path.join(REPO, "ears", "mlab"))


def _p(path):
    return path if os.path.isabs(path) else os.path.join(LAB, path)


def apply_op(x, sr, op: dict):
    op = dict(op)
    name = op.pop("op")
    if name == "gain":
        return dsp.gain(x, op["gain_db"])
    if name == "eq":
        return dsp.eq(x, sr, op["bands"])
    if name == "compressor":
        return dsp.compressor(x, sr, **op)
    if name == "limiter":
        return dsp.limiter(x, sr, **op)
    if name == "master_to":
        return dsp.master_to(x, sr, op.pop("target_lufs"), **op)[0]
    if name == "clip":
        return dsp.clip(x, op.get("ceiling_db", 0.0), op.get("mode", "hard"))
    if name == "quantize":
        return dsp.quantize(x, **op)
    if name == "truncate":
        return dsp.truncate(x, op.get("bits", 16))
    if name == "normalize_lufs":
        return dsp.normalize_lufs(x, sr, op["target"])
    if name == "mono":
        return dsp.to_mono(x)
    if name == "ms_width":
        return dsp.ms_width(x, op.get("side_gain_db", 0.0))
    if name == "excerpt":
        return dsp.excerpt(x, sr, op["start_s"], op["dur_s"], op.get("fade_ms", 10.0))
    if name == "codec":
        return delivery.roundtrip(x, sr, op.get("label", "aac128"))
    if name == "platform":
        # same model as `mlab deliver` (turn-down only, or turn-up capped at -1 dBTP)
        row = delivery.normalization(L.integrated(x, sr), L.true_peak(x, sr))[op.get("name", "youtube")]
        return x * lin(row["gain_db"] or 0.0)
    raise ValueError(f"unknown op {name}")


def build_variants(spec):
    inputs = {k: aio.load(_p(v)) for k, v in (spec.get("inputs") or {}).items()}
    out = {}
    for v in spec["variants"]:
        if "file" in v:
            a = aio.load(_p(v["file"]))
        else:
            src = v.get("from")
            base = inputs.get(src) or out.get(src)
            if base is None:
                raise KeyError(f"variant {v['name']}: unknown source {src}")
            a = aio.Audio(base.x.copy(), base.sr, f"{src}+ops", base.subtype, base.fmt)
        x = a.x
        for op in v.get("chain", []) or []:
            x = apply_op(x, a.sr, op)
        processed = bool(v.get("chain"))
        # processed audio lives in float until something quantizes it; a lossy source
        # stays "lossy" only if no op touched it
        out[v["name"]] = aio.Audio(x, a.sr, f"{v['name']}" if processed else a.path,
                                   "FLOAT" if processed else a.subtype, a.fmt)
    return out


OPS = {"<": np.less, "<=": np.less_equal, ">": np.greater, ">=": np.greater_equal}


def evaluate(pred, rows):
    lm = rows.get(pred["left"], {}).get(pred["metric"])
    rm = rows.get(pred["right"], {}).get(pred["metric"]) if pred.get("right") else 0.0
    if not isinstance(lm, (int, float)) or not isinstance(rm, (int, float)):
        return {"status": "INCONCLUSIVE", "observed": None}
    obs = lm - rm
    ref = abs(obs) if pred["op"].startswith("abs") else obs
    gap = abs(ref - pred["value"])
    strict = pred["op"] in ("<", ">", "abs<", "abs>")
    if gap < 0.015 and (strict or gap > 0):   # metrics are rounded to 0.01; a result this close to the line is a tie
        return {"status": "INCONCLUSIVE", "observed": r(obs, 3), "note": "within rounding of the threshold"}
    if pred["op"] in OPS:
        ok = bool(OPS[pred["op"]](obs, pred["value"]))
    elif pred["op"] == "abs<":
        ok = abs(obs) < pred["value"]
    elif pred["op"] == "abs>":
        ok = abs(obs) > pred["value"]
    else:
        raise ValueError(pred["op"])
    return {"status": "PASS" if ok else "FAIL", "observed": r(obs, 3)}


def run(path, outroot=None, codecs=None):
    with open(path) as f:
        spec = yaml.safe_load(f)
    hid = spec["id"]
    slug = os.path.splitext(os.path.basename(path))[0]
    outdir = os.path.join(outroot or os.path.join(ENGINEER, "hypotheses", "results"), slug)
    os.makedirs(outdir, exist_ok=True)
    variants = build_variants(spec)
    want_codecs = spec.get("codecs", False) if codecs is None else codecs
    rows, sheets = {}, {}
    for name, a in variants.items():
        aio.save(os.path.join(outdir, "audio", f"{name}.wav"), a.x, a.sr)
        sh = measure.sheet(a, codecs=want_codecs)
        sheets[name] = sh
        rows[name] = measure.flat(sh)
        aio.dump_json(sh, os.path.join(outdir, "sheets", f"{name}.json"))
    keys = spec.get("metrics") or measure.CORE_KEYS
    preds = []
    for p in spec.get("predictions", []) or []:
        preds.append({**p, **evaluate(p, rows)})
    statuses = [p["status"] for p in preds]
    verdict = ("NO PREDICTION" if not preds else "NOT SUPPORTED" if "FAIL" in statuses
               else "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "SUPPORTED")
    listen = spec.get("listening") or {}
    abx_dir = None
    if listen.get("abx"):
        a_name, b_name = listen["abx"]
        exc = listen.get("excerpt") or [None, None]
        abx_dir = os.path.join(outdir, "abx")
        compare.abx_kit(variants[a_name], variants[b_name], abx_dir, trials=listen.get("trials", 12),
                        start=exc[0], dur=exc[1])
    md = _report(spec, variants, rows, keys, preds, verdict, abx_dir)
    with open(os.path.join(outdir, "report.md"), "w") as f:
        f.write(md)
    aio.dump_json({"id": hid, "verdict": verdict, "predictions": preds,
                   "rows": {k: {m: v.get(m) for m in keys} for k, v in rows.items()}},
                  os.path.join(outdir, "result.json"))
    return outdir, verdict


def _report(spec, variants, rows, keys, preds, verdict, abx_dir):
    names = list(variants)
    L_ = [f"# {spec['id']} — {spec.get('title', '')}", "",
          f"Run {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · chapter {spec.get('chapter', '?')} · "
          f"source: {spec.get('source', 'n/a')}", "",
          f"**Claim.** {spec.get('claim', '').strip()}", "", f"**Verdict: {verdict}**", ""]
    if preds:
        L_ += ["## Predictions", "", "| metric | left − right | op | threshold | observed | status |", "|---|---|---|---|---|---|"]
        for p in preds:
            L_.append(f"| {p['metric']} | {p['left']} − {p.get('right', '0')} | {p['op']} | {p['value']} | "
                      f"{p['observed']} | {p['status']} |")
            if p.get("why"):
                L_.append(f"| | *{p['why']}* | | | | |")
        L_.append("")
    L_ += ["## Measurements", "", "| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in keys:
        L_.append(f"| {k} | " + " | ".join(str(rows[n].get(k)) for n in names) + " |")
    L_ += ["", "## Variants", ""]
    for v in spec["variants"]:
        src = v.get("file") or f"{v.get('from')} → " + " → ".join(o["op"] for o in v.get("chain", []) or [])
        L_.append(f"- **{v['name']}**: {src}")
    if abx_dir:
        L_ += ["", "## Listening", "", f"Blind ABX kit in `{os.path.relpath(abx_dir, LAB)}` (level-matched). "
               "Score with `python3 -m mlab abx-score <folder> <answers>`."]
    L_ += ["", "## Interpretation", "", spec.get("interpretation_hint", "_Write what this changes, then log it in LEARNINGS.md._"), ""]
    return "\n".join(L_)
