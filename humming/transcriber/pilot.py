"""First look at Anthony's calibration takes of known songs.

    python3 -m transcriber.pilot <folder of wavs> [-o out/pilot.json]

File names: <song>_free.wav, <song>_click_<n>.wav, where <song> is a
reference in transcriber/refs/ or transcriber/refs_private/ (happy_birthday,
jingle_bells_chorus, mario_overworld). Anything else in the folder is skipped.

Per take:
  click    (click takes) the metronome as the microphone heard it: tempo,
           phase, and how steady it is. The click is played through a
           speaker so its recorded times are the true grid; no latency guess.
  notes    note starts from the onset detector, pitch from SwiftF0 over each
           note's middle half, tuning removed.
  align    the take against the reference, free of key and tempo: the
           transposition that best fits, then a dynamic-programming match of
           notes that allows missed and extra notes.
  errors   per matched note: pitch error in cents (after transposition and
           tuning), timing error against a straight-line fit of onset time
           to score beat, missed and extra notes.
  vs click (click takes) where each hummed note starts against the click
           grid, in ms: the singer's asynchrony, as a distribution.

Across takes of one song:
  agreement  every pair of click takes scored against each other with the
             paper's note metric (50 ms, exact semitone), after lining up
             their keys and grids. This is the ceiling from the design note;
             the note predicts it will be above 90 in 100.
"""
import argparse
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import mir_eval
import numpy as np

HERE = Path(__file__).resolve().parent
SR = 16000
HOP = 160  # 10 ms


# ---- references -----------------------------------------------------------

def load_ref(song):
    for d in ("refs", "refs_private"):
        p = HERE / d / f"{song}.json"
        if p.exists():
            r = json.loads(p.read_text())
            beats = np.cumsum([0] + [n["beats"] for n in r["notes"]])
            return {"pitch": np.array([n["pitch"] for n in r["notes"]], float),
                    "beat": beats[:-1], "dur": np.diff(beats), "meta": r}
    return None


# ---- audio ----------------------------------------------------------------

def load(path, sr=SR):
    import librosa
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y


def pitch_track(y):
    """SwiftF0 on 10 ms frames: MIDI pitch (nan when unpitched) and confidence."""
    from swift_f0 import SwiftF0
    r = SwiftF0().detect(y, SR)
    n = len(y) // HOP + 1
    grid = np.arange(n) * HOP / SR
    idx = np.clip(np.searchsorted(r.timestamps, grid), 0, len(r.timestamps) - 1)
    f0 = np.where(r.confidence[idx] >= 0.9, r.pitch_hz[idx], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69 + 12 * np.log2(f0 / 440.0)
    return midi, r.confidence[idx]


def onsets(path):
    """Note starts: madmom's CNN detector if installed, else SuperFlux."""
    try:
        from madmom.features.onsets import CNNOnsetProcessor, OnsetPeakPickingProcessor
        act = CNNOnsetProcessor()(str(path))
        return np.asarray(OnsetPeakPickingProcessor(fps=100, threshold=0.5, combine=0.02)(act))
    except ImportError:
        import librosa
        y, sr = librosa.load(path, sr=22050)
        S = librosa.feature.melspectrogram(y=y, sr=sr, hop_length=256, n_mels=138, fmin=27.5, fmax=11000)
        env = librosa.onset.onset_strength(S=librosa.power_to_db(S), sr=sr, hop_length=256, lag=2, max_size=3)
        return librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=256, units="time")


def click_grid(path):
    """Click times from high-band transients, fitted to a straight grid.

    Returns (period s, phase s, residual ms, click times) or None. The fit is a
    robust line through transients that sit on a common period; voice
    transients ("d" bursts) fall off the line and are dropped.
    """
    import librosa
    from scipy.signal import butter, sosfilt, find_peaks
    y, sr = librosa.load(path, sr=44100, mono=True)
    hp = sosfilt(butter(4, 5000, "highpass", fs=sr, output="sos"), y)
    env = np.convolve(np.abs(hp), np.ones(44) / 44, "same")
    peaks, _ = find_peaks(env, height=np.percentile(env, 99.5) * 0.3, distance=int(0.15 * sr))
    t = peaks / sr
    if len(t) < 6:
        return None
    ioi = np.diff(t)
    period = np.median(ioi)
    for _ in range(3):  # refine on intervals near one period
        good = np.abs(ioi / period - 1) < 0.1
        if good.sum() < 4:
            return None
        period = np.median(ioi[good])
    k = np.round((t - t[0]) / period)
    for _ in range(3):  # robust line fit time = phase + k * period
        A = np.c_[np.ones_like(k), k]
        coef, *_ = np.linalg.lstsq(A, t, rcond=None)
        res = t - A @ coef
        keep = np.abs(res) < max(0.01, 3 * np.median(np.abs(res)))
        t, k = t[keep], k[keep]
    phase, period = coef
    return float(period), float(phase), float(1000 * np.std(t - (phase + k * period))), t.tolist()


