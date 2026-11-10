"""Features of a sound's *use* inside a full mix (no isolated stems).

See analysis/README.md for a plain-language description of every field.
"""
from __future__ import annotations

import numpy as np
import librosa
import scipy.signal as ss

from .signal_features import BANDS, EPS

N_STEPS = 16          # 16th-note grid per bar
BEAT_BINS = (0, 4, 8, 12)   # quarter-note positions within the 16-step grid
OFFBEAT8_BINS = (2, 6, 10, 14)  # the "and" of each beat


def _band_envelopes(y, sr, n_fft=2048, hop=512):
    """Per-band magnitude envelope and half-wave-rectified flux (onset envelope)."""
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop)
    energy, flux = {}, {}
    for name, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        band_e = S[mask, :].sum(axis=0) if mask.any() else np.zeros(S.shape[1])
        energy[name] = band_e
        d = np.diff(band_e, prepend=band_e[0])
        flux[name] = np.maximum(d, 0.0)
    return energy, flux, times, hop


def _correct_tempo(tempo):
    tempo = float(np.atleast_1d(tempo)[0])
    candidates = {"none": tempo, "doubled": tempo * 2, "halved": tempo / 2}
    # hard techno lives ~130-190 BPM; pick whichever candidate lands there
    best_label, best_val = "none", tempo
    best_dist = abs(tempo - 152) if 130 <= tempo <= 190 else 1e9
    for label, val in candidates.items():
        if 130 <= val <= 190:
            d = abs(val - 152)
            if d < best_dist:
                best_dist, best_label, best_val = d, label, val
    return tempo, best_val, best_label


def _bar_grid(beat_times):
    """Build a flat 16th-note grid labelled (bar_idx, step_idx) from quarter-note beats."""
    n_full_beats = (len(beat_times) - 1)
    n_bars = n_full_beats // 4
    grid_times, grid_bar, grid_step = [], [], []
    for bar in range(n_bars):
        for beat_in_bar in range(4):
            b = bar * 4 + beat_in_bar
            t0, t1 = beat_times[b], beat_times[b + 1]
            for sub in range(4):
                grid_times.append(t0 + (t1 - t0) * sub / 4.0)
                grid_bar.append(bar)
                grid_step.append(beat_in_bar * 4 + sub)
    return np.array(grid_times), np.array(grid_bar), np.array(grid_step), n_bars


def _fold_onsets(onset_times, grid_times, grid_bar, grid_step, n_bars):
    """Nearest-grid-point assignment of onset times to (bar, 16th-step)."""
    hist = np.zeros((max(n_bars, 1), N_STEPS))
    if len(grid_times) == 0 or len(onset_times) == 0:
        return hist
    idx = np.searchsorted(grid_times, onset_times)
    idx = np.clip(idx, 1, len(grid_times) - 1)
    left, right = idx - 1, idx
    use_left = np.abs(onset_times - grid_times[left]) <= np.abs(grid_times[right] - onset_times)
    chosen = np.where(use_left, left, right)
    for c in chosen:
        hist[grid_bar[c], grid_step[c]] += 1
    return hist


def _autocorr_at(env, sr, hop, lag_s):
    ac = librosa.autocorrelate(env, max_size=len(env))
    lag_frames = int(round(lag_s * sr / hop))
    if lag_frames <= 0 or lag_frames >= len(ac) or ac[0] <= EPS:
        return float("nan")
    return float(ac[lag_frames] / ac[0])


