"""Queue item 4: feed five measures a case whose answer is known, record what
each returns. One JSON per measure under results/calibrate_measures_v1/.
Cases are built from analysis/fixtures.py so they match the unit tests.
Run from a foreground shell after the rig is idle (CPU). `--only NAME` runs one.
"""
import argparse, json, math, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import fixtures, grid, loudness, signal_features
OUT = Path("results/calibrate_measures_v1"); OUT.mkdir(parents=True, exist_ok=True)
SR = 44100
rng = np.random.default_rng(0)

def crest_db(y):  # the plain definition, computed on the samples we hand in
    y = np.asarray(y, dtype=np.float64); return 20*math.log10(np.abs(y).max()/ (np.sqrt((y**2).mean())+1e-20))

def case_grid_lock():
    bpm, rows = 150.0, []
    for jitter_ms in (0, 5, 10, 20):
        y, sr, _, _ = fixtures.click_track(bpm=bpm, sr=22050, n_bars=16)
        if jitter_ms:  # move each beat by a random offset within +/- jitter
            beat = int(sr*60/bpm); out = np.zeros_like(y)
            for b in range(0, len(y)-beat, beat):
                s = int(rng.uniform(-jitter_ms, jitter_ms)*sr/1000); seg = y[b:b+beat]
                lo, hi = max(0, b+s), min(len(out), b+s+len(seg)); out[lo:hi] += seg[:hi-lo]
            y = out
        out = grid.analyse(None, y=np.asarray(y, dtype=np.float64))
        rows.append(dict(jitter_ms=jitter_ms, true_bpm=bpm, tempo=out["tempo"], tempo_error=round(out["tempo"]-bpm,2), phase=out["phase"], lock=out["lock"]))
    base = rows[0]["lock"]
    for r in rows: r["lock_vs_clean"] = round(r["lock"]-base, 3)
    return dict(measure="grid lock", entry="analysis.grid.analyse (tempo, phase, lock)", rows=rows,
                reading="tempo should stay at 150 and lock should stay near the clean value as jitter grows; where lock drops is the tolerance. phase is reported for drift, its clean value is the reference.")

def case_kick_body():
    rows = []
    for decay in (10.0, 25.0, 50.0, 100.0):  # fixtures.sine_burst decay constant (1/s)
        y = fixtures.sine_burst(freq=50.0, sr=SR, dur=1.0, decay=decay)
        true_40db_ms = 1000.0 * math.log(100.0) / decay  # amplitude e^{-decay t} hits -40 dB at ln(100)/decay
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"k.wav"; sf.write(str(p), y, SR)
            subprocess.run([sys.executable, "-m", "analysis.run", "hits", td, "-o", str(Path(td)/"h.csv")], capture_output=True)
            subprocess.run([sys.executable, "analysis/hits_extra.py", str(Path(td)/"h.csv")], capture_output=True)
            import csv; r = next(csv.DictReader(open(Path(td)/"h.csv")))
        got = float(r.get("decay40_ms") or "nan")
        rows.append(dict(decay_constant=decay, true_decay40_ms=round(true_40db_ms,1), reported_decay40_ms=got, error_ms=round(got-true_40db_ms,1)))
    return dict(measure="kick body (decay40_ms)", entry="analysis.run hits + hits_extra", rows=rows,
                reading="reported should track the analytic 40 dB time; a constant offset is the follower's window, a slope is a bias.")

def case_sustain_share():
    rows = []
    for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
        n = int(SR*0.6); t = np.arange(n)/SR; body = np.sin(2*np.pi*60*t)
        env = np.ones(n); k = int(n*frac); env[k:] = np.exp(-40.0*(t[k:]-t[k]))  # plateau for frac, then fast decay
        y = body*env*0.5
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"s.wav"; sf.write(str(p), y, SR)
            subprocess.run([sys.executable, "-m", "analysis.run", "hits", td, "-o", str(Path(td)/"h.csv")], capture_output=True)
            subprocess.run([sys.executable, "analysis/hits_extra.py", str(Path(td)/"h.csv")], capture_output=True)
            import csv; r = next(csv.DictReader(open(Path(td)/"h.csv")))
        got = float(r.get("sustain_share") or "nan")
        rows.append(dict(built_plateau_fraction=frac, reported_sustain_share=got, error=round(got-frac,3)))
    return dict(measure="sustain share", entry="hits_extra.sustain_share", rows=rows,
                reading="if the measure means 'fraction of the hit held near full level', reported tracks built; if it means something else, this table says what.")

def case_band_shares_noise():
    rows = []; n = SR*4; t = np.arange(n)/SR
    for sub_ratio in (0.8,):
        for snr_db in (40, 30, 20, 10, 0):
            a_sub = math.sqrt(sub_ratio); a_mid = math.sqrt(1-sub_ratio)
            sig = a_sub*np.sin(2*np.pi*50*t) + a_mid*np.sin(2*np.pi*300*t)
            noise = rng.standard_normal(n); noise *= np.sqrt((sig**2).mean()) / np.sqrt((noise**2).mean()) * 10**(-snr_db/20)
            y = sig + noise
            import librosa
            S = np.abs(librosa.stft(y.astype(np.float32), n_fft=8192, hop_length=2048)); f = librosa.fft_frequencies(sr=SR, n_fft=8192)
            got = signal_features._band_shares(S, f)
            rows.append(dict(built_sub_share=sub_ratio, snr_db=snr_db, reported=got if isinstance(got, dict) else list(map(float, got))))
    return dict(measure="band shares under noise", entry="signal_features._band_shares", rows=rows,
                reading="with no noise the sub share should read the built ratio (mid band takes the rest); drift as SNR falls is the noise floor spreading energy across bands.")

def case_crest_limiting():
    rows = []
    y, sr_c, _, _ = fixtures.click_track(bpm=130.0, sr=22050, n_bars=8); y = np.asarray(y, dtype=np.float64); y /= np.abs(y).max()
    for ceil_db in (0, -3, -6, -9, -12):
        c = 10**(ceil_db/20); yc = np.clip(y, -c, c)
        m = loudness.measure(yc, sr_c); rep = (m.get("crest_db", m.get("crest")) if isinstance(m, dict) else (m[0] if isinstance(m,(tuple,list)) else m))
        if isinstance(rep, (int, float)): rep = float(rep)
        rows.append(dict(ceiling_db=ceil_db, true_crest_db=round(crest_db(yc),2), reported_crest_db=rep, error_db=None if rep is None else round(float(rep)-crest_db(yc),2)))
    return dict(measure="crest under limiting", entry="analysis.loudness.measure", rows=rows,
                reading="true crest is peak over RMS on the clipped samples; reported should match at every ceiling. A gap that grows as the ceiling drops is the measure's own window smoothing peaks.")

CASES = {"grid_lock": case_grid_lock, "kick_body": case_kick_body, "sustain_share": case_sustain_share,
         "band_shares_noise": case_band_shares_noise, "crest_limiting": case_crest_limiting}
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--only"); a = ap.parse_args()
    for name, fn in CASES.items():
        if a.only and name != a.only: continue
        try: res = fn(); res["ok"] = True
        except Exception as e: res = dict(measure=name, ok=False, error=f"{type(e).__name__}: {e}")
        (OUT/f"{name}.json").write_text(json.dumps(res, indent=1, default=str)); print(name, "ok" if res.get("ok") else res.get("error"), flush=True)
