"""Describe the HumTrans dataset: what is in it, and how the humming departs from its labels.

    python3 -m humtrans.characterize meta     # all 14,614 recordings: names, split, labels
    python3 -m humtrans.characterize audio    # all recordings: level, clipping, noise floor
    python3 -m humtrans.characterize perform  # recordings with cached pYIN: lag, tuning, octave, pitch

Writes out/humtrans/characterize_<part>.json. The perform part needs
`python3 -m humtrans.transcribe pyin ...` first and covers whatever it has done.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pretty_midi
import soundfile as sf

from .common import CACHE, MIDI, OUT, WAV, load_notes, ref_notes, split

NAME = re.compile(r"^([FM]\d\d)_(\d{4})_(\d{4})_(\d)(?:_(U+|D+))?$")


def parse(key):
    singer, piece, seg, take, octave = NAME.match(key).groups()
    return {"singer": singer, "piece": piece, "segment": f"{piece}_{seg}", "take": take,
            "suffix": octave or "", "octaves": (octave or "").count("U") - (octave or "").count("D")}


def all_keys():
    return [(k, s) for s in ("TRAIN", "VALID", "TEST") for k in split(s)]


def pct(x, q=(5, 25, 50, 75, 95)):
    return dict(zip([f"p{v}" for v in q], np.percentile(x, q).round(4).tolist()))


def meta():
    keys = all_keys()
    rows = []
    for k, s in keys:
        m = pretty_midi.PrettyMIDI(str(MIDI / f"{k}.mid"))
        n = m.instruments[0].notes
        iv = np.array([[x.start, x.end] for x in n])
        p = np.array([x.pitch for x in n])
        rows.append({**parse(k), "key": k, "split": s, "dur": float(iv[-1, 1]), "n": len(n),
                     "tempo": float(m.get_tempo_changes()[1][0]), "resolution": m.resolution,
                     "pmin": int(p.min()), "pmax": int(p.max()), "first_onset": float(iv[0, 0]),
                     "note_durs": (iv[:, 1] - iv[:, 0]).tolist(),
                     "gaps": (iv[1:, 0] - iv[:-1, 1]).tolist(), "pitches": p.tolist()})
    out = {"recordings": len(rows)}
    out["hours"] = {s: round(sum(r["dur"] for r in rows if r["split"] == s) / 3600, 2)
                    for s in ("TRAIN", "VALID", "TEST")}
    out["per_singer"] = {s: {"recordings": sum(1 for r in rows if r["singer"] == s),
                             "hours": round(sum(r["dur"] for r in rows if r["singer"] == s) / 3600, 2),
                             "suffix": dict(Counter(r["suffix"] for r in rows if r["singer"] == s))}
                         for s in sorted({r["singer"] for r in rows})}
    out["suffix"] = dict(Counter(r["suffix"] for r in rows))
    out["takes"] = dict(Counter(r["take"] for r in rows))
    segs = defaultdict(set)
    for r in rows:
        segs[r["segment"]].add(r["singer"])
    out["singers_per_segment"] = dict(sorted(Counter(len(v) for v in segs.values()).items()))
    pieces = defaultdict(set)
    for r in rows:
        pieces[r["piece"]].add(r["segment"])
    out["segments_per_piece"] = dict(sorted(Counter(len(v) for v in pieces.values()).items()))
    tr = {r["piece"] for r in rows if r["split"] == "TRAIN"}
    out["held_out_pieces"] = {s: float(np.mean([r["piece"] not in tr for r in rows if r["split"] == s]))
                              for s in ("VALID", "TEST")}
    tr_singers = {r["singer"] for r in rows if r["split"] == "TRAIN"}
    out["unseen_singers_in_eval"] = sorted({r["singer"] for r in rows if r["split"] != "TRAIN"} - tr_singers)
    # Labels of one segment differ between recordings only by the recording's
    # octave suffix and by note length (two MIDI exports); onsets agree.
    byseg = defaultdict(list)
    for r in rows:
        byseg[r["segment"]].append(r)
    onset_diff, shift_ok, off_diff = [], [], []
    for rs in byseg.values():
        a = rs[0]
        ia, _ = ref_notes(a["key"])
        for b in rs[1:]:
            ib, _ = ref_notes(b["key"])
            if len(ib) != len(ia):
                onset_diff.append(np.inf)
                continue
            onset_diff.append(float(np.abs(ib[:, 0] - ia[:, 0]).max()))
            off_diff.append(float(np.abs(ib[:, 1] - ia[:, 1]).max()))
            d = np.array(b["pitches"]) - np.array(a["pitches"])
            shift_ok.append(bool(np.all(d == 12 * (b["octaves"] - a["octaves"]))))
    out["label_consistency"] = {
        "pairs": len(onset_diff), "onsets_identical": float(np.mean(np.array(onset_diff) < 1e-3)),
        "pitch_shift_equals_suffix": float(np.mean(shift_ok)),
        "offset_diff_s": pct(off_diff), "resolution": dict(Counter(r["resolution"] for r in rows))}
    nd = np.concatenate([r["note_durs"] for r in rows])
    gaps = np.concatenate([r["gaps"] for r in rows])
    allp = np.concatenate([r["pitches"] for r in rows])
    out["labels"] = {
        "notes": int(len(nd)), "recording_s": pct([r["dur"] for r in rows]),
        "tempo_bpm": pct([r["tempo"] for r in rows]),
        "notes_per_s": pct([r["n"] / r["dur"] for r in rows]),
        "note_s": pct(nd), "notes_under_100ms": float(np.mean(nd < 0.1)),
        "gap_s": pct(gaps), "legato_fraction": float(np.mean(gaps < 0.01)),
        "range_semitones": pct([r["pmax"] - r["pmin"] for r in rows]),
        "pitch": pct(allp), "first_onset_zero": float(np.mean([r["first_onset"] == 0 for r in rows])),
        "repeated_pitch_fraction": float(np.mean([np.mean(np.diff(r["pitches"]) == 0) for r in rows if r["n"] > 1])),
        "interval_abs_semitones": pct(np.abs(np.concatenate([np.diff(r["pitches"]) for r in rows]))),
    }
    return out


def audio_one(key):
    y, sr = sf.read(str(WAV / f"{key}.wav"), dtype="float32")
    hop = sr // 100
    frames = y[: len(y) // hop * hop].reshape(-1, hop)
    db = 10 * np.log10(np.mean(frames ** 2, 1) + 1e-12)
    iv, _ = ref_notes(key)
    return {"key": key, "sr": sr, "channels": 1 if y.ndim == 1 else y.shape[1],
            "dur_minus_label": round(len(y) / sr - float(iv[-1, 1]), 4),
            "peak_db": float(20 * np.log10(np.abs(y).max() + 1e-12)),
            "clipped": float(np.mean(np.abs(y) >= 0.999)),
            "active_db": float(np.percentile(db, 90)), "floor_db": float(np.percentile(db, 10)),
            "dc": float(np.mean(y))}


def audio():
    keys = [k for k, _ in all_keys()]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(audio_one, keys, chunksize=32))
    by = defaultdict(list)
    for r in rows:
        by[parse(r["key"])["singer"]].append(r)
    snr = np.array([r["active_db"] - r["floor_db"] for r in rows])
    return {"sample_rates": dict(Counter(r["sr"] for r in rows)),
            "channels": dict(Counter(r["channels"] for r in rows)),
            "audio_length_equals_label_end": float(np.mean(np.abs([r["dur_minus_label"] for r in rows]) < 0.01)),
            "peak_db": pct([r["peak_db"] for r in rows]),
            "any_clipping": float(np.mean([r["clipped"] > 0 for r in rows])),
            "clipped_over_0.1pct": float(np.mean([r["clipped"] > 0.001 for r in rows])),
            "active_db": pct([r["active_db"] for r in rows]),
            "floor_db": pct([r["floor_db"] for r in rows]),
            "active_minus_floor_db": pct(snr),
            "per_singer": {s: {"active_db": round(float(np.median([r["active_db"] for r in rs])), 1),
                               "floor_db": round(float(np.median([r["floor_db"] for r in rs])), 1),
                               "active_minus_floor_db": round(float(np.median([r["active_db"] - r["floor_db"] for r in rs])), 1)}
                           for s, rs in sorted(by.items())}}


def perform_one(key):
    from .evaluate import f0_lag
    _, _, d = load_notes(CACHE / "pyin" / f"{key}.json")
    f0 = np.array([np.nan if v is None else v for v in d["f0_midi"]])
    lag, agree = f0_lag(key)
    lag0, _ = f0_lag(key, 0)
    lag1, _ = f0_lag(key, 1)
    iv, p = ref_notes(key)
    t = np.arange(len(f0)) * 0.01
    ref = np.full(len(t), np.nan)
    for (s, e), m in zip(iv, p):
        ref[(t >= s + lag) & (t < e + lag)] = m
    ok = ~np.isnan(f0) & ~np.isnan(ref)
    dev = f0[ok] - d["tuning"] - ref[ok]
    octave = int(np.round(np.median(dev) / 12)) if ok.sum() else 0
    folded = (dev + 6) % 12 - 6
    # Cents error of held notes, tuning removed, octave folded, middle half of each note only.
    mids = np.zeros(len(t), bool)
    for s, e in iv:
        a, b = s + lag + (e - s) / 4, e + lag - (e - s) / 4
        mids |= (t >= a) & (t < b)
    okm = ok & mids
    cents = ((f0[okm] - d["tuning"] - ref[okm] + 6) % 12 - 6) * 100
    last = iv[-1]
    tail = (t >= last[0] + lag) & (t < last[1])
    return {"key": key, **parse(key), "lag": lag, "lag_first_half": lag0, "lag_second_half": lag1,
            "agree": agree, "tuning_cents": round(100 * d["tuning"], 1),
            "octave_vs_label": octave,
            "within_50c": float(np.mean(np.abs(folded) < 0.5)) if ok.sum() else None,
            "note_cents_abs_median": float(np.median(np.abs(cents))) if len(cents) else None,
            "voiced_in_label_notes": float(np.mean(~np.isnan(f0[~np.isnan(ref)]))) if (~np.isnan(ref)).sum() else None,
            "last_note_kept_s": round(float(last[1] - (last[0] + lag)), 3),
            "last_note_s": round(float(last[1] - last[0]), 3),
            "voiced_before_first_note": float(np.mean(~np.isnan(f0[t < iv[0, 0]]))) if iv[0, 0] > 0.1 else None,
            "voiced_at_end": bool(np.any(~np.isnan(f0[tail]))) if tail.any() else False}


def perform():
    keys = [k for k, _ in all_keys() if (CACHE / "pyin" / f"{k}.json").exists()]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(perform_one, keys, chunksize=8))
    (OUT / "perform_rows.json").write_text(json.dumps(rows))
    ok = [r for r in rows if r["agree"] > 0.5]

    def summ(rs):
        return {"n": len(rs), "lag_s": pct([r["lag"] for r in rs]),
                "lag_drift_s": pct([r["lag_second_half"] - r["lag_first_half"] for r in rs]),
                "tuning_cents": pct([r["tuning_cents"] for r in rs]),
                "within_50c": pct([r["within_50c"] for r in rs if r["within_50c"] is not None]),
                "note_cents_abs_median": pct([r["note_cents_abs_median"] for r in rs if r["note_cents_abs_median"] is not None]),
                "octave_vs_label": dict(Counter(r["octave_vs_label"] for r in rs)),
                "voiced_in_label_notes": pct([r["voiced_in_label_notes"] for r in rs if r["voiced_in_label_notes"] is not None])}
    by = defaultdict(list)
    for r in ok:
        by[r["singer"]].append(r)
    return {"recordings": len(rows), "aligned (agree > 0.5)": len(ok),
            "all": summ(ok), "per_singer": {s: summ(rs) for s, rs in sorted(by.items())},
            "last_note_truncated_fraction": pct([1 - r["last_note_kept_s"] / r["last_note_s"] for r in ok]),
            "octave_vs_label_by_suffix": {sfx: dict(Counter(r["octave_vs_label"] for r in ok if r["suffix"] == sfx))
                                          for sfx in sorted({r["suffix"] for r in ok})}}


def main():
    part = sys.argv[1]
    res = {"meta": meta, "audio": audio, "perform": perform}[part]()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"characterize_{part}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
