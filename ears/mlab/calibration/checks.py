"""Known-answer checks for every instrument.

Each check returns rows: (instrument, case, expected, measured, tolerance, ok, basis).
`basis` names where the expected value comes from:
  EBU-3341 / EBU-3342 / BS.1770  -> published standard test cases (re-synthesised here)
  analytic                       -> closed-form maths
  self-consistency               -> the instrument recovers a known processor's settings
  cross-check                    -> an independent implementation (pyloudnorm, ffmpeg ebur128)

Run: python3 -m mlab calibrate   or   python3 -m pytest calibration -q
"""
from __future__ import annotations

import datetime as dt
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
sys.path.insert(0, LAB)

from mlab import (als, bitdepth, compare, delivery, dsp, dynamics, loudness as L,  # noqa: E402
                  premaster, siggen, spectrum as S, io as aio)
from mlab.util import db, lin  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
HW = os.path.join(LAB, "audio", "hw002")


def row(inst, case, exp, meas, tol, basis):
    ok = abs(meas - exp) <= tol if isinstance(exp, (int, float)) else bool(meas == exp)
    return {"instrument": inst, "case": case, "expected": exp, "measured": meas,
            "tol": tol, "ok": bool(ok), "basis": basis}


def seq(parts, sr, f=1000.0):
    return np.vstack([siggen.sine(f, lv, d, sr) for lv, d in parts])


# ------------------------------------------------------------------ loudness
def check_kweighting():
    ref = [(1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585),
           (1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621)]
    rows = []
    for i, ((b, a), rf) in enumerate(zip(L.k_weighting(48000), ref)):
        got = (*b, a[1], a[2])
        err = max(abs(g - e) for g, e in zip(got, rf))
        rows.append(row("loudness", f"K-weighting stage {i + 1} coefficients @48k (max abs err)", 0.0, float(err), 1e-8, "BS.1770"))
    return rows


def check_ebu3341():
    rows = []
    cases = [("1: -23 dBFS 20 s", [(-23, 20)], -23.0), ("2: -33 dBFS 20 s", [(-33, 20)], -33.0),
             ("3: -36/-23/-36", [(-36, 10), (-23, 60), (-36, 10)], -23.0),
             ("4: -72/-36/-23/-36/-72", [(-72, 10), (-36, 10), (-23, 60), (-36, 10), (-72, 10)], -23.0),
             ("5: -26/-20/-26 x 20.1 s", [(-26, 20.1), (-20, 20.1), (-26, 20.1)], -23.0)]
    for name, parts, exp in cases:
        rows.append(row("loudness", f"integrated, Tech 3341 case {name}", exp,
                        float(L.integrated(seq(parts, 48000), 48000)), 0.1, "EBU-3341"))
    for sr in (44100, 96000):
        rows.append(row("loudness", f"integrated case 1 at {sr} Hz", -23.0,
                        float(L.integrated(seq([(-23, 20)], sr), sr)), 0.1, "EBU-3341"))
    x = seq([(-23, 20)], 48000)
    rows.append(row("loudness", "momentary max, steady -23 tone", -23.0, float(L.momentary(x, 48000).max()), 0.1, "EBU-3341"))
    rows.append(row("loudness", "short-term max, steady -23 tone", -23.0, float(L.short_term(x, 48000).max()), 0.1, "EBU-3341"))
    return rows


def check_ebu3342():
    rows = []
    for name, parts, exp in [("1: -20/-30", [(-20, 20), (-30, 20)], 10), ("2: -20/-15", [(-20, 20), (-15, 20)], 5),
                             ("3: -40/-20", [(-40, 20), (-20, 20)], 20),
                             ("4: -50/-35/-20/-35/-50", [(-50, 20), (-35, 20), (-20, 20), (-35, 20), (-50, 20)], 15)]:
        rows.append(row("loudness", f"LRA, Tech 3342 case {name}", exp,
                        float(L.analyze(seq(parts, 48000), 48000).lra), 1.0, "EBU-3342"))
    return rows


