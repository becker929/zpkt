"""Calibrate the measuring scripts on synthetic audio with known answers, before they decide anything.

    run selftest.py                  # prints a table; exit 1 if any check fails
    run selftest.py --json OUT.json  # keep the numbers (preflight.py stores them in its JSON, and the
                                     # retro copies the bias into run.json from there)

Checks:
- onset bias: kick, bass, clap, hat and click events at random known times, alone and mixed, at
  16 kHz (the tutorial's audio) and 44.1 kHz (Live's renders). FAIL if the median error of any
  kind is over 5 ms, or under 95 % of events are found. Run 1 built a version on a detector that
  ran 21 ms early; this is how a later run catches the same thing.
- grid: per-16th body/hats strengths on a 2-bar pattern sort body hits from hat hits.
- pitch: 55 Hz and 82.4 Hz notes within 10 cents, with both naming conventions.
- positions: beats to bar.beat.sixteenth.
- anchor: a loop's start and its later passes found to the millisecond.
- info: how far ears/mlab's onset_envelope frame index runs ahead (never read its frames as times).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor  # noqa: E402
import onsets  # noqa: E402
import pitch  # noqa: E402
from common import band, note_names, position, write_json  # noqa: E402

KIND_BAND = {"kick": "low", "bass": "low", "clap": "mid", "hat": "high", "click": "full"}
BIAS_MAX_MS = 5.0
RECALL_MIN = 0.95


def event(kind: str, sr: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(int(0.3 * sr)) / sr
    if kind == "kick":
        f = 45 + 70 * np.exp(-t / 0.03)
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / 0.12) * 0.8
    if kind == "bass":
        return np.sin(2 * np.pi * 55.0 * t) * np.exp(-t / 0.07) * 0.6
    if kind == "clap":
        y = np.zeros_like(t)
        for off in (0.0, 0.009, 0.018):
            a = int(off * sr)
            n = len(t) - a
            y[a:] += rng.standard_normal(n) * np.exp(-np.arange(n) / (0.004 * sr if off < 0.018 else 0.04 * sr))
        return band(y, sr, 800, 3000) * 0.5
    if kind == "hat":
        y = rng.standard_normal(len(t)) * np.exp(-t / 0.012)
        return band(y, sr, min(6000.0, 0.4 * sr), None) * 0.3
    if kind == "click":
        y = rng.standard_normal(len(t)) * np.exp(-t / 0.002) * 0.5
        y[0] = 0.9
        return y
    raise ValueError(kind)


def scene(kinds: list[str], sr: int, rng: np.random.Generator, seconds: float = 14.0):
    """Events at random times (>= 250 ms apart overall), over a -70 dBFS noise floor."""
    x = rng.standard_normal(int(seconds * sr)) * 10 ** (-70 / 20)
    truth: dict[str, list[float]] = {k: [] for k in kinds}
    t = 0.3
    while t < seconds - 0.5:
        k = kinds[rng.integers(len(kinds))]
        a = int(t * sr)
        e = event(k, sr, rng)
        x[a:a + len(e)] += e[:len(x) - a]
        truth[k].append(a / sr)
        t += 0.25 + rng.uniform(0, 0.2)
    return x, truth


def match(found: list[float], truth: list[float], tol: float = 0.03) -> dict:
    found = sorted(found)
    errs, used = [], set()
    for t in truth:
        best = min((abs(f - t), i) for i, f in enumerate(found)) if found else (1e9, -1)
        if best[0] <= tol and best[1] not in used:
            used.add(best[1])
            errs.append((found[best[1]] - t) * 1000)
    n = len(truth)
    return {"n": n, "found": len(errs), "recall": round(len(errs) / n, 3) if n else 1.0,
            "extras": len(found) - len(used),
            "bias_ms": round(float(np.median(errs)), 2) if errs else None,
            "max_abs_ms": round(float(np.max(np.abs(errs))), 2) if errs else None}


def check_onsets(rng: np.random.Generator) -> list[dict]:
    rows = []
    for sr in (16000, 44100):
        cases = [[k] for k in KIND_BAND] + [["kick", "clap", "hat"], ["bass", "clap", "hat", "click"]]
        for kinds in cases:
            x, truth = scene(kinds, sr, rng)
            for k in kinds:
                _, ons = onsets.band_onsets(x, sr, KIND_BAND[k])
                found = [o["t"] for o in ons]
                if len(kinds) > 1:  # in a mix, other kinds' onsets in this band are not extras
                    others = [t for kk in kinds if kk != k for t in truth[kk]]
                    found = [f for f in found if min((abs(f - o) for o in others), default=1) > 0.03]
                m = match(found, truth[k])
                ok = m["bias_ms"] is not None and abs(m["bias_ms"]) <= BIAS_MAX_MS and m["recall"] >= RECALL_MIN
                rows.append({"check": "onset", "sr": sr, "kind": k, "scene": "+".join(kinds),
                             "band": KIND_BAND[k], **m, "pass": bool(ok)})
    return rows


def check_grid(rng: np.random.Generator) -> dict:
    sr, bpm = 44100, 123.0
    spb = 60 / bpm
    body_pos = [0.5, 1.5, 2.75, 3.5, 4.5, 5.5, 6.75, 7.5]
    hat_pos = [0.25, 1.25, 2.25, 3.25, 4.25, 5.25, 6.25, 7.25]
    x = rng.standard_normal(int((2 * 8 * spb + 1) * sr)) * 1e-4
    t = np.arange(int(0.25 * sr)) / sr
    conga = np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.06) * 0.5
    for p in range(2):
        for b in body_pos:
            a = int((0.5 + (p * 8 + b) * spb) * sr)
            x[a:a + len(conga)] += conga
        for b in hat_pos:
            a = int((0.5 + (p * 8 + b) * spb) * sr)
            h = event("hat", sr, rng)
            x[a:a + len(h)] += h[:len(x) - a]
    _, body = onsets.grid_strengths(x, sr, "body=40-1500", t0=0.5, bpm=bpm, loop_beats=8, passes=2)
    _, hats = onsets.grid_strengths(x, sr, "hats=5000-16000", t0=0.5, bpm=bpm, loop_beats=8, passes=2)
    called_body = [r["beat"] for r, h in zip(body, hats) if r["level_db"] - h["level_db"] >= 10 and r["jump_db"] >= 6]
    called_hat = [h["beat"] for r, h in zip(body, hats) if h["jump_db"] >= 6 and h["level_db"] - r["level_db"] > -10
                  and h["beat"] not in called_body]
    ok = sorted(called_body) == body_pos and sorted(called_hat) == hat_pos
    errs = [abs(r["err_ms"]) for r in body if r["beat"] in body_pos]
    return {"check": "grid", "body_found": called_body, "hats_found": called_hat,
            "max_abs_err_ms": round(max(errs), 2), "pass": bool(ok)}


def check_pitch() -> list[dict]:
    rows = []
    for sr in (16000, 44100):
        for hz, midi in ((55.0, 33), (82.407, 40)):
            t = np.arange(int(0.4 * sr)) / sr
            x = np.concatenate([np.zeros(sr // 10), np.sin(2 * np.pi * hz * t) * np.exp(-t / 0.2)])
            r = pitch.analyse(x, sr, 0.1, delay=0.01, win=0.12, fmin=25, fmax=400)
            names = note_names(midi)
            ok = r.get("midi") == midi and abs(r.get("cents", 99)) <= 10 and r["sci"] == names["sci"]
            rows.append({"check": "pitch", "sr": sr, "true_hz": hz, "hz": r.get("hz"), "cents": r.get("cents"),
                         "sci": r.get("sci"), "live": r.get("live"), "pass": bool(ok)})
    return rows


def check_positions() -> dict:
    cases = {(1.5, 1): "1.2.3", (5.5, 1): "2.2.3", (7.75, 1): "2.4.4", (1.5, 15): "15.2.3", (0.1, 1): "1.1.1+0.40"}
    got = {f"{b}@{s}": position(b, s) for (b, s) in cases}
    names = note_names(33) == {"midi": 33, "live": "A0", "sci": "A1"} and note_names(60)["live"] == "C3"
    ok = all(position(b, s) == want for (b, s), want in cases.items()) and names
    return {"check": "positions", "got": got, "pass": bool(ok)}


def check_anchor(rng: np.random.Generator) -> dict:
    sr, bpm = 16000, 123.0
    n = int(round(8 * 60 / bpm * sr))
    loop = np.zeros(n)
    for b in (0.0, 0.5, 1.5, 2.75, 3.5, 4.5, 5.5, 6.75, 7.5):
        e = event("click" if b else "kick", sr, rng)
        a = int(b * 60 / bpm * sr)
        loop[a:a + len(e)] += e[:n - a]
    start = 1.2345
    x = np.concatenate([rng.standard_normal(int(start * sr)) * 1e-4, loop, loop, loop, np.zeros(sr)])
    s = anchor.start_near(x, sr, 1.3, 0.3)["t"]
    al = anchor.align(x, sr, s, s + 2 * n / sr + 0.05, n, 0.2)
    true_start = int(start * sr) / sr
    err_start = (s - true_start) * 1000  # the onset detector's bias
    err_align = (al["t"] - (s + 2 * n / sr)) * 1000  # correlation against the found start: exact
    ok = abs(err_start) <= BIAS_MAX_MS and abs(err_align) <= 0.2
    return {"check": "anchor", "start_err_ms": round(err_start, 3), "align_err_ms": round(err_align, 3), "pass": bool(ok)}


def info_mlab(rng: np.random.Generator) -> dict:
    try:
        from mlab.sections import onset_envelope
    except ImportError:
        return {"check": "info", "mlab_onset_envelope_frame_offset_ms": None, "note": "mlab not importable here"}
    sr = 44100
    x, truth = scene(["click"], sr, rng, seconds=8.0)
    env, fps = onset_envelope(x, sr)
    env = env - env.min()
    lags = []
    for t in truth["click"]:
        a, b = int((t - 0.05) * fps), int((t + 0.05) * fps)
        lags.append(((np.argmax(env[a:b]) + a) / fps - t) * 1000)
    return {"check": "info", "mlab_onset_envelope_frame_offset_ms": round(float(np.median(lags)), 2),
            "note": "an onset_envelope frame index / fps is this far from the onset; add the offset back"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="write the results here")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    rows = check_onsets(rng)
    print(f"{'sr':>6} {'kind':6} {'scene':24} {'band':5} {'found':>8} {'extras':>6} {'bias ms':>8} {'max ms':>7}  result")
    for r in rows:
        print(f"{r['sr']:6d} {r['kind']:6} {r['scene']:24} {r['band']:5} {r['found']:3d}/{r['n']:<4d} {r['extras']:6d} "
              f"{r['bias_ms'] if r['bias_ms'] is not None else '-':>8} {r['max_abs_ms'] if r['max_abs_ms'] is not None else '-':>7}  "
              f"{'pass' if r['pass'] else 'FAIL'}")
    others = [check_grid(rng), *check_pitch(), check_positions(), check_anchor(rng)]
    for r in others:
        print(f"{r['check']:9s} {'pass' if r['pass'] else 'FAIL'}  " +
              ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("check", "pass")))
    info = info_mlab(rng)
    print(f"info      mlab onset_envelope frame offset: {info['mlab_onset_envelope_frame_offset_ms']} ms ({info['note']})")

    biases = [r["bias_ms"] for r in rows if r["bias_ms"] is not None]
    summary = {"pass": all(r["pass"] for r in rows + others),
               "onset_bias_ms_worst": max(biases, key=abs) if biases else None,
               "onset_max_abs_ms": max(r["max_abs_ms"] or 0 for r in rows),
               "onset_recall_min": min(r["recall"] for r in rows)}
    print(f"\nselftest {'PASS' if summary['pass'] else 'FAIL'}: worst onset bias {summary['onset_bias_ms_worst']} ms "
          f"(limit {BIAS_MAX_MS}), max error {summary['onset_max_abs_ms']} ms, min recall {summary['onset_recall_min']}")
    if a.json:
        write_json(a.json, {"summary": summary, "onsets": rows, "checks": others, "info": info})
    sys.exit(0 if summary["pass"] else 1)


if __name__ == "__main__":
    main()