def voicing_starts(midi, gap=3):
    """Times where pitched sound begins after at least `gap` unpitched frames."""
    v = ~np.isnan(midi)
    out = []
    for i in range(gap, len(v)):
        if v[i] and not v[i - gap:i].any():
            out.append(i * HOP / SR)
    return np.array(out)


def drop_clicks(on, clicks, midi):
    """Replace metronome-contaminated starts with voice-based ones.

    Detector starts within 15 ms of a recorded click are dropped: the click
    masks the consonant. Near each click, a note start is then put back if
    the pitch track shows voicing beginning within 150 ms, at that voicing
    start minus this take's usual consonant-to-voicing lead, measured on the
    starts away from any click. A click inside a held note adds nothing.
    """
    if clicks is None or not len(clicks):
        return on, None
    clicks = np.asarray(clicks)
    vs = voicing_starts(midi)
    far = np.array([t for t in on if np.min(np.abs(clicks - t)) > 0.015])
    leads = [v - t for t in far for v in vs[(vs >= t) & (vs < t + 0.1)][:1]]
    lead = float(np.median(leads)) if leads else 0.0
    add = []
    for c in clicks:
        cand = vs[(vs >= c - 0.03) & (vs <= c + 0.15)]
        for v in cand[:1]:
            t = v - lead
            if not len(far) or np.min(np.abs(far - t)) > 0.06:
                add.append(t)
    return np.sort(np.r_[far, add]), lead


