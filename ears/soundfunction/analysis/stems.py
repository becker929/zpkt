"""Stem-aware analysis: Demucs separation, hits harvested from the drum stem,
the pump read from the bass stem, and the same for real multitrack stems.

    from analysis import stems
    parts = stems.separate("mix.wav", out_dir)          # {"drums": path, "bass": path, ...}
    hits  = stems.harvest_hits(parts["drums"])          # list of dicts: t, role, probs, features
    pump  = stems.bass_pump(parts["bass"], grid_result) # pump measured on the bass alone

Fast features: only the seven portable measures the role model uses, computed
exactly as analysis/signal_features.py does, without the pitch tracker and the
harmonic/percussive split, so a minute of drums (a few hundred hits) takes
seconds rather than minutes.
"""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np
import librosa
from analysis.signal_features import _stft_mag, _band_shares, _db, EPS
from analysis.hits_extra import env_timings
from analysis import grid, pump as pump_mod

ROOT = Path(__file__).resolve().parent.parent
MODEL = json.load(open(ROOT / "out" / "classifier_union.json"))["model"]
STEMS = ["drums", "bass", "other", "vocals"]
SR = 44100
ROLE_OF = {"hat_closed": "hat", "hat_open": "hat", "perc": "hook", "stab": "hook", "pad": "space", "riser": "space", "impact": "space"}


def separate(path, out_dir=None, model="htdemucs"):
    """Run Demucs on one file; return {stem: wav path}. Skips when the stems exist.
    With out_dir None the stems are cached under $LAB_CACHE (default lab/cache) by content hash."""
    if out_dir is None:
        import hashlib
        h = hashlib.sha1(open(path, "rb").read()).hexdigest()[:16]
        out_dir = Path(os.environ.get("LAB_CACHE", str(ROOT / "lab" / "cache"))) / h
    out_dir = Path(out_dir); stem_dir = out_dir / model / Path(path).stem
    if not all((stem_dir / f"{s}.wav").exists() for s in STEMS):
        subprocess.run([sys.executable, "-m", "demucs", "-n", model, "-d", "cpu", "--shifts", "0", "-o", str(out_dir), str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {s: str(stem_dir / f"{s}.wav") for s in STEMS}


def fast_features(y, sr=SR):
    y = np.asarray(y, dtype=np.float64)
    if not np.any(y): return None
    peak = float(np.abs(y).max()); rms = float(np.sqrt(np.mean(y ** 2)))
    S, freqs, hop, _ = _stft_mag(y, sr)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr, freq=freqs)[0]
    seg = y[: min(len(y), int(0.1 * sr))]
    S100, f100, _, _ = _stft_mag(seg, sr)
    c100 = float(np.mean(librosa.feature.spectral_centroid(S=S100, sr=sr, freq=f100)[0]))
    t_ms = librosa.times_like(centroid, sr=sr, hop_length=hop) * 1000.0
    slope = float(np.polyfit(t_ms, centroid, 1)[0]) if len(t_ms) >= 2 else 0.0
    f = dict(crest_factor_db=_db(peak) - _db(rms), spectral_centroid_hz=float(np.mean(centroid)), spectral_centroid_hz_100ms=c100,
             centroid_slope_hz_per_ms=slope)
    f.update(_band_shares(S, freqs)); f.update(env_timings(y, sr))
    return f


def predict(f):
    x = np.array([f[k] for k in MODEL["features"]], dtype=float)
    z = (x - np.array(MODEL["mean"])) / np.array(MODEL["scale"])
    logits = np.array(MODEL["bias"]) + np.array(MODEL["weights"]) @ z
    p = np.exp(logits - logits.max()); p /= p.sum()
    return MODEL["classes"][int(p.argmax())], {c: round(float(v), 3) for c, v in zip(MODEL["classes"], p)}


def harvest_hits(path, max_hits=600, win_s=0.40, min_gap_s=0.05):
    """Cut a drum stem (or any percussive file) into hits at its onsets and name each one."""
    y, _ = librosa.load(path, sr=SR, mono=True)
    if not np.any(y): return []
    onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=512)
    frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR, hop_length=512, backtrack=True, units="frames",
                                        pre_max=3, post_max=3, pre_avg=6, post_avg=6, delta=0.2, wait=int(min_gap_s * SR / 512))
    times = librosa.frames_to_time(frames, sr=SR, hop_length=512)
    strengths = onset_env[np.clip(frames, 0, len(onset_env) - 1)]
    hits = []
    for i, t in enumerate(times[:max_hits]):
        s = int(t * SR); e = int(min(len(y), s + win_s * SR, (times[i + 1] * SR) if i + 1 < len(times) else len(y)))
        seg = y[s:e]
        if len(seg) < int(0.02 * SR): continue
        seg = seg / (np.abs(seg).max() + 1e-9)
        f = fast_features(seg)
        if f is None: continue
        role, probs = predict(f)
        hits.append(dict(t=round(float(t), 3), strength=round(float(strengths[i]), 2), role=role, probs=probs, features=f))
    return hits


