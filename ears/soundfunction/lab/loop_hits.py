#!/usr/bin/env python3
"""
Per-hit measures on a LOOP: segment by onset, describe each hit, summarise.

`analysis.run hits` treats a file as one hit, so on a 12 s loop it returns
the file length as the decay (13.7 s, sustain 0.997, every row of the kick
group knob map). This splits the loop at onsets first, then runs the same
one-shot measures on each hit and the same envelope timings as
`analysis/hits_extra.py`, and writes both the per-hit rows and a per-file
summary (medians) that a knob-map row can carry.

    python3 lab/loop_hits.py <wav-or-folder> [-o out.csv] [--min-gap-ms 120] [--max-hit-ms 800]

Summary columns per file: n_hits, and the median of decay20_ms, decay40_ms,
sustain_share, crest_factor_db, attack_ms, band_sub_share across hits.
"""
import argparse, csv, statistics as st, sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.signal_features import describe_hit          # noqa: E402
from analysis.hits_extra import env_timings                # noqa: E402

SUMMARY_KEYS = ["decay20_ms", "decay40_ms", "sustain_share", "crest_factor_db", "attack_ms", "band_sub_share"]


def onsets(y, sr, min_gap_ms):
    """Onset sample indices, at least min_gap_ms apart, strongest kept on conflict."""
    o_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
    frames = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, hop_length=256, units="frames",
                                        backtrack=True, pre_max=3, post_max=3, pre_avg=10, post_avg=10,
                                        delta=0.2, wait=int(min_gap_ms / 1000 * sr / 256))
    idx = librosa.frames_to_samples(frames, hop_length=256)
    # Enforce the gap ourselves: librosa's `wait` is advisory once backtracking
    # moves onsets, and a low kick's first cycles can trigger twice.
    gap = int(min_gap_ms / 1000 * sr); w = int(0.03 * sr); kept = []
    for i in sorted(int(i) for i in idx):
        if i >= len(y) - sr * 0.01:
            continue
        if kept and i - kept[-1] < gap:
            continue
        # A hit is a RISE in level. Spectral flux also fires on an abrupt stop
        # (a gated tail, a clipped loop end), so require the 30 ms after the
        # onset to be at least 3 dB louder than the 30 ms before it.
        before = np.sqrt(np.mean(y[max(0, i - w):i] ** 2)) + 1e-12 if i > 0 else 1e-12
        after = np.sqrt(np.mean(y[i:i + w] ** 2)) + 1e-12
        if 20 * np.log10(after / before) < 3.0:
            continue
        kept.append(i)
    return kept


def hits_of(path, min_gap_ms, max_hit_ms):
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    on = onsets(y, sr, min_gap_ms)
    rows = []
    for j, s0 in enumerate(on):
        s1 = on[j + 1] if j + 1 < len(on) else len(y)
        s1 = min(s1, s0 + int(max_hit_ms / 1000 * sr))
        seg = y[s0:s1]
        if len(seg) < sr * 0.02 or not np.any(seg):
            continue
        try:
            f = describe_hit(seg, sr)
        except Exception as e:  # noqa: BLE001
            continue
        f.update(env_timings(seg, sr))
        f.update(file=str(path), hit=j, onset_s=round(s0 / sr, 4), hit_len_ms=round((s1 - s0) / sr * 1000, 1))
        rows.append(f)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("-o", "--out", default="loop_hits.csv")
    ap.add_argument("--min-gap-ms", type=float, default=120.0)
    ap.add_argument("--max-hit-ms", type=float, default=800.0)
    a = ap.parse_args()

    files = []
    for p in a.paths:
        p = Path(p)
        files += sorted(p.rglob("*.wav")) if p.is_dir() else [p]
    all_rows, summary = [], []
    for f in files:
        rows = hits_of(f, a.min_gap_ms, a.max_hit_ms)
        all_rows += rows
        s = dict(file=str(f), n_hits=len(rows))
        for k in SUMMARY_KEYS:
            v = [r[k] for r in rows if r.get(k) is not None and np.isfinite(r[k])]
            s[k + "_median"] = round(st.median(v), 4) if v else None
        summary.append(s)
        print(f"{f.name}: {len(rows)} hits; decay40 median {s['decay40_ms_median']} ms; sustain {s['sustain_share_median']}; crest {s['crest_factor_db_median']}")
    if all_rows:
        keys = sorted({k for r in all_rows for k in r})
        with open(a.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(all_rows)
    sp = Path(a.out).with_suffix(".summary.csv")
    with open(sp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)
    print(f"wrote {a.out} and {sp}")


if __name__ == "__main__":
    main()