def describe_track(path: str, npy_path: str | None = None) -> dict:
    y, sr = librosa.load(path, sr=None, mono=True)
    duration_s = len(y) / sr

    hop = 512
    energy, flux, frame_times, hop = _band_envelopes(y, sr, hop=hop)
    # Beat-track from a kick-weighted (sub+low) onset envelope rather than the
    # full-mix envelope: in hard techno the kick carries the pulse far more
    # reliably than hi-hats/percussion, which can otherwise pull the beat grid
    # onto the wrong phase.
    kick_env = flux["sub"] + flux["low"]
    tempo_raw, tempo_corrected, correction = _correct_tempo(
        librosa.beat.beat_track(onset_envelope=kick_env, sr=sr, hop_length=hop)[0])
    _, beat_frames = librosa.beat.beat_track(
        onset_envelope=kick_env, sr=sr, hop_length=hop, start_bpm=tempo_corrected)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)

    grid_times, grid_bar, grid_step, n_bars = _bar_grid(beat_times)
    if n_bars < 1:
        n_bars = 0

    bands = list(BANDS.keys())
    bar_matrix = np.zeros((len(bands), max(n_bars, 1)))
    bar_edges = beat_times[0::4] if len(beat_times) >= 5 else np.array([0.0, duration_s])

    per_band = {}
    kick_bins = {"sub", "low"}
    kick_hist_total = np.zeros((max(n_bars, 1), N_STEPS))

    for bi, name in enumerate(bands):
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=flux[name], sr=sr, hop_length=hop, backtrack=False)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)

        hist = _fold_onsets(onset_times, grid_times, grid_bar, grid_step, n_bars)
        total_hits = hist.sum()
        profile = (hist.sum(axis=0) / total_hits) if total_hits > 0 else hist.sum(axis=0)
        top_bins = [int(i) for i in np.argsort(-profile)[:3]]

        beat_energy = float(profile[list(BEAT_BINS)].sum())
        offbeat_energy = float(sum(profile[i] for i in range(N_STEPS) if i not in BEAT_BINS))
        syncopation = offbeat_energy / (beat_energy + EPS)

        onsets_per_bar = float(hist.sum() / n_bars) if n_bars else 0.0
        density = onsets_per_bar / N_STEPS

        per_beat_s = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 60.0 / tempo_corrected
        per_bar_s = per_beat_s * 4
        periodicity = {
            "at_1_beat": _autocorr_at(flux[name], sr, hop, per_beat_s),
            "at_2_beats": _autocorr_at(flux[name], sr, hop, per_beat_s * 2),
            "at_1_bar": _autocorr_at(flux[name], sr, hop, per_bar_s),
        }

        # per-bar mean energy for bar_matrix / entry-exit profile
        if n_bars:
            for b in range(n_bars):
                t0 = bar_edges[b] if b < len(bar_edges) else b * per_bar_s
                t1 = bar_edges[b + 1] if b + 1 < len(bar_edges) else t0 + per_bar_s
                m = (frame_times >= t0) & (frame_times < t1)
                bar_matrix[bi, b] = float(energy[name][m].mean()) if m.any() else 0.0
        else:
            bar_matrix[bi, 0] = float(energy[name].mean())

        if name in kick_bins:
            kick_hist_total += hist

        per_band[name] = {
            "bar_profile_16step": profile.tolist(),
            "top_bins": top_bins,
            "syncopation_score": syncopation,
            "onsets_per_bar": onsets_per_bar,
            "density_0_1": density,
            "periodicity_strength": periodicity,
        }

    # --- kick detection (sub+low onsets quantised to the beat grid) --------
    kick_fraction_per_bar = np.zeros(max(n_bars, 1))
    if n_bars:
        beat_hits = kick_hist_total[:, list(BEAT_BINS)] > 0
        kick_fraction_per_bar = beat_hits.mean(axis=1)
    kick_beat_fraction = float(kick_fraction_per_bar.mean()) if n_bars else 0.0
    kicks_per_bar = float(kick_hist_total.sum() / n_bars) if n_bars else 0.0

    # --- section structure: bar-to-bar novelty on [bands + kick] features --
    if n_bars >= 3:
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=6)
        mfcc_times = librosa.frames_to_time(np.arange(mfcc.shape[1]), sr=sr, hop_length=512)
        bar_mfcc = np.zeros((6, n_bars))
        for b in range(n_bars):
            t0 = bar_edges[b] if b < len(bar_edges) else b * per_bar_s
            t1 = bar_edges[b + 1] if b + 1 < len(bar_edges) else t0 + per_bar_s
            m = (mfcc_times >= t0) & (mfcc_times < t1)
            bar_mfcc[:, b] = mfcc[:, m].mean(axis=1) if m.any() else 0.0

        band_frac = bar_matrix / (bar_matrix.max(axis=1, keepdims=True) + EPS)
        feats = np.vstack([band_frac, bar_mfcc, kick_fraction_per_bar[None, :]]).T
        feats = (feats - feats.mean(axis=0)) / (feats.std(axis=0) + EPS)
        novelty = np.linalg.norm(np.diff(feats, axis=0), axis=1)

        peaks, _ = ss.find_peaks(novelty, distance=4, prominence=novelty.std() * 0.5 + EPS)
        boundary_bars = [0] + [int(p) + 1 for p in peaks] + [n_bars]
        boundary_bars = sorted(set(boundary_bars))
    else:
        boundary_bars = [0, n_bars]

    segments = []
    for s, e in zip(boundary_bars[:-1], boundary_bars[1:]):
        frac = float(kick_fraction_per_bar[s:e].mean()) if e > s else 0.0
        label = "kick-on" if frac >= 0.5 else "kick-off"
        t0 = float(bar_edges[s]) if s < len(bar_edges) else s * per_bar_s
        t1 = float(bar_edges[e]) if e < len(bar_edges) else duration_s
        segments.append({"start_bar": s, "end_bar": e, "start_s": t0, "end_s": t1,
                          "label": label, "kick_fraction": frac})

    breakdown = None
    best_len = -1
    for i, seg in enumerate(segments):
        if seg["label"] == "kick-off":
            length = seg["end_bar"] - seg["start_bar"]
            if length > best_len:
                best_len, breakdown = length, (i, seg)
    candidate_breakdown = None
    candidate_drop_bar = None
    if breakdown is not None:
        i, seg = breakdown
        candidate_breakdown = {"start_bar": seg["start_bar"], "end_bar": seg["end_bar"],
                                "start_s": seg["start_s"], "end_s": seg["end_s"]}
        for nxt in segments[i + 1:]:
            if nxt["label"] == "kick-on":
                candidate_drop_bar = nxt["start_bar"]
                break

    # --- entry / exit profile per band --------------------------------------
    entry_exit = {}
    for bi, name in enumerate(bands):
        row = bar_matrix[bi]
        thresh = row.max() * 0.15 if row.max() > 0 else 0.0
        active = row > thresh
        presence = []
        for si, seg in enumerate(segments):
            m = active[seg["start_bar"]:seg["end_bar"]]
            presence.append({"segment_index": si, "label": seg["label"],
                              "present": bool(m.mean() >= 0.5) if len(m) else False,
                              "active_fraction": float(m.mean()) if len(m) else 0.0})
        entry_exit[name] = presence

    if npy_path:
        np.save(npy_path, bar_matrix)

    return {
        "file": path,
        "duration_s": duration_s,
        "tempo_bpm_raw": tempo_raw,
        "tempo_bpm": tempo_corrected,
        "tempo_correction": correction,
        "n_bars": n_bars,
        "bands": per_band,
        "kick": {
            "kicks_per_bar": kicks_per_bar,
            "kick_beat_fraction": kick_beat_fraction,
            "kick_fraction_per_bar": kick_fraction_per_bar.tolist(),
        },
        "segments": segments,
        "candidate_breakdown": candidate_breakdown,
        "candidate_drop_bar": candidate_drop_bar,
        "entry_exit": entry_exit,
        "bar_matrix": bar_matrix.tolist(),
        "bar_matrix_bands_order": bands,
        "bar_matrix_npy": npy_path,
    }
