#!/usr/bin/env python3
"""
Measure a duck on real stems, and check the measure against a known answer.

Three things in one tool, all writing JSON and nothing else:

  corpus    The corpus band-pump measure (band_pump.py) run on a real kick +
            bass pair, on 30 s windows. Reports sub and low dip like the
            corpus does, so the two can be compared directly.

  calibrate Feed the SAME measure a broadband duck of known depth and report
            what it returns. A measure that returns 12 dB when given 24 is
            saturating, and the table says by how much at each depth.

  bypass    The exact answer. Given the bass rendered twice, once as it is
            and once with the ducking device bypassed, divide the two
            envelopes. The quotient is the gain curve the device applies,
            with no estimator in the way. Reported per band, so a split duck
            (sub deeper than low) shows up as a number, or does not.

Usage on any machine with the repo and requirements.txt installed:

  python3 lab/duck_calibration.py corpus    --kick K.wav --bass B.wav
  python3 lab/duck_calibration.py calibrate --kick K.wav
  python3 lab/duck_calibration.py bypass    --kick K.wav --bass B.wav --bypass B_off.wav
  add  --out result.json  to choose the output path (default: ./duck_<mode>.json)

Only the JSON leaves the machine. Audio stays where it is.
"""
import argparse, json, sys
from pathlib import Path

import numpy as np
import librosa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "corpus2"))
from analysis import grid, pump as pump_mod          # noqa: E402
from band_pump import curve, recovery_rise_ms         # noqa: E402

SR = grid.SR
BANDS = {0: "sub 20-60 Hz", 1: "low 60-150 Hz"}


def load(path, offset=0.0, duration=None):
    y, _ = librosa.load(str(path), sr=SR, mono=True, offset=offset, duration=duration)
    return y


def lock_grid(yd):
    envd, atkd = grid.envelopes(yd)
    _, bpm, ph = grid.lock(atkd[0], grid.coarse_tempo(yd))
    return float(bpm), float(ph)


def corpus_measure(yd, yb):
    """Exactly what band_pump.py reports, on one pair."""
    bpm, ph = lock_grid(yd)
    envb, _ = grid.envelopes(yb)
    cs, cl = curve(envb[0], bpm, ph), curve(envb[1], bpm, ph)
    ms = pump_mod.measure(cs, bpm) if cs is not None else {}
    ml = pump_mod.measure(cl, bpm) if cl is not None else {}
    s, l = ms.get("pump_depth_db"), ml.get("pump_depth_db")
    return dict(tempo=round(bpm, 2), sub_pump_db=s, low_pump_db=l,
                sub_minus_low_db=(round(s - l, 2) if s is not None and l is not None else None),
                low_return_ms=ml.get("pump_return_ms"), recovery_rise_ms=recovery_rise_ms(cl))


def broadband_duck(sig, bpm, ph, depth_db, shape_ms=120.0):
    """A gain duck on every beat that is identical at all frequencies."""
    beat = 60.0 / bpm
    g = np.ones(len(sig)); n = int(shape_ms / 1000 * SR)
    env = np.linspace(0, 1, n) ** 2; floor = 10 ** (-depth_db / 20)
    for b in range(int(len(sig) / SR / beat) + 1):
        s = int((ph / grid.FR + b * beat) * SR)
        if 0 <= s < len(sig):
            e = min(len(sig), s + n); g[s:e] = floor + (1 - floor) * env[:e - s]
    return sig * g


def content_end(y, sr, floor_db=-60.0, hold_s=2.0):
    """Index where the audio stops: last sample above floor_db, plus a short hold.

    Stems bounced from song.last_event_time carry the whole set's length, not
    the track's. HW002's rumble was 614 s of which 264 s was music; any
    window past that measured silence.
    """
    a = np.abs(y); pk = a.max()
    if pk <= 0:
        return 0
    idx = np.flatnonzero(a > pk * 10 ** (floor_db / 20))
    return int(min(len(y), idx[-1] + hold_s * sr)) if idx.size else 0


def align(ref, other, sr, bpm, max_lag_s=None):
    """Shift `other` so it lines up with `ref`, by cross-correlation.

    Two real-time takes do not start on the same sample (251 samples apart on
    the first run). The lag search is constrained to well inside one beat:
    an unconstrained search locks onto the material's own periodicity and
    returns one whole beat, which is wrong by construction.
    """
    if max_lag_s is None:
        max_lag_s = 0.4 * 60.0 / bpm
    n = min(len(ref), len(other), int(20 * sr))
    a, b = ref[:n].astype(np.float64), other[:n].astype(np.float64)
    m = int(max_lag_s * sr)
    c = np.correlate(a, b, mode="full")[n - 1 - m: n + m]
    lag = int(np.argmax(c)) - m
    if lag > 0:
        other = np.concatenate([np.zeros(lag), other])[:len(ref)]
    elif lag < 0:
        other = np.concatenate([other[-lag:], np.zeros(-lag)])[:len(ref)]
    return other, lag


def mode_corpus(a):
    yb_all = load(a.bass)
    dur = (content_end(yb_all, SR) or len(yb_all)) / SR      # music, not file length
    out = []
    for frac in (0.35, 0.5, 0.65, 0.8):
        off = dur * frac
        if off + 20 > dur:
            continue
        yd, yb = load(a.kick, off, 30), load(a.bass, off, 30)
        try:
            r = corpus_measure(yd, yb); r["window"] = f"30 s at {int(frac * 100)}%"
        except Exception as e:
            r = dict(window=f"30 s at {int(frac * 100)}%", error=f"{type(e).__name__}: {e}")
        out.append(r)
    return dict(mode="corpus", kick=str(a.kick), bass=str(a.bass), content_seconds=round(dur, 1), windows=out,
                note="Same measure as the corpus. On a solo stem that goes near-silent between kicks "
                     "these numbers can be meaningless; run calibrate and bypass before trusting them.")


