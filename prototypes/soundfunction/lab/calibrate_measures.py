"""Queue item 4, requirement 2: "Every measure on the sheet checked against a
case where the answer is known, and corrected where it bends."

Five measures, each fed cases built from clean synthetic samples, each JSON
recording the measure's exact definition (function, window, band edges), the
true value computed on the same samples with the stated formula, the
returned value, the error, and pass/fail against the tolerance the research
agent set (mailbox 5646120288). Light cases run anywhere; the two that go
through the one-shot pipeline (kick body, sustain share) are heavier.
    python3 lab/calibrate_measures.py [--only NAME] [--light]
"""
import argparse, csv, json, math, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf, librosa
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import fixtures, grid, loudness, signal_features
OUT = Path("results/calibrate_measures_v1"); OUT.mkdir(parents=True, exist_ok=True)
SR = 44100; rng = np.random.default_rng(0)
EARS_PY = "/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python"; EARS = "/Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py"

def crest_full(y):
    y = np.asarray(y, np.float64); return 20*math.log10(np.abs(y).max() / (math.sqrt((y**2).mean()) + 1e-20))
def hits_pipeline(files):
    """Run analysis.run hits + hits_extra on a folder of one-shots; return rows by filename."""
    with tempfile.TemporaryDirectory() as td:
        for name, y, sr in files: sf.write(str(Path(td)/name), y, sr)
        subprocess.run([sys.executable, "-m", "analysis.run", "hits", td, "-o", str(Path(td)/"h.csv")], capture_output=True)
        subprocess.run([sys.executable, "analysis/hits_extra.py", str(Path(td)/"h.csv")], capture_output=True)
        return {Path(r["file"]).name: r for r in csv.DictReader(open(Path(td)/"h.csv"))}
def ears(y, sr):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f: sf.write(f.name, y, sr); p = f.name
    r = subprocess.run([EARS_PY, EARS, "analyze", p], capture_output=True, text=True); Path(p).unlink()
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-200:]}

# ---------------------------------------------------------------- grid lock
def case_grid_lock():
    rows = []
    def jitter(y, sr, bpm, ms):
        if not ms: return y
        beat = int(sr*60/bpm); out = np.zeros_like(y)
        for b in range(0, len(y)-beat, beat):
            s = int(rng.uniform(-ms, ms)*sr/1000); seg = y[b:b+beat]; lo, hi = max(0, b+s), min(len(out), b+s+len(seg)); out[lo:hi] += seg[:hi-lo]
        return out
    def burst_track(bpm, sr, n_bars=16):  # clicks replaced by a 50 Hz burst with a 300 ms decay: hard techno has no clicks
        beat = int(sr*60/bpm); n = beat*4*n_bars; y = np.zeros(n); t = np.arange(int(sr*0.6))/sr
        b = np.sin(2*np.pi*50*t)*np.exp(-t/0.3*math.log(100)/ (math.log(100)/ (1/ (1/0.3)) ) ) if False else np.sin(2*np.pi*50*t)*np.exp(-t*(math.log(100)/0.3))  # -40 dB at 300 ms
        for k in range(0, n-len(b), beat): y[k:k+len(b)] += b
        return y/np.abs(y).max()
    for kind, bpm in (("click", 150.0), ("burst50", 140.0), ("burst50", 160.0)):
        base_phase = None
        for j in (0, 5, 10, 20):
            if kind == "click": y, sr, _, _ = fixtures.click_track(bpm=bpm, sr=22050, n_bars=16)
            else: sr = 22050; y = burst_track(bpm, sr)
            y = jitter(np.asarray(y, np.float64), sr, bpm, j); out = grid.analyse(None, y=y)
            if base_phase is None: base_phase = out["phase"]
            bpm_err_pct = 100*abs(out["tempo"]-bpm)/bpm; ph_err_ms = abs(out["phase"]-base_phase)
            ok = None if j > 10 else (bpm_err_pct <= 0.5 and ph_err_ms <= 10)
            rows.append(dict(case=kind, true_bpm=bpm, jitter_ms=j, tempo=out["tempo"], bpm_error_pct=round(bpm_err_pct,3), phase=out["phase"], phase_shift_from_clean=round(ph_err_ms,2), lock=out["lock"], pass_=ok))
    return dict(measure="grid lock", definition=dict(function="analysis.grid.analyse", method="Hilbert envelopes per band at 250 Hz, attack track = log-envelope rises > 2 dB/frame, coarse tempo then lock(lowatk, bpm0)", outputs=["tempo","phase","lock"]),
                tolerance="BPM within 0.5% and phase within 10 ms at jitter <= 10 ms; jitter 20 recorded, not judged", rows=rows)