def kick_pitch(path, hits, n=16):
    """Where the kick lands: median f0 at ~100 ms into the loudest kicks, from the pitch tracker."""
    ks = sorted([h for h in hits if h["role"] == "kick"], key=lambda h: -h["strength"])[:n]
    if not ks: return None
    y, _ = librosa.load(path, sr=SR, mono=True)
    vals = []
    for h in ks:
        s = int(h["t"] * SR); seg = y[s: s + int(0.25 * SR)]
        try:
            f0, _, _ = librosa.pyin(seg, fmin=35.0, fmax=200.0, sr=SR, frame_length=4096, hop_length=512)
        except Exception:
            continue
        tt = librosa.times_like(f0, sr=SR, hop_length=512)
        near = f0[(tt > 0.06) & (tt < 0.14)]; near = near[~np.isnan(near)]
        if len(near): vals.append(float(np.median(near)))
    return round(float(np.median(vals)), 1) if vals else None


def role_summary(hits, duration_s):
    """Counts, rates and medians per job from a list of hits."""
    out = {}
    for job in ["kick", "hat", "clap", "hook", "rumble", "space"]:
        hs = [h for h in hits if h["role"] == job]
        if not hs: continue
        med = lambda k: round(float(np.median([h["features"][k] for h in hs])), 3)
        out[job] = dict(count=len(hs), per_minute=round(60 * len(hs) / max(duration_s, 1e-9), 1),
                        decay40_ms=med("decay40_ms"), sustain_share=med("sustain_share"), band_sub_share=med("band_sub_share"),
                        band_low_share=med("band_low_share"), band_air_share=med("band_air_share"), spectral_centroid_hz=med("spectral_centroid_hz"),
                        crest_factor_db=med("crest_factor_db"), mean_confidence=round(float(np.mean([h["probs"][job] for h in hs])), 3))
    return out


def grid_of(path):
    """The mix's grid: tempo, phase, bar profiles, kick on/off, downbeat. Same code as the corpus."""
    from analysis import downbeat
    y, _ = librosa.load(path, sr=grid.SR, mono=True)
    env, atk = grid.envelopes(y)
    g = grid.analyse(path, y=y, env=env, atk=atk)
    g["downbeat"] = downbeat.find(env, g["tempo"], g["phase"])
    g["pump_mix"] = pump_mod.analyse_env(env, g)
    g["duration_s"] = round(len(y) / grid.SR, 1)
    return g


def bass_pump(bass_path, g):
    """The pump read on the bass stem alone, folded on the mix's beat grid."""
    y, _ = librosa.load(bass_path, sr=grid.SR, mono=True)
    if not np.any(y): return dict(pump_depth_db=None, pump_return_ms=None)
    env, _ = grid.envelopes(y)
    r = pump_mod.analyse_env(env, g)
    # how much of the bass energy lives below 60 Hz vs 60-150: rumble weight
    tot = env.sum(axis=1) + 1e-12
    r["bass_sub_share"] = round(float(tot[0] / (tot[0] + tot[1])), 3)
    return r


def stem_levels(parts):
    """Relative loudness of each stem, in dB below the loudest."""
    lv = {}
    for s, p in parts.items():
        y, _ = librosa.load(p, sr=22050, mono=True)
        lv[s] = float(_db(np.sqrt(np.mean(y ** 2)) if np.any(y) else EPS))
    top = max(lv.values())
    return {s: round(v - top, 1) for s, v in lv.items()}