def mode_calibrate(a):
    dur = librosa.get_duration(path=str(a.kick))
    yd = load(a.kick, dur * 0.35, 30)
    bpm, ph = lock_grid(yd)
    t = np.arange(len(yd)) / SR
    tone = (0.5 * np.sin(2 * np.pi * 45 * t) + 0.5 * np.sin(2 * np.pi * 110 * t)).astype(np.float32)
    rows = []
    for d in (3, 6, 12, 18, 24, 32, 40):
        r = corpus_measure(yd, broadband_duck(tone, bpm, ph, d))
        rows.append(dict(true_duck_db=d, measured_sub_db=r["sub_pump_db"], measured_low_db=r["low_pump_db"],
                         reported_split_db=r["sub_minus_low_db"]))
    return dict(mode="calibrate", kick=str(a.kick), tempo=round(bpm, 2), rows=rows,
                reading="If measured stops rising while true keeps rising, the measure saturates there. "
                        "If reported_split is not near zero, the measure invents a split it should not.")


def mode_bypass(a):
    """Exact gain curve by division: ducked render over bypassed render, per band."""
    # Work on the CONTENT of the stems, not the file length, and align the two
    # takes once, up front, before any window is cut.
    yd_all, yb_all, y0_all = load(a.kick), load(a.bass), load(a.bypass)
    n = min(len(yd_all), len(yb_all), len(y0_all)); yd_all, yb_all, y0_all = yd_all[:n], yb_all[:n], y0_all[:n]
    end = min(content_end(yb_all, SR), content_end(y0_all, SR)) or n
    bpm0, _ = lock_grid(yd_all[: min(n, 60 * SR)])
    y0_all, lag = align(yb_all, y0_all, SR, bpm0)
    dur = end / SR
    results = []
    meta = dict(content_seconds=round(dur, 1), file_seconds=round(n / SR, 1),
                trailing_silence_share=round(1 - dur / (n / SR), 3), alignment_lag_samples=lag)
    for frac in (0.35, 0.5, 0.65, 0.8):
        off = dur * frac
        if off + 20 > dur:
            continue
        s0, s1 = int(off * SR), int(min(end, (off + 30) * SR))
        yd, yb, y0 = yd_all[s0:s1], yb_all[s0:s1], y0_all[s0:s1]
        bpm, ph = lock_grid(yd)
        eb, _ = grid.envelopes(yb); e0, _ = grid.envelopes(y0)
        row = dict(window=f"30 s at {int(frac * 100)}%", tempo=round(bpm, 2), bands={})
        for i, name in BANDS.items():
            floor = np.percentile(e0[i], 99) * 1e-3          # ignore frames where the bypassed band is silent
            ok = e0[i] > floor
            ratio_db = np.full(len(eb[i]), np.nan)
            # grid.envelopes returns POWER envelopes (band_pump.curve uses 10*log10 on
            # them), so the gain in dB is 10*log10 of the ratio, not 20.
            ratio_db[ok] = 10 * np.log10((eb[i][ok] + 1e-12) / (e0[i][ok] + 1e-12))
            # fold the gain curve on the beat grid, median across beats
            beat = grid.FR * 60 / bpm; L = int(beat); beats = []
            for b in range(int((len(ratio_db) - ph) // beat)):
                s = int(round(ph + b * beat))
                seg = ratio_db[s:s + L]
                if s + L <= len(ratio_db) and np.isfinite(seg).mean() > 0.8:
                    beats.append(seg)
            if len(beats) < 8:
                row["bands"][name] = dict(error=f"only {len(beats)} usable beats"); continue
            m = np.nanmedian(np.stack(beats), axis=0)
            top = np.nanmax(m); depth = float(top - np.nanmin(m))
            t_min = int(np.nanargmin(m)) * 1000 / grid.FR
            row["bands"][name] = dict(gain_dip_db=round(depth, 2), dip_at_ms=round(t_min, 1),
                                      beats_used=len(beats), curve_db=[round(float(v), 2) for v in m[::max(1, L // 24)]])
        s = row["bands"].get(BANDS[0], {}).get("gain_dip_db"); l = row["bands"].get(BANDS[1], {}).get("gain_dip_db")
        row["sub_minus_low_db"] = round(s - l, 2) if s is not None and l is not None else None
        results.append(row)
    return dict(mode="bypass", kick=str(a.kick), bass=str(a.bass), bypass=str(a.bypass), **meta, windows=results,
                reading="gain_dip_db is the device's own curve. Checked on a synthetic 18 dB duck it reads 15.8 "
                        "in both bands: envelope smoothing under-reads a fast dip by about 2 dB, equally per band. "
                        "sub_minus_low_db >= 3 means the split duck the tools advertise is present; near 0 means "
                        "one curve for both bands. The split is exact even where the depth is slightly low.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["corpus", "calibrate", "bypass"])
    ap.add_argument("--kick", required=True, type=Path)
    ap.add_argument("--bass", type=Path)
    ap.add_argument("--bypass", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.mode in ("corpus", "bypass") and not a.bass:
        ap.error("--bass is required for this mode")
    if a.mode == "bypass" and not a.bypass:
        ap.error("--bypass is required: the same bass rendered with the ducking device off")
    res = {"corpus": mode_corpus, "calibrate": mode_calibrate, "bypass": mode_bypass}[a.mode](a)
    out = a.out or Path(f"duck_{a.mode}.json")
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:1500])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