def check_truepeak():
    rows = []
    sr = 48000
    n = sr * 2
    k = np.arange(n)
    fade = np.minimum(1, np.minimum(k, n - 1 - k) / (0.05 * sr))
    s = np.sin(2 * np.pi * 0.25 * k + np.pi / 4) * fade
    s /= np.abs(s[2400:-2400]).max()
    rows.append(row("true peak", "fs/4 sine at 45°: TP - sample peak", 3.0103,
                    L.true_peak(s[:, None], sr) - L.sample_peak(s[:, None]), 0.05, "analytic"))
    c = siggen.bandlimited_click(sr, 0.9, 0.37)
    rows.append(row("true peak", "isolated band-limited pulse, peak between samples", float(db(0.9)),
                    L.true_peak(c, sr), 0.1, "analytic"))
    rows.append(row("true peak", "same pulse: sample peak under-reads by > 0.3 dB", True,
                    bool(L.sample_peak(c) < db(0.9) - 0.3), 0, "analytic"))
    rng = np.random.default_rng(3)
    errs = [L.true_peak((np.sin(2 * np.pi * f * k / sr + ph) * fade)[:, None], sr)
            for f, ph in zip(rng.uniform(0.02, 0.45, 60) * sr, rng.uniform(0, 2 * np.pi, 60))]
    rows.append(row("true peak", "60 random full-scale sines 0.02-0.45 fs: worst |error| dB", 0.0,
                    float(np.max(np.abs(errs))), 0.1, "analytic"))
    x = siggen.pink(10, 44100, seed=5, rms_dbfs=-12)
    y = dsp.limiter(x, 44100, ceiling_db=-1.0)
    rows.append(row("true peak", "reference limiter holds -1 dBTP on hot pink noise (TP)", -1.0,
                    L.true_peak(y, 44100), 0.05, "self-consistency"))
    return rows


def check_crossref(hw_files=()):
    """Independent implementations: pyloudnorm (integrated) and ffmpeg ebur128 (I, LRA, TP)."""
    rows = []
    sr = 48000
    signals = {"pink -20 dBFS": siggen.pink(20, sr, seed=2, rms_dbfs=-20),
               "EBU 3342 case 4": seq([(-50, 20), (-35, 20), (-20, 20), (-35, 20), (-50, 20)], sr)}
    for f in hw_files:
        a = aio.load(f)
        signals[os.path.basename(f)] = (a.x, a.sr)
    try:
        import pyloudnorm as pyln
    except ImportError:
        pyln = None
    for name, v in signals.items():
        x, fs = v if isinstance(v, tuple) else (v, sr)
        mine = L.analyze(x, fs)
        if pyln:
            rows.append(row("loudness", f"integrated vs pyloudnorm: {name}", float(pyln.Meter(fs).integrated_loudness(x)),
                            float(mine.integrated), 0.1, "cross-check"))
        ff = ffmpeg_ebur128(x, fs)
        if ff:
            rows.append(row("loudness", f"integrated vs ffmpeg ebur128: {name}", ff["I"], float(mine.integrated), 0.2, "cross-check"))
            rows.append(row("loudness", f"LRA vs ffmpeg ebur128: {name}", ff["LRA"], float(mine.lra), 0.5, "cross-check"))
            rows.append(row("true peak", f"TP vs ffmpeg ebur128: {name}", ff["TP"], float(mine.true_peak), 0.3, "cross-check"))
    return rows


def ffmpeg_ebur128(x, sr):
    if not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.wav")
        aio.save(p, x, sr)
        res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", p, "-af", "ebur128=peak=true",
                              "-f", "null", "-"], capture_output=True, text=True)
    txt = res.stderr.split("Summary:")[-1]
    try:
        I = float(re.search(r"I:\s+(-?[\d.]+) LUFS", txt).group(1))
        LRA = float(re.search(r"LRA:\s+(-?[\d.]+) LU", txt).group(1))
        TP = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", txt).group(1))
    except AttributeError:
        return None
    return {"I": I, "LRA": LRA, "TP": TP}