def onsets_of(path, sr=grid.SR):
    y, _ = librosa.load(path, sr=sr, mono=True)
    o = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    fr = librosa.onset.onset_detect(onset_envelope=o, sr=sr, hop_length=512, units="frames", delta=0.2, wait=2)
    return librosa.frames_to_time(fr, sr=sr, hop_length=512), len(y) / sr


def kick_onsets(path, rel=0.15):
    """Kick times from a drum or kick stem: rises in the sub band's envelope, the same signal
    the corpus grid locks on, so hats and claps in the same stem do not count. `rel` is the
    threshold as a share of the 95th percentile attack; 0.15 keeps the quieter kicks of a
    mid-forward, distorted kick sound."""
    y, _ = librosa.load(path, sr=grid.SR, mono=True)
    if not np.any(y): return np.array([]), len(y) / grid.SR
    env, atk = grid.envelopes(y); a = atk[0]
    th = rel * np.quantile(a[a > 0], 0.95) if (a > 0).any() else np.inf
    peaks = [i for i in range(1, len(a) - 1) if a[i] >= th and a[i] >= a[i - 1] and a[i] >= a[i + 1]]
    # merge peaks closer than 80 ms
    ons, last = [], -1e9
    for i in peaks:
        if i - last > 0.08 * grid.FR: ons.append(i / grid.FR); last = i
    return np.array(ons), len(y) / grid.SR


def sidechain_between(kick_path, bass_path, g=None):
    """True ducking: the bass stem's low band folded on the kick stem's own kick onsets.
    Returns depth (dB) and return time (ms) like the pump, but with no guessing about the grid."""
    ons, dur = kick_onsets(kick_path)
    if len(ons) < 4: return dict(pump_depth_db=None, pump_return_ms=None, n_kicks=int(len(ons)))
    # keep the onsets that sit on the beat: lock a tempo on the kick stem's own sub attacks
    # (rumble tails and off-beat ghosts also rise in the sub band) and drop the rest
    yk, _ = librosa.load(kick_path, sr=grid.SR, mono=True)
    envk, atkk = grid.envelopes(yk)
    _, bpm, ph = grid.lock(atkk[0], grid.coarse_tempo(yk))
    beat = 60.0 / bpm
    on_beat = [t for t in ons if abs(((t * grid.FR - ph) / (beat * grid.FR)) % 1.0 - 0.5) > 0.5 - 0.04 / beat]
    if len(on_beat) >= 4: ons = np.array(on_beat)
    y, _ = librosa.load(bass_path, sr=grid.SR, mono=True)
    env, _ = grid.envelopes(y); low = env[1]
    L = int(beat * grid.FR)
    rows = []
    for t in ons:
        s = int(t * grid.FR)
        if s + L <= len(low) and low[s:s + L].max() > 0: rows.append(low[s:s + L])
    if len(rows) < 4: return dict(pump_depth_db=None, pump_return_ms=None, n_kicks=int(len(ons)))
    m = np.median(np.stack(rows), axis=0); curve = 10 * np.log10(m / (m.max() + 1e-12) + 1e-9)
    r = pump_mod.measure(curve, bpm); r["n_kicks"] = int(len(ons)); r["kick_interval_ms"] = round(float(beat) * 1000, 1); r["tempo"] = round(float(bpm), 2)
    return r