def notes_of(path, clicks=None):
    y = load(path)
    midi, conf = pitch_track(y)
    on, lead = drop_clicks(onsets(path), clicks, midi)
    ok = ~np.isnan(midi)
    dev = midi[ok] - np.round(midi[ok])
    tuning = float(np.angle(np.mean(np.exp(2j * np.pi * dev))) / (2 * np.pi)) if ok.any() else 0.0
    ends = np.r_[on[1:], len(y) / SR]
    out = []
    for s, e in zip(on, ends):
        a, b = int(s * SR / HOP), int(e * SR / HOP)
        seg = midi[a:b]
        v = ~np.isnan(seg)
        if v.sum() < 3:  # an onset with no pitched sound after it: a click or a breath
            continue
        idx = np.flatnonzero(v)
        last = a + idx[-1]
        mid = seg[idx[len(idx) // 4: max(len(idx) // 4 + 1, 3 * len(idx) // 4)]]
        out.append({"on": float(s), "off": float((last + 1) * HOP / SR), "pitch_raw": float(np.median(mid)),
                    "conf": float(np.mean(conf[a:b]))})
    for n in out:
        n["pitch"] = int(np.round(n["pitch_raw"] - tuning))
        n["cents_from_semitone"] = round(100 * (n["pitch_raw"] - tuning - n["pitch"]), 1)
    return out, tuning


# ---- alignment ------------------------------------------------------------

def align(sung, ref):
    """Transposition, then a DP note match allowing misses and extras.

    Cost of matching sung note i to ref note j is the pitch difference in
    semitones (capped at 3) after transposition; a skip costs 1.5.
    """
    sp = np.array([n["pitch"] for n in sung], float)
    best = None
    for tr in range(-36, 37):
        d = np.abs(sp[:, None] + tr - ref["pitch"][None, :])
        score = np.mean(np.min(d, 1) == 0)
        if best is None or score > best[0]:
            best = (score, tr)
    tr = best[1]
    n, m = len(sp), len(ref["pitch"])
    SKIP = 1.5
    D = np.full((n + 1, m + 1), np.inf)
    D[0, :] = np.arange(m + 1) * SKIP
    D[:, 0] = np.arange(n + 1) * SKIP
    back = np.zeros((n + 1, m + 1), int)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = min(abs(sp[i - 1] + tr - ref["pitch"][j - 1]), 3)
            opts = (D[i - 1, j - 1] + c, D[i - 1, j] + SKIP, D[i, j - 1] + SKIP)
            back[i, j] = int(np.argmin(opts))
            D[i, j] = opts[back[i, j]]
    i, j, pairs = n, m, []
    while i > 0 and j > 0:
        if back[i, j] == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif back[i, j] == 1:
            i -= 1
        else:
            j -= 1
    return tr, pairs[::-1]


def take_report(path, ref, grid=None):
    sung, tuning = notes_of(path, grid[3] if grid else None)
    if not sung:
        return {"file": path.name, "notes": 0}
    tr, pairs = align(sung, ref)
    si = np.array([p[0] for p in pairs])
    ri = np.array([p[1] for p in pairs])
    on = np.array([sung[i]["on"] for i in si])
    beat = ref["beat"][ri]
    # Straight-line tempo fit: onset = t0 + beat * seconds_per_beat
    A = np.c_[np.ones_like(beat), beat]
    coef, *_ = np.linalg.lstsq(A, on, rcond=None)
    timing_ms = 1000 * (on - A @ coef)
    pitch_err = np.array([sung[i]["pitch"] + tr - ref["pitch"][j] for i, j in pairs])
    cents = np.array([sung[i]["cents_from_semitone"] for i in si])
    rep = {"file": path.name, "notes_sung": len(sung), "notes_ref": len(ref["pitch"]),
           "matched": len(pairs), "extra": len(sung) - len(pairs), "missed": len(ref["pitch"]) - len(pairs),
           "transpose": tr, "tuning_cents": round(100 * tuning, 1),
           "tempo_bpm_fit": round(60 / coef[1], 1) if coef[1] > 0 else None,
           "pitch_exact": round(float(np.mean(pitch_err == 0)), 3),
           "pitch_off_by": {int(k): int(v) for k, v in zip(*np.unique(pitch_err, return_counts=True))},
           "cents_within_semitone_abs_median": round(float(np.median(np.abs(cents))), 1),
           "timing_vs_line_ms_abs_median": round(float(np.median(np.abs(timing_ms))), 1),
           "timing_vs_line_ms_p90": round(float(np.percentile(np.abs(timing_ms), 90)), 1),
           "notes": sung}
    if grid:
        period, phase, resid, _ = grid
        k = np.round((on - phase) / period * 2) / 2  # nearest half beat
        asyn = 1000 * (on - (phase + k * period))
        rep["click"] = {"bpm": round(60 / period, 2), "click_jitter_ms": round(resid, 2),
                        "asynchrony_ms_median": round(float(np.median(asyn)), 1),
                        "asynchrony_ms_iqr": [round(float(x), 1) for x in np.percentile(asyn, [25, 75])]}
    return rep


def agreement(a, b, grid_a, grid_b):
    """Two click takes scored against each other, keys and grids lined up.

    Take b's onsets are mapped onto take a's timeline through the two click
    grids (beat number is shared); b's pitches are moved by the difference in
    transposition. Then mir_eval note F1 with 50 ms onsets, exact semitone,
    offsets ignored, as in the paper's metric.
    """
    pa, pha = grid_a[0], grid_a[1]
    pb, phb = grid_b[0], grid_b[1]
    on_a = np.array([n["on"] for n in a["notes"]])
    on_b = pha + (np.array([n["on"] for n in b["notes"]]) - phb) / pb * pa
    # Downbeats of the two takes may differ by whole beats; try small shifts.
    best = 0.0
    for shift in range(-8, 9):
        ob = on_b + shift * pa
        p_a = np.array([n["pitch"] + a["transpose"] for n in a["notes"]], float)
        p_b = np.array([n["pitch"] + b["transpose"] for n in b["notes"]], float)
        keep = ob >= 0
        iv_a = np.c_[on_a, on_a + 0.1]
        iv_b = np.c_[ob[keep], ob[keep] + 0.1]
        p_b = p_b[keep]
        f = mir_eval.transcription.precision_recall_f1_overlap(
            iv_a, mir_eval.util.midi_to_hz(p_a), iv_b, mir_eval.util.midi_to_hz(p_b),
            onset_tolerance=0.05, pitch_tolerance=50, offset_ratio=None)[2]
        best = max(best, f)
    return round(float(best), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("-o", "--out", default=str(HERE.parent / "out" / "pilot.json"))
    a = ap.parse_args()
    takes = defaultdict(list)
    for p in sorted(Path(a.folder).glob("*.wav")):
        parts = p.stem.split("_")
        kind_at = next((i for i, x in enumerate(parts) if x in ("free", "click")), None)
        if kind_at is None:
            continue
        takes["_".join(parts[:kind_at])].append((parts[kind_at], p))
    res = {}
    for song, files in takes.items():
        ref = load_ref(song)
        if ref is None:
            print("no reference for", song)
            continue
        reps, grids = [], []
        for kind, p in files:
            grid = click_grid(p) if kind == "click" else None
            rep = take_report(p, ref, grid)
            rep["kind"] = kind
            reps.append(rep)
            grids.append(grid)
            print(song, p.name, {k: v for k, v in rep.items() if k != "notes"}, flush=True)
        clicked = [(r, g) for r, g in zip(reps, grids) if g]
        res[song] = {"takes": reps,
                     "agreement_pairs": [{"a": r1["file"], "b": r2["file"], "note_F1": agreement(r1, r2, g1, g2)}
                                         for (r1, g1), (r2, g2) in combinations(clicked, 2)]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