# ---------------------------------------------------------------- kick body
def case_kick_body():
    files, truth = [], {}
    for f0 in (40.0, 50.0, 60.0):
        for decay in (10.0, 25.0, 50.0, 100.0):
            y, _sr = fixtures.sine_burst(freq=f0, sr=SR, dur=1.0, decay=decay); name = f"k_{int(f0)}_{int(decay)}.wav"
            files.append((name, y, SR)); truth[name] = dict(f0=f0, decay_constant=decay, true_decay20_ms=1000*math.log(10)/decay, true_decay40_ms=1000*math.log(100)/decay)
    got = hits_pipeline(files); rows = []
    from scipy.signal import hilbert
    def ref_decay(y, sr, db):
        """Independent reference: analytic-signal envelope, no library code.
        Separates irreducible envelope-estimation error from the library's own bias."""
        env = np.abs(hilbert(np.asarray(y, np.float64))); k = int(env.argmax())
        idx = np.flatnonzero(env[k:] < env.max()*10**(db/20))
        return 1000.0*idx[0]/sr if idx.size else float("nan")
    ymap = {n: (y, sr) for n, y, sr in files}
    for name, tr in truth.items():
        r = got.get(name, {}); d20 = float(r.get("decay20_ms") or "nan"); d40 = float(r.get("decay40_ms") or "nan")
        y, sr = ymap[name]; ref40 = ref_decay(y, sr, -40); ref20 = ref_decay(y, sr, -20)
        e40 = 100*(d40 - tr["true_decay40_ms"])/tr["true_decay40_ms"]
        e_env = 100*(ref40 - tr["true_decay40_ms"])/tr["true_decay40_ms"]
        e_lib = 100*(d40 - ref40)/ref40
        rows.append(dict(**tr, envelope_ref_decay40_ms=round(ref40,1), envelope_ref_decay20_ms=round(ref20,1),
                         reported_decay20_ms=d20, reported_decay40_ms=d40,
                         error_vs_analytic_pct=round(e40,1), envelope_estimation_error_pct=round(e_env,1), library_error_vs_envelope_pct=round(e_lib,1),
                         pass_=bool(abs(e40) <= 10)))
    return dict(measure="kick body (decay20_ms, decay40_ms)", definition=dict(function="analysis.run hits -> analysis/hits_extra.py", method="time for the hit envelope to fall 20/40 dB below its peak; envelope from the analytic signal (see signal_features._env_db), 2 ms frames"),
                tolerance="decay40 within 10% of the analytic value ln(100)/decay; bias per frequency recorded if it fails", rows=rows,
                reading="three columns on purpose: the analytic truth exp(-decay t); an independent analytic-signal envelope on the same samples, which shows what ANY envelope method costs at these frequencies; and the library. The gap between the last two is the library's own bias.")

# ---------------------------------------------------------------- sustain share
def case_sustain_share():
    files, truth = [], {}
    for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
        n = int(SR*0.6); t = np.arange(n)/SR; env = np.ones(n); k = int(n*frac); env[k:] = np.exp(-40.0*(t[k:]-t[k]))
        y = 0.5*np.sin(2*np.pi*60*t)*env; name = f"s_{int(frac*100)}.wav"; files.append((name, y, SR))
        k50 = int(0.050*SR); truth[name] = dict(built_plateau_fraction=frac, true_sustain_share=float((y[k50:]**2).sum()/(y**2).sum()))
    got = hits_pipeline(files); rows = []
    for name, t in truth.items():
        rep = float(got.get(name, {}).get("sustain_share") or "nan"); err = rep - t["true_sustain_share"]
        rows.append(dict(**t, reported_sustain_share=rep, error=round(err,4), pass_=bool(abs(err) <= 0.02)))
    return dict(measure="sustain share", definition=dict(function="analysis/hits_extra.py sustain_share", method="energy after the first 50 ms of the hit over total energy; truth computed with the same formula on the clean constructed samples"),
                tolerance="within 0.02 of the true ratio", rows=rows)

