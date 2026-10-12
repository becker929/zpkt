"""Measure a practice render against its render spec (what PLAN.md says the render holds).

    run measure_render.py practice/renders/A_raw.wav practice/spec_A.json --out practice/measurements/A_raw.json

The spec is JSON; times are beats from the render's first sample (practice bar 1 = beat 0):

  {"bpm": 123, "beats": 65,
   "sections": [{"name": "perc", "bars": [1, 4]}, {"name": "perc+bass", "bars": [5, 8]}, ...],
   "events": [{"name": "bass", "band": "20-150", "loop_beats": 8, "beats": [1.5, 2.75], "bars": [5, 16],
               "tol_ms": 15, "explain_from": [1, 4]},
              {"name": "kick", "band": "20-150", "loop_beats": 8, "beats": [0, 1, 2, 3, 4, 5, 6, 7],
               "bars": [9, 16], "reference": true}],
   "presence": [{"name": "perc", "band": "150-5000", "template_bars": [1, 2], "present": [[1, 8]],
                 "absent": [[9, 16]]}],
   "floors": [{"name": "crackle", "band": "8000-"}],
   "delivery": {"lufs": -15.0, "lufs_tol": 1.0, "true_peak_max": -1.0}}

Checks: loudness (BS.1770 integrated, 8x true peak, from ears/mlab), sample peak, clipping, the
longest stretch under -60 dBFS, per-section LUFS, duration; every planned event found within tol_ms
(the detector's own error on a "reference" list is reported as its bias); extra onsets in each
event band (an extra whose level matches the same loop position in the explain_from bars belongs
to that section's material, e.g. a perc loop's own low end); a loop's presence per 2-bar segment
by template projection (> 0.3 present, < 0.1 absent: the robust absence test); and the noise
floor per section in a band (crackle where it should be, nowhere else). Floors are reported, not
checked: compare them across sections yourself (run 1: -106 dB without crackle, -72 dB with it).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    band,
    best_jump_near,
    detect_onsets,
    jump_curve,
    parse_band,
    read_audio,
    rms_db,
    write_json,
)


def loudness(x2: np.ndarray, sr: int) -> tuple[float, float]:
    from mlab import loudness as L

    return float(L.integrated(x2, sr)), float(L.true_peak(x2, sr))


def bars_to_s(bars: list[int], spb: float) -> tuple[float, float]:
    return (bars[0] - 1) * 4 * spb, bars[1] * 4 * spb


def planned_times(ev: dict, spb: float) -> list[tuple[float, float]]:
    """(beat, time s) of every planned event of a list inside its bars."""
    b0, b1 = (ev["bars"][0] - 1) * 4, ev["bars"][1] * 4
    loop = ev.get("loop_beats", 8)
    out = []
    k = int(b0 // loop)
    while k * loop < b1:
        for b in ev["beats"]:
            beat = k * loop + b
            if b0 <= beat < b1:
                out.append((beat, beat * spb))
        k += 1
    return out


def segment_gains(gains: list[float], span: int, ranges: list[list[int]]) -> list[float]:
    """The template gains of the segments (span bars each) inside the given bar ranges."""
    return [gains[k] for r in ranges for k in range((r[0] - 1) // span, r[1] // span) if k < len(gains)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("render")
    ap.add_argument("spec")
    ap.add_argument("--out", help="write the full result here")
    a = ap.parse_args()

    spec = json.loads(Path(a.spec).read_text())
    x2, sr = read_audio(a.render, mono=False)
    m = x2.mean(axis=1)
    spb = 60.0 / spec["bpm"]
    res: dict = {"render": a.render, "spec": a.spec, "seconds": round(len(m) / sr, 4)}
    checks: dict[str, bool] = {}

    lufs, tp = loudness(x2, sr)
    res["integrated_lufs"], res["true_peak_dbtp"] = round(lufs, 2), round(tp, 2)
    res["sample_peak_dbfs"] = round(float(20 * np.log10(np.abs(x2).max() + 1e-15)), 2)
    res["clipped_samples"] = int((np.abs(x2) >= 0.999).sum())
    checks["no_clipping"] = res["clipped_samples"] == 0
    if "beats" in spec:
        want = spec["beats"] * spb
        res["planned_seconds"] = round(want, 4)
        checks["duration"] = abs(len(m) / sr - want) <= 0.05
    hop = int(0.01 * sr)
    end = int(min(len(m), max(bars_to_s(s["bars"], spb)[1] for s in spec.get("sections", [{"bars": [1, 1]}])) * sr))
    r10 = np.sqrt(np.convolve(m[:end] ** 2, np.ones(hop) / hop, "valid")[::hop])
    run = longest = 0
    for q in r10 < 10 ** (-60 / 20):
        run = run + 1 if q else 0
        longest = max(longest, run)
    res["longest_below_-60dBFS_s"] = round(longest * 0.01, 2)
    res["sections_lufs"] = {}
    for s in spec.get("sections", []):
        t0, t1 = bars_to_s(s["bars"], spb)
        res["sections_lufs"][s["name"]] = round(loudness(x2[int(t0 * sr):int(t1 * sr)], sr)[0], 2)

    planned_all = []
    for ev in spec.get("events", []):
        planned_all += [t for _, t in planned_times(ev, spb)]
    res["events"] = {}
    for ev in spec.get("events", []):
        name, lo, hi = parse_band(ev["band"])
        y = band(m, sr, lo, hi)
        after, before = jump_curve(y, sr, 5.0 if (hi or 1e9) <= 300 else 3.0)
        tol = ev.get("tol_ms", 15.0)
        rows = []
        for beat, t in planned_times(ev, spb):
            ft, jdb, lvl = best_jump_near(after, before, sr, t)
            rows.append({"beat": beat, "err_ms": round((ft - t) * 1000, 2), "jump_db": round(jdb, 1),
                         "level_db": round(lvl, 1)})
        errs = np.array([r["err_ms"] for r in rows])
        ok = bool(len(rows) and (np.abs(errs) <= tol).all() and min(r["jump_db"] for r in rows) >= 3)
        out = {"n": len(rows), "within_tol": int((np.abs(errs) <= tol).sum()), "tol_ms": tol,
               "max_abs_err_ms": round(float(np.abs(errs).max()), 2) if len(rows) else None,
               "median_err_ms": round(float(np.median(errs)), 2) if len(rows) else None, "pass": ok, "notes": rows}
        # extras: blind onsets in this band and these bars, within 20 dB of this list's own events,
        # that no planned event (of any list) explains
        t0, t1 = bars_to_s(ev["bars"], spb)
        seg = y[int(t0 * sr):int(t1 * sr)]
        own = float(np.median([r["level_db"] for r in rows])) if rows else -150.0
        blind = [o for o in detect_onsets(seg, sr, half_ms=5.0, min_jump_db=6.0, floor_db=-40.0) if o["level_db"] >= own - 20]
        extras = []
        for o in blind:
            t = t0 + o["t"]
            if min((abs(t - p) for p in planned_all), default=1) <= 0.03:
                continue
            item = {"t": round(t, 4), "beat": round(t / spb, 3), "level_db": round(o["level_db"], 1)}
            if "explain_from" in ev:  # the same loop position in a section without this source
                loop = ev.get("loop_beats", 8)
                e0, e1 = (ev["explain_from"][0] - 1) * 4, ev["explain_from"][1] * 4
                pos = (t / spb - e0) % loop
                refs = [best_jump_near(after, before, sr, (e0 + k * loop + pos) * spb, 20.0)[2]
                        for k in range(int((e1 - e0) // loop)) if (e0 + k * loop + pos) * spb > 0.03]
                item["explained"] = bool(refs and max(refs) >= o["level_db"] - 3)
            extras.append(item)
        out["extras"] = extras
        out["unexplained_extras"] = sum(not e.get("explained", False) for e in extras)
        res["events"][ev["name"]] = out
        if ev.get("reference"):
            res["detector_bias_ms"] = out["median_err_ms"]
        else:
            checks[f"events_{ev['name']}"] = ok and out["unexplained_extras"] == 0

    res["presence"] = {}
    for pr in spec.get("presence", []):
        _, lo, hi = parse_band(pr["band"])
        y = band(m, sr, lo, hi)
        t0, t1 = bars_to_s(pr["template_bars"], spb)
        T = y[int(t0 * sr):int(t1 * sr)]
        n = len(T)
        gains = []
        for k in range(int(len(y) // n)):
            s = y[k * n:(k + 1) * n]
            gains.append(round(float(s @ T / (T @ T + 1e-15)), 3))
        span = (pr["template_bars"][1] - pr["template_bars"][0] + 1)
        # present > 0.3: a multisampled or round-robin source does not repeat exactly (run 1's conga
        # pad projected 0.42-0.57 on itself); absent < 0.1 is the strict side
        ok = (all(g > 0.3 for g in segment_gains(gains, span, pr.get("present", [])))
              and all(abs(g) < 0.1 for g in segment_gains(gains, span, pr.get("absent", []))))
        res["presence"][pr["name"]] = {"gain_per_segment": gains, "segment_bars": span, "pass": bool(ok)}
        checks[f"presence_{pr['name']}"] = bool(ok)

    res["floors_db"] = {}
    for fl in spec.get("floors", []):
        _, lo, hi = parse_band(fl["band"])
        y = band(m, sr, lo, hi)
        row = {}
        for s in spec.get("sections", []):
            t0, t1 = bars_to_s(s["bars"], spb)
            seg = y[int(t0 * sr):int(t1 * sr)]
            r = np.sqrt(np.convolve(seg ** 2, np.ones(hop) / hop, "valid")[::hop])
            row[s["name"]] = round(float(20 * np.log10(np.percentile(r, 10) + 1e-12)), 1)
        res["floors_db"][fl["name"]] = row
    if d := spec.get("delivery"):
        checks["lufs"] = abs(lufs - d["lufs"]) <= d.get("lufs_tol", 1.0)
        checks["true_peak"] = tp <= d.get("true_peak_max", -1.0)
    res["checks"] = checks
    res["pass"] = all(checks.values())
    res["sections_rms_db"] = {s["name"]: rms_db(m[int(bars_to_s(s["bars"], spb)[0] * sr):int(bars_to_s(s["bars"], spb)[1] * sr)])
                          for s in spec.get("sections", [])}
    if a.out:
        write_json(a.out, res)
    show = {k: v for k, v in res.items() if k != "events"}
    show["events"] = {k: {kk: vv for kk, vv in v.items() if kk != "notes"} for k, v in res["events"].items()}
    print(json.dumps(show, indent=1))


if __name__ == "__main__":
    main()