# ------------------------------------------------------------------ dynamics
def check_dynamics():
    rows = []
    sr = 44100
    rows.append(row("dynamics", "crest factor of a sine (dB)", 3.0103,
                    dynamics.crest_db(siggen.sine(100, -6, 2, sr)), 0.01, "analytic"))
    sq = np.sign(np.sin(2 * np.pi * 100 * np.arange(sr) / sr))[:, None] * 0.5
    rows.append(row("dynamics", "crest factor of a square wave (dB)", 0.0, dynamics.crest_db(sq), 0.01, "analytic"))
    gr = dsp.gain_computer(np.array([-10.0]), -20.0, 4.0, 0.0)[0]
    rows.append(row("dynamics", "gain computer: 10 dB over, 4:1 -> 7.5 dB GR", 7.5, float(gr), 1e-9, "analytic"))
    kl = siggen.kick_loop(sr)
    base = dynamics.transient_contrast(kl, sr)["transient_contrast_median_db"]
    slow = dynamics.transient_contrast(dsp.compressor(kl, sr, -30, 4, 30, 80, 0), sr)["transient_contrast_median_db"]
    fast = dynamics.transient_contrast(dsp.compressor(kl, sr, -30, 4, 0.1, 80, 0), sr)["transient_contrast_median_db"]
    rows.append(row("dynamics", "punch: slow-attack comp raises hit-vs-body contrast (> +2 dB)", True, bool(slow - base > 2), 0, "self-consistency"))
    rows.append(row("dynamics", "punch: 0.1 ms attack gives > 3 dB less contrast than 30 ms", True, bool(slow - fast > 3), 0, "self-consistency"))
    lim = dsp.limiter(kl * lin(12), sr, -1.0)
    rows.append(row("dynamics", "punch: 12 dB into a limiter lowers contrast (> 2 dB)", True,
                    bool(base - dynamics.transient_contrast(lim, sr)["transient_contrast_median_db"] > 2), 0, "self-consistency"))
    probe, lay = siggen.comp_probe(sr)
    wet = dsp.compressor(probe, sr, -20, 4, 10, 100, 6)
    delayed = np.vstack([np.zeros((1024, 2)), wet])[: len(wet)]           # plugin latency
    d2, w2, lag = dynamics.probe_align(probe, delayed)
    est = dynamics.comp_probe(d2, w2, sr, lay)
    rows.append(row("comp-probe", "1024-sample plugin latency found by onset alignment", 1024, lag, 0, "self-consistency"))
    rows.append(row("comp-probe", "attack ms with 1024-sample latency (10 ms set)", 10, est.get("attack_ms", -1), 2.0, "self-consistency"))
    rows.append(row("comp-probe", "release ms with 1024-sample latency (100 ms set)", 100, est.get("release_ms", -1), 20.0, "self-consistency"))
    for (th, ra, kn, at, rl) in [(-30, 4, 6, 10, 100), (-18, 2, 0, 1, 50), (-24, 8, 10, 30, 300)]:
        wet = dsp.compressor(probe, sr, th, ra, at, rl, kn, detector="peak")
        est = dynamics.comp_probe(probe, wet, sr, lay)
        tag = f"thr {th} / {ra}:1 / knee {kn} / A {at} ms / R {rl} ms"
        rows.append(row("comp-probe", f"threshold, {tag}", th, est["threshold_db"], 1.5, "self-consistency"))
        rows.append(row("comp-probe", f"ratio, {tag}", ra, est["ratio"], 0.15 * ra, "self-consistency"))
        rows.append(row("comp-probe", f"attack ms, {tag}", at, est.get("attack_ms", -1), max(2.0, 0.2 * at), "self-consistency"))
        rows.append(row("comp-probe", f"release ms, {tag}", rl, est.get("release_ms", -1), max(4.0, 0.2 * rl), "self-consistency"))
    return rows