def kicks_by_position(drum_path, g=None, n_pitch=16, rel=0.25, bass_path=None):
    """Kicks found by where they sit, not by what the role model calls them. In this music the
    kick is on the beat by definition, so: take the beat grid (the mix's, when given), and call
    a beat a kick when the drum stem has a strong full-band onset there. A kick that is
    mid-forward with a sustained rumble under it shows no rise in the sub band at all, which is
    why the earlier sub-attack finder missed most of a distorted kick's hits. Returns count,
    rate, feature medians over the whole beat, how loud the kick still is when the next lands,
    the model's opinion of these kicks, and the landing pitch."""
    y, _ = librosa.load(drum_path, sr=SR, mono=True); dur = len(y) / SR
    if not np.any(y) or dur < 5: return dict(n=0, per_minute=0.0)
    if g is None:
        y22 = librosa.resample(y, orig_sr=SR, target_sr=grid.SR); env, atk = grid.envelopes(y22)
        _, bpm, ph = grid.lock(atk[0], grid.coarse_tempo(y22))
    else:
        bpm, ph = g["tempo"], g["phase"]
    beat = 60.0 / bpm; beat_times = np.arange(ph / grid.FR, dur - beat, beat)
    hop = 512; ons = librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop)
    fr = lambda t: int(round(t * SR / hop))
    strength = np.array([ons[max(0, fr(t) - 2): fr(t) + 3].max() if fr(t) + 3 <= len(ons) else 0.0 for t in beat_times])
    th = rel * np.quantile(strength[strength > 0], 0.90) if (strength > 0).any() else np.inf
    on_beat = [float(t) for t, st in zip(beat_times, strength) if st >= th]
    if len(on_beat) < 4: return dict(n=int(len(on_beat)), per_minute=round(60 * len(on_beat) / dur, 1))
    feats, strengths, ringing = [], [], []
    win = int(beat * 0.95 * SR)           # the whole beat: a kick that fills it is a finding, not a truncation
    for t in on_beat:
        s0 = int(t * SR); seg = y[s0: s0 + win]
        if len(seg) < int(0.05 * SR) or not np.any(seg): continue
        strengths.append(float(np.abs(seg).max())); seg = seg / (np.abs(seg).max() + 1e-9)
        f = fast_features(seg)
        if f:
            feats.append(f)
            tail = seg[-int(0.05 * SR):]; ringing.append(float(20 * np.log10(np.sqrt(np.mean(tail ** 2)) + 1e-9)))
    if not feats: return dict(n=int(len(on_beat)), per_minute=round(60 * len(on_beat) / dur, 1))
    med = lambda k: round(float(np.median([f[k] for f in feats])), 3)
    # the kick *body*: first 250 ms of drums plus bass together, which is what a one-shot kick
    # in this music actually is (kick and rumble as one), so it can be compared with sample packs
    body = None
    if bass_path is not None:
        yb, _ = librosa.load(bass_path, sr=SR, mono=True); n = min(len(y), len(yb)); ysum = y[:n] + yb[:n]
        bf = []
        for t in on_beat:
            s0 = int(t * SR); seg = ysum[s0: s0 + int(0.25 * SR)]
            if len(seg) < int(0.05 * SR) or not np.any(seg): continue
            f = fast_features(seg / (np.abs(seg).max() + 1e-9))
            if f: bf.append(f)
        if bf:
            body = {k: round(float(np.median([f[k] for f in bf])), 3) for k in ("decay20_ms", "band_sub_share", "band_low_share", "band_lowmid_share", "band_mid_share", "band_high_share", "band_air_share", "spectral_centroid_hz", "centroid_slope_hz_per_ms", "crest_factor_db")}
    out = dict(n=int(len(on_beat)), per_minute=round(60 * len(on_beat) / dur, 1), tempo=round(float(bpm), 2), beat_ms=round(beat * 1000, 1), body=body,
               decay20_ms=med("decay20_ms"), decay40_ms=med("decay40_ms"), decay40_hits_window=round(float(np.mean([f["decay40_ms"] >= win / SR * 1000 - 3 for f in feats])), 2),
               level_at_next_beat_db=round(float(np.median(ringing)), 1),
               sustain_share=med("sustain_share"), band_sub_share=med("band_sub_share"), band_low_share=med("band_low_share"),
               band_mid_share=med("band_mid_share"), band_air_share=med("band_air_share"), spectral_centroid_hz=med("spectral_centroid_hz"), crest_factor_db=med("crest_factor_db"))
    # what the role model would call these kicks
    names = [predict(f)[0] for f in feats]
    out["model_calls_them"] = {c: names.count(c) for c in sorted(set(names))}
    # landing pitch on the loudest of them
    idx = np.argsort(strengths)[::-1][:n_pitch]; vals = []
    for i in idx:
        s0 = int(on_beat[i] * SR); seg = y[s0: s0 + int(0.25 * SR)]
        try:
            f0, _, _ = librosa.pyin(seg, fmin=35.0, fmax=200.0, sr=SR, frame_length=4096, hop_length=512)
        except Exception:
            continue
        tt = librosa.times_like(f0, sr=SR, hop_length=512); near = f0[(tt > 0.06) & (tt < 0.14)]; near = near[~np.isnan(near)]
        if len(near): vals.append(float(np.median(near)))
    out["landing_pitch_hz"] = round(float(np.median(vals)), 1) if vals else None
    out["pitch_readable_share"] = round(len(vals) / max(len(idx), 1), 2)
    return out
