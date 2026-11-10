"""Compare pitch trackers on hummed notes.

    python3 -m humtrans.pitchbench track pyin crepe-tiny pesto fcpe swift crepe-full
    python3 -m humtrans.pitchbench score

HumTrans has no frame-level pitch truth, only the score each hummer heard.
So trackers are compared on what they share: the same recordings, the same
hummer errors. Per label note, the middle half (after the recording's own
delay) is read with each tracker. Measures:

  note_acc   the note's median pitch, after the recording's tuning and octave
             are removed, rounds to the label's semitone. Hummer errors cap it
             for every tracker alike; differences between trackers are theirs.
  voiced     share of note-middle frames the tracker calls pitched
  jumps      share of voiced note-middle frames more than a semitone from the
             note's median: jitter, octave slips, glitches
  auroc      how well the tracker's own confidence, averaged over the note,
             separates right notes from wrong ones (0.5 = no better than chance)
  x_rt       seconds of compute per second of audio on this machine

Sample: 15 TEST recordings per hummer, 150 in all, fixed seed.
"""
import json
import random
import sys
import time
from collections import defaultdict

import numpy as np

from .common import CACHE, OUT, WAV, ref_notes, split

SR, HOP = 16000, 160
F0 = CACHE / "f0"


def sample():
    by = defaultdict(list)
    for k in split("TEST"):
        by[k[:3]].append(k)
    rng = random.Random(1)
    return sorted(k for ks in by.values() for k in rng.sample(sorted(ks), 15))


def load(key):
    import librosa
    y, _ = librosa.load(WAV / f"{key}.wav", sr=SR)
    return y


def to_grid(t, f0, conf, n):
    """Resample a tracker's output onto 10 ms frames."""
    grid = np.arange(n) * HOP / SR
    idx = np.clip(np.searchsorted(t, grid), 0, len(t) - 1)
    prev = np.clip(idx - 1, 0, len(t) - 1)
    near = np.where(np.abs(t[prev] - grid) < np.abs(t[idx] - grid), prev, idx)
    return f0[near], conf[near]


def track(name, y):
    """Returns (f0 Hz or nan when unpitched, confidence 0-1) on 10 ms frames."""
    n = len(y) // HOP + 1
    if name == "pyin":
        import librosa
        f0, v, prob = librosa.pyin(y, fmin=65, fmax=1000, sr=SR, frame_length=1024, hop_length=HOP)
        return np.where(v, f0, np.nan)[:n], prob[:n]
    import torch
    torch.set_num_threads(4)
    x = torch.tensor(y)[None]
    if name.startswith("crepe"):
        import torchcrepe
        f, p = torchcrepe.predict(x, SR, HOP, 50, 1100, name.split("-")[1], batch_size=512,
                                  return_periodicity=True, device="cpu")
        f, p = f[0].numpy(), p[0].numpy()
        return np.where(p > 0.21, f, np.nan)[:n], p[:n]
    if name == "pesto":
        import pesto
        ts, f, c, _ = pesto.predict(x, SR, step_size=10.0)
        f, c = f[0].numpy(), c[0].numpy()
        return to_grid(ts.numpy() / 1000 if ts.max() > 100 else ts.numpy(), np.where(c > 0.5, f, np.nan), c, n)
    if name == "fcpe":
        from torchfcpe import spawn_bundled_infer_model
        global _fcpe
        if "_fcpe" not in globals():
            _fcpe = spawn_bundled_infer_model(device="cpu")
        f = _fcpe.infer(x[..., None], sr=SR, decoder_mode="local_argmax", threshold=0.006, f0_min=50,
                        f0_max=1100, interp_uv=False, output_interp_target_length=n)[0, :, 0].numpy()
        return np.where(f > 0, f, np.nan), (f > 0).astype(float)
    if name == "swift":
        from swift_f0 import SwiftF0
        r = SwiftF0().detect(y, SR)
        return to_grid(r.timestamps, np.where(r.confidence > 0.9, r.pitch_hz, np.nan), r.confidence, n)
    if name == "rmvpe":
        # RVC's RMVPE loader and checkpoint (lj1995/VoiceConversionWebUI rmvpe.pt),
        # from a directory given in RMVPE_DIR; its CUDA-graph hook is stubbed for CPU.
        import os
        sys.path.insert(0, os.environ["RMVPE_DIR"])
        from rvc_rmvpe import RMVPE
        global _rmvpe
        if "_rmvpe" not in globals():
            _rmvpe = RMVPE(os.path.join(os.environ["RMVPE_DIR"], "rmvpe.pt"), False, "cpu")
        hidden = _rmvpe.mel2hidden(_rmvpe.extract_mel(y)).squeeze(0).numpy()
        f = _rmvpe.decode(hidden, thred=0.03)[:n]
        return np.where(f > 0, f, np.nan), hidden.max(1)[:n]
    raise ValueError(name)