# ------------------------------------------------------------------ spectrum / EQ
def check_spectrum():
    rows = []
    sr = 44100
    x = siggen.pink(30, sr, seed=4)
    tb = S.tonal_balance(x, sr)
    rows.append(row("spectrum", "pink noise density slope (dB/oct)", -3.01, tb["slope_db_per_oct"], 0.3, "analytic"))
    bands = [v for c, v in tb["third_octave"] if 100 <= c <= 10000]
    rows.append(row("spectrum", "pink noise 1/3-oct band spread 100 Hz-10 kHz (max-min dB)", 0.0,
                    float(max(bands) - min(bands)), 1.5, "analytic"))
    s = siggen.sine(1000, -10, 5, sr)
    to = S.third_octave(s, sr)
    i = int(np.argmin([abs(c - 1000) for c, _ in to]))
    rows.append(row("spectrum", "1 kHz sine lands in the 1 kHz band (> 30 dB above neighbours)", True,
                    bool(to[i][1] - max(to[i - 1][1], to[i + 1][1]) > 30), 0, "analytic"))
    bandsEQ = [{"type": "peak", "f": 1000, "gain_db": 6, "q": 1.0}, {"type": "lowshelf", "f": 100, "gain_db": -4, "q": 0.707},
               {"type": "highshelf", "f": 8000, "gain_db": 3, "q": 0.707}]
    y = dsp.eq(x, sr, bandsEQ)
    res = S.eq_diff(x, y, sr)
    f = np.array(res["freq_hz"])
    g = np.array(res["gain_db"])
    for fq in (40, 100, 1000, 3000, 12000):
        exp = float(sum(dsp.biquad_response_db(b["type"], b["f"], sr, b["gain_db"], b["q"], [fq])[0] for b in bandsEQ))
        rows.append(row("eq-diff", f"recovered EQ gain at {fq} Hz", exp, float(np.interp(fq, f, g)), 0.3, "self-consistency"))
    for ph in (40, 60, 80):
        _, lp = S.iso226(ph, [1000])
        rows.append(row("equal-loudness", f"ISO 226 contour at 1 kHz equals {ph} phon", float(ph), float(lp[0]), 0.05, "ISO 226"))
    _, lo = S.iso226(40, [50])
    rows.append(row("equal-loudness", "40 phon needs more SPL at 50 Hz than at 1 kHz (> +20 dB)", True, bool(lo[0] - 40 > 20), 0, "ISO 226"))
    st = S.stereo_by_band(np.hstack([x[:, :1], -x[:, :1]]), sr)
    rows.append(row("stereo", "polarity-inverted channels: low-band correlation", -1.0, st[0]["correlation"], 0.01, "analytic"))
    return rows