# ---------------------------------------------------------------- band shares
def case_band_shares_noise():
    rows = []; n = SR*4; t = np.arange(n)/SR
    tones = [(50.0, 0.8), (300.0, 0.2)]  # built energy shares
    edge_tones = [(60.0, 0.5), (150.0, 0.5)]
    def shares(y):
        S = np.abs(librosa.stft(y.astype(np.float32), n_fft=8192, hop_length=2048)); f = librosa.fft_frequencies(sr=SR, n_fft=8192)
        lib = signal_features._band_shares(S, f); e = ears(y, SR)
        return dict(library_six_band=lib, library_sub_plus_low_20_150=round(lib["band_sub_share"]+lib["band_low_share"],4), ears_shim=({k:e[k] for k in ("sub_share","low_share","mid_share","high_share","air_share")} if "sub_share" in e else e))
    for label, tl in (("50+300", tones), ("edges 60+150", edge_tones)):
        sig = sum(math.sqrt(a)*np.sin(2*np.pi*f*t) for f, a in tl)
        for snr_db in (None, 40, 30, 20, 10, 0):
            y = sig.copy()
            if snr_db is not None:
                nz = rng.standard_normal(n); nz *= math.sqrt((sig**2).mean())/math.sqrt((nz**2).mean())*10**(-snr_db/20); y = y + nz
            got = shares(y); built_sub_20_60 = sum(a for f, a in tl if 20 <= f < 60); built_20_150 = sum(a for f, a in tl if 20 <= f < 150)
            err = got["library_six_band"]["band_sub_share"] - built_sub_20_60
            on_edge = label.startswith("edges")   # a tone ON a band edge is split by the window; there is no single true band, so record, do not judge
            rows.append(dict(case=label, snr_db=snr_db, built_sub_20_60=built_sub_20_60, built_sub_20_150=built_20_150, reported=got, library_sub_error=round(err,4),
                             pass_=(None if (on_edge or (snr_db is not None and snr_db < 20)) else bool(abs(err) <= 0.02)),
                             note=("edge tone: energy splits across the boundary by spectral leakage; the row shows how each vocabulary splits it" if on_edge else None)))
    return dict(measure="band shares", definition=dict(library="analysis.signal_features._band_shares: power sum per band on an STFT magnitude, bands "+json.dumps(signal_features.BANDS), knob_map_notation="sub_share = 20-150 Hz (library sub+low)", ears_shim="edges not published; inferred from the edge-tone rows"),
                tolerance="library sub within 0.02 of the built ratio down to 20 dB SNR; 10 and 0 dB recorded", rows=rows)

# ---------------------------------------------------------------- crest
def case_crest():
    rows = []; y, sr, _, _ = fixtures.click_track(bpm=130.0, sr=22050, n_bars=8); y = np.asarray(y, np.float64); y /= np.abs(y).max()
    for ceil_db in (0, -3, -6, -9, -12):
        c = 10**(ceil_db/20); yc = np.clip(y, -c, c); rep = loudness.measure(yc, sr)["crest_db"]; tr = crest_full(yc)
        rows.append(dict(case="clipping", ceiling_db=ceil_db, true_crest_same_window_db=round(tr,2), reported_crest_db=rep, error_db=round(rep-tr,2), pass_=bool(abs(rep-tr) <= 0.5)))
    base = loudness.measure(y, sr)["crest_db"]
    for pad_s in (0, 0.5, 1.0, 2.0):
        yp = np.concatenate([y, np.zeros(int(pad_s*sr))]); rep = loudness.measure(yp, sr)["crest_db"]
        rows.append(dict(case="trailing silence", pad_s=pad_s, reported_crest_db=rep, drift_from_unpadded_db=round(rep-base,2), pass_=None))
    return dict(measure="crest", definition=dict(function="analysis.loudness.measure", method="20*log10(peak / RMS) over the WHOLE buffer handed in; no window, no gating. Silence in the buffer lowers RMS and raises crest."),
                tolerance="clipping: within 0.5 dB of peak/RMS computed on the clipped samples with the same whole-buffer window. Padding: drift recorded, becomes the window rule", rows=rows)

CASES = {"grid_lock": case_grid_lock, "kick_body": case_kick_body, "sustain_share": case_sustain_share, "band_shares": case_band_shares_noise, "crest": case_crest}
LIGHT = ("grid_lock", "band_shares", "crest")
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--only"); ap.add_argument("--light", action="store_true"); a = ap.parse_args()
    for name, fn in CASES.items():
        if a.only and name != a.only: continue
        if a.light and name not in LIGHT: continue
        try: res = fn(); res["ok"] = True
        except Exception as e: res = dict(measure=name, ok=False, error=f"{type(e).__name__}: {e}")
        (OUT/f"{name}.json").write_text(json.dumps(res, indent=1, default=str))
        n = len(res.get("rows", [])); p = sum(1 for r in res.get("rows", []) if r.get("pass_") is True); f = sum(1 for r in res.get("rows", []) if r.get("pass_") is False)
        print(f"{name:14s} {'ok' if res.get('ok') else res.get('error')}  rows={n} pass={p} fail={f}", flush=True)