def cmd_track(names):
    keys = sample()
    for name in names:
        (F0 / name).mkdir(parents=True, exist_ok=True)
        spent = audio = 0.0
        for key in keys:
            path = F0 / name / f"{key}.npz"
            if path.exists():
                continue
            y = load(key)
            t = time.time()
            f0, conf = track(name, y)
            spent += time.time() - t
            audio += len(y) / SR
            np.savez_compressed(path, f0=f0.astype(np.float32), conf=conf.astype(np.float32))
        if audio:
            (F0 / name / "_speed.json").write_text(json.dumps({"x_rt": spent / audio}))
        print(name, "done", round(spent / audio, 3) if audio else "cached", flush=True)


def shift(x, n):
    """x moved n frames earlier (n > 0) or later, padded with nan."""
    out = np.full_like(x, np.nan)
    if n >= 0:
        out[: len(x) - n] = x[n:]
    else:
        out[-n:] = x[:n]
    return out


def recording_offsets(midi, ref):
    """Tuning (semitones), lag (frames) and octave (semitones) against the label."""
    ok = ~np.isnan(midi)
    dev = midi[ok] - np.round(midi[ok])
    tuning = float(np.angle(np.mean(np.exp(2j * np.pi * dev))) / (2 * np.pi)) if ok.any() else 0.0
    best = (-1, 0)
    for n in range(-10, 161):
        e = shift(midi, n)
        both = ~np.isnan(e) & ~np.isnan(ref)
        if both.sum() < 30:
            continue
        a = np.mean(np.abs((e[both] - tuning - ref[both] + 6) % 12 - 6) < 0.5)
        if a > best[0]:
            best = (a, n)
    e = shift(midi, best[1])
    both = ~np.isnan(e) & ~np.isnan(ref)
    octave = 12 * np.round(np.median(e[both] - tuning - ref[both]) / 12) if both.any() else 0.0
    return tuning, best[1], octave


def auroc(score, label):
    score, label = np.asarray(score), np.asarray(label, bool)
    if label.all() or not label.any():
        return float("nan")
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    npos = label.sum()
    return float((ranks[label].sum() - npos * (npos + 1) / 2) / (npos * (~label).sum()))


def cmd_score():
    names = sorted(p.name for p in F0.iterdir() if p.is_dir())
    keys = sample()
    res = {}
    for name in names:
        right, conf_mean, voiced, jumps = [], [], [], []
        per_singer = defaultdict(list)
        for key in keys:
            d = np.load(F0 / name / f"{key}.npz")
            with np.errstate(divide="ignore", invalid="ignore"):
                midi = 69 + 12 * np.log2(d["f0"] / 440.0)
            conf = d["conf"]
            iv, p = ref_notes(key)
            t = np.arange(len(midi)) * HOP / SR
            ref = np.full(len(t), np.nan)
            for (s, e), m in zip(iv, p):
                ref[(t >= s) & (t < e)] = m
            tuning, lag, octave = recording_offsets(midi, ref)
            for (s, e), m in zip(iv, p):
                a = int((s + (e - s) / 4) * SR / HOP) + lag
                b = int((e - (e - s) / 4) * SR / HOP) + lag
                seg, cseg = midi[a:b], conf[a:b]
                if len(seg) < 3:
                    continue
                v = ~np.isnan(seg)
                voiced.append(v.mean())
                if v.sum() < 2:
                    right.append(False)
                    conf_mean.append(float(np.mean(cseg)) if len(cseg) else 0.0)
                    per_singer[key[:3]].append(False)
                    continue
                med = np.median(seg[v])
                jumps.append(np.mean(np.abs(seg[v] - med) > 1))
                hit = bool(np.round(med - tuning - octave) == m)
                right.append(hit)
                per_singer[key[:3]].append(hit)
                conf_mean.append(float(np.mean(cseg)))
        speed = json.loads((F0 / name / "_speed.json").read_text())["x_rt"] if (F0 / name / "_speed.json").exists() else None
        res[name] = {"notes": len(right), "note_acc": round(float(np.mean(right)), 4),
                     "voiced": round(float(np.mean(voiced)), 4), "jumps": round(float(np.mean(jumps)), 4),
                     "auroc": round(auroc(conf_mean, right), 3), "x_rt": round(speed, 3) if speed else None,
                     "note_acc_by_singer": {s: round(float(np.mean(v)), 3) for s, v in sorted(per_singer.items())}}
        print(name, json.dumps({k: v for k, v in res[name].items() if k != "note_acc_by_singer"}), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pitchbench.json").write_text(json.dumps(res, indent=1))


def main():
    if sys.argv[1] == "track":
        cmd_track(sys.argv[2:])
    else:
        cmd_score()


if __name__ == "__main__":
    main()