# ------------------------------------------------------------------ bit depth
def check_bitdepth():
    rows = []
    sr = 44100
    x = siggen.pink(5, sr, seed=6, rms_dbfs=-20)
    for bits in (16, 24):
        rows.append(row("bitdepth", f"effective bits of a {bits}-bit quantised signal", bits,
                        bitdepth.effective_bits(dsp.quantize(x, bits)), 0, "analytic"))
    rows.append(row("bitdepth", "effective bits of float noise (> 24)", 32, bitdepth.effective_bits(x), 0, "analytic"))
    for d in ("none", "rpdf", "tpdf"):
        e = dsp.quantize(x, 16, d, seed=1) - x
        rows.append(row("bitdepth", f"16-bit error floor, {d} (dBFS rms)", bitdepth.theoretical_floor_dbfs(16, d),
                        float(db(np.sqrt(np.mean(e ** 2)))), 0.2, "analytic"))
    n = sr * 6
    t = np.arange(n) / sr
    fade = (np.sin(2 * np.pi * 1000 * t) * lin(np.linspace(-40, -96, n)))[:, None]
    tr = bitdepth.truncation_distortion(fade, dsp.truncate(fade, 16), sr, 1000)
    dt_ = bitdepth.truncation_distortion(fade, dsp.quantize(fade, 16, "tpdf"), sr, 1000)
    rows.append(row("bitdepth", "truncation puts >8 dB more of its error at harmonics than TPDF", True,
                    bool(tr - dt_ > 8), 0, "analytic"))
    e = dsp.quantize(x, 16, "tpdf", shaping=True) - x
    f, p = __import__("scipy.signal", fromlist=["welch"]).welch(e[:, 0], sr, nperseg=4096)
    tilt = 10 * np.log10(p[(f > 15000) & (f < 20000)].mean() / p[(f > 1000) & (f < 5000)].mean())
    rows.append(row("bitdepth", "noise-shaped dither error rises > 6 dB toward HF", True, bool(tilt > 6), 0, "analytic"))
    return rows


# ------------------------------------------------------------------ premaster
def check_premaster():
    rows = []
    sr = 44100
    from scipy import signal as sps
    hp = sps.butter(2, 25, "highpass", fs=sr, output="sos")      # real mixes carry no infrasound
    m = sps.sosfilt(hp, siggen.pink(8, sr, ch=1, seed=7), axis=0)
    side = sps.sosfilt(hp, siggen.pink(8, sr, ch=1, seed=17), axis=0) * 0.3
    base = np.hstack([m + side, m - side])            # correlated stereo, like a mix
    base = base * (lin(-6) / np.max(np.abs(base)))
    k = np.arange(len(base))
    fade = np.clip((np.minimum(k, len(base) - 1 - k) - 0.1 * sr) / (0.3 * sr), 0, 1)[:, None]
    clean = base * fade                                # 0.1 s silence, then a 0.3 s fade

    def status(x, check, subtype="PCM_24"):
        res = premaster.run(aio.Audio(x, sr, "t", subtype, "WAV"))
        return next(r_["status"] for r_ in res["checks"] if r_["check"] == check), res["overall"]

    rows.append(row("premaster", "clean 24-bit mix with fades: overall", "PASS", status(clean, "format")[1], 0, "planted fault"))
    c = clean.copy()
    c[40000:40010] = 1.0
    rows.append(row("premaster", "10 samples at full scale: clipped_runs", "FAIL", status(c, "clipped_runs")[0], 0, "planted fault"))
    rows.append(row("premaster", "DC offset -40 dBFS: dc_offset_dbfs", "WARN", status(clean + 0.01, "dc_offset_dbfs")[0], 0, "planted fault"))
    inv = clean.copy()
    inv[:, 1] *= -1
    rows.append(row("premaster", "one channel polarity-inverted: correlation", "FAIL", status(inv, "correlation")[0], 0, "planted fault"))
    crushed = dsp.clip(clean * lin(20), -0.3)
    rows.append(row("premaster", "clipped/limited main bus (PLR < 8): plr_db", "WARN", status(crushed, "plr_db")[0], 0, "planted fault"))
    rows.append(row("premaster", "no fade-out: tail_last_10ms_dbfs", "WARN", status(base, "tail_last_10ms_dbfs")[0], 0, "planted fault"))
    rows.append(row("premaster", "16-bit export: format", "WARN", status(clean, "format", "PCM_16")[0], 0, "planted fault"))
    return rows


# ------------------------------------------------------------------ compare / delivery / als
def check_compare_delivery():
    rows = []
    sr = 44100
    a = aio.from_array(siggen.pink(10, sr, seed=8, rms_dbfs=-18), sr)
    b = aio.from_array(siggen.pink(10, sr, seed=9, rms_dbfs=-26), sr)
    (xa, _), (xb, _) = compare.match([a, b])[0]
    rows.append(row("compare", "loudness match: |LUFS A - LUFS B|", 0.0, abs(L.integrated(xa, sr) - L.integrated(xb, sr)), 0.01, "analytic"))
    rows.append(row("compare", "ABX: P(>=10 of 12 by guessing)", 0.0193, compare.binom_p(10, 12), 0.0001, "analytic"))
    rows.append(row("compare", "ABX: P(>=9 of 12 by guessing)", 0.0730, compare.binom_p(9, 12), 0.0001, "analytic"))
    nm = delivery.normalization(-8.0, -0.5)
    rows.append(row("delivery", "YouTube gain for a -8 LUFS master", -6.0, nm["youtube"]["gain_db"], 1e-9, "platform model"))
    nm = delivery.normalization(-20.0, -6.0)
    rows.append(row("delivery", "YouTube leaves a -20 LUFS master alone", 0.0, nm["youtube"]["gain_db"], 1e-9, "platform model"))
    if delivery.codec_available("aac128"):
        x = siggen.pink(8, sr, seed=10, rms_dbfs=-18)
        y = delivery.roundtrip(x, sr, "aac128")
        from scipy import signal as sps
        sos = sps.butter(4, 4000, "lowpass", fs=sr, output="sos")
        a_, b_ = sps.sosfilt(sos, x[: len(y), 0]), sps.sosfilt(sos, y[:, 0])
        cc = float(np.corrcoef(a_, b_)[0, 1])
        rows.append(row("delivery", "AAC round-trip time-aligned (correlation below 4 kHz)", 1.0, cc, 0.02, "self-consistency"))
    return rows


def check_als():
    rows = []
    s12 = als.read(os.path.join(FIX, "L12-automation.als"))
    rows.append(row("als", "Live 12 set: tempo read from MainTrack", 120.0, s12["tempo"], 0, "fixture"))
    s10 = als.read(os.path.join(FIX, "example-140.als"))
    rows.append(row("als", "Live 10 set: tempo read from MasterTrack", 140.0, s10["tempo"], 0, "fixture"))
    # plant devices into a copy of the Live 12 fixture
    raw = gzip.open(os.path.join(FIX, "L12-automation.als")).read().decode()
    lim = '<Limiter Id="900"><On><Manual Value="true" /></On><UserName Value="" /></Limiter>'
    plug = ('<PluginDevice Id="901"><On><Manual Value="false" /></On><UserName Value="" /><PluginDesc>'
            '<VstPluginInfo Id="0"><PlugName Value="Decapitator" /></VstPluginInfo></PluginDesc></PluginDevice>')
    def plant(text, after_tag, xml):
        i = text.index(after_tag)
        mt = re.compile(r"<Devices\s*/>|<Devices>").search(text, i)
        tag = mt.group(0)
        new = "<Devices>" + xml + ("</Devices>" if tag.endswith("/>") else "")
        return text[:mt.start()] + new + text[mt.end():]
    raw2 = plant(plant(raw, "<MainTrack", lim), "<AudioTrack", plug)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "planted.als")
        with gzip.open(p, "wb") as f:
            f.write(raw2.encode())
        s = als.read(p)
    txt = " ".join(s["findings"])
    rows.append(row("als", "planted Limiter on main bus is flagged", True, "Limiter" in txt, 0, "planted fault"))
    rows.append(row("als", "planted switched-off Decapitator is flagged", True, "Decapitator" in txt, 0, "planted fault"))
    return rows


def check_edge_cases():
    rows = []
    sr = 44100
    z = np.zeros((sr * 5, 2))
    res = premaster.run(aio.Audio(z, sr, "silent", "PCM_24", "WAV"))
    rows.append(row("premaster", "all-zero file: overall", "FAIL", res["overall"], 0, "planted fault"))
    nm = delivery.normalization(L.integrated(z, sr), L.true_peak(z, sr))
    rows.append(row("delivery", "all-zero file: no platform gain invented", True, nm["spotify"]["gain_db"] is None, 0, "planted fault"))
    short = siggen.sine(1000, -20, 1.0, sr)
    rows.append(row("loudness", "1 s file: LRA undefined (needs > 3 s)", True, bool(np.isnan(L.analyze(short, sr).lra)), 0, "EBU-3342"))
    return rows


def check_sections():
    """A synthetic song with known tempo, break, peak and drop (siggen.song_sections)."""
    from mlab import sections as SE
    rows = []
    sr = 44100
    for bpm in (157.3, 140.0):
        x, truth = siggen.song_sections(sr, bpm)
        a = SE.analyze(x, sr)
        rows.append(row("sections", f"tempo of a {bpm} BPM song (BPM)", bpm, a["bpm"], 0.05, "analytic"))
        rows.append(row("sections", f"break found at bars {truth['break']} ({bpm} BPM)", truth["break"], a["main_break"], 0, "analytic"))
        rows.append(row("sections", f"peak window = densest {truth['peak']} ({bpm} BPM)", truth["peak"], a["peak_bars"], 0, "analytic"))
        rows.append(row("sections", f"drop vs peak highs, hats +6.02 dB in peak ({bpm} BPM)", -6.02, a["drop_vs_peak_high_db"], 0.5, "analytic"))
    # planted fault: a one-bar kick dropout inside the peak must not move the window
    x, truth = siggen.song_sections(sr, 150.0, dropout_bar=truth["peak"][0] + 5)
    a = SE.analyze(x, sr)
    rows.append(row("sections", "peak window survives a one-bar kick dropout", truth["peak"], a["peak_bars"], 0, "planted fault"))
    return rows


ALL = [check_edge_cases, check_kweighting, check_ebu3341, check_ebu3342, check_truepeak, check_dynamics,
       check_spectrum, check_bitdepth, check_premaster, check_compare_delivery, check_als, check_sections]


def hw_files():
    if not os.path.isdir(HW):
        return []
    return sorted(os.path.join(HW, f) for f in os.listdir(HW)
                  if os.path.splitext(f)[1].lower() in (".wav", ".mp3", ".flac", ".aif", ".aiff"))[:3]


def run_all(crosscheck=True):
    rows = []
    for fn in ALL:
        rows += fn()
    if crosscheck:
        rows += check_crossref(hw_files())
    return rows


def write_report(path, crosscheck=True):
    rows = run_all(crosscheck)
    n_ok = sum(r_["ok"] for r_ in rows)
    lines = ["# Calibration report", "",
             f"Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} by `python3 -m mlab calibrate`.",
             f"**{n_ok} / {len(rows)} checks pass.**", "",
             "Basis: EBU-3341/3342 and BS.1770 = published test cases, re-synthesised; analytic = closed-form; "
             "self-consistency = recovers a known processor; cross-check = independent implementation; "
             "planted fault = a defect inserted on purpose.", "",
             "| instrument | case | expected | measured | tol | ok | basis |", "|---|---|---|---|---|---|---|"]
    for r_ in rows:
        m = r_["measured"]
        m = round(m, 4) if isinstance(m, float) else m
        e = r_["expected"]
        e = round(e, 4) if isinstance(e, float) else e
        lines.append(f"| {r_['instrument']} | {r_['case']} | {e} | {m} | {r_['tol']} | {'✅' if r_['ok'] else '❌'} | {r_['basis']} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{n_ok}/{len(rows)} checks pass -> {os.path.relpath(path, LAB)}")
    for r_ in rows:
        if not r_["ok"]:
            print(f"  FAIL {r_['instrument']}: {r_['case']}: expected {r_['expected']}, got {r_['measured']}")
    return n_ok == len(rows)
