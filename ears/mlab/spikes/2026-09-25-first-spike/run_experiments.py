"""Mastering spike: five small experiments on a synthetic test mix.
Run: python3 run_experiments.py   (needs numpy scipy soundfile pyloudnorm)
All output WAVs land in ./out, numbers in ./RESULTS.md."""
import os, json, random
import numpy as np, soundfile as sf, pyloudnorm as pyln
from scipy import signal
from scipy.ndimage import minimum_filter1d

SR = 44100
rng = np.random.default_rng(7)
OUT = "out"; os.makedirs(OUT, exist_ok=True)
meter = pyln.Meter(SR)
db = lambda x: 20 * np.log10(np.maximum(x, 1e-12))
lin = lambda d: 10 ** (d / 20)
report = []

def lufs(x): return meter.integrated_loudness(x)
def sample_peak(x): return db(np.max(np.abs(x)))
def true_peak(x):  # 4x oversampled peak, per ITU-R BS.1770 style
    return db(np.max(np.abs(signal.resample_poly(x, 4, 1, axis=0))))
def crest(x): return sample_peak(x) - db(np.sqrt(np.mean(x ** 2)))
def stats(name, x):
    L = lufs(x); tp = true_peak(x)
    return dict(file=name, LUFS=round(L, 1), sample_peak=round(sample_peak(x), 2),
                true_peak=round(tp, 2), PLR=round(tp - L, 1), crest=round(crest(x), 1))
def write(name, x, subtype="FLOAT"):
    sf.write(os.path.join(OUT, name), x, SR, subtype=subtype); return name

# ---------- synthetic "premaster": drums, bass, pad, 12 s @ 120 bpm ----------
BEAT = 0.5; N = int(SR * 12); t_all = np.arange(N) / SR
mix = np.zeros((N, 2)); drums = np.zeros((N, 2))
def place(buf, snd, start, pan=0.0):
    i = int(start * SR); j = min(N, i + len(snd)); s = snd[: j - i]
    buf[i:j, 0] += s * np.cos((pan + 1) * np.pi / 4); buf[i:j, 1] += s * np.sin((pan + 1) * np.pi / 4)
def env(n, tau): return np.exp(-np.arange(n) / (SR * tau))
def kick():
    n = int(0.45 * SR); t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t / 0.04); ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * env(n, 0.18) + 0.3 * rng.standard_normal(n) * env(n, 0.003)
def snare():
    n = int(0.3 * SR); b, a = signal.butter(2, [1500, 7000], "band", fs=SR)
    return 0.6 * signal.lfilter(b, a, rng.standard_normal(n)) * env(n, 0.07) + 0.5 * np.sin(2*np.pi*190*np.arange(n)/SR) * env(n, 0.05)
def hat():
    n = int(0.08 * SR); b, a = signal.butter(4, 8000, "high", fs=SR)
    return 0.25 * signal.lfilter(b, a, rng.standard_normal(n)) * env(n, 0.015)
for bar in range(6):
    t0 = bar * 4 * BEAT
    for bt in (0, 2, 2.5): place(drums, kick(), t0 + bt * BEAT)
    for bt in (1, 3): place(drums, snare(), t0 + bt * BEAT, 0.1)
    for e in range(8): place(drums, hat() * (1 if e % 2 else 0.6), t0 + e * BEAT / 2, 0.4)
roots = [55.0, 43.65, 65.41, 49.0]  # A1 F1 C2 G1
chords = [[220, 261.6, 329.6], [174.6, 220, 261.6], [261.6, 329.6, 392], [196, 246.9, 293.7]]
bass = np.zeros(N); pad = np.zeros((N, 2))
for k in range(12):  # one chord per 2 beats... per bar-half
    i, j = int(k * SR), int((k + 1) * SR); t = np.arange(j - i) / SR; c = k // 3 % 4
    saw = signal.sawtooth(2 * np.pi * roots[c] * t)
    bass[i:j] += 0.5 * saw * np.minimum(1, t / 0.01) * np.exp(-t / 0.8)
    for f in chords[c]:
        pad[i:j, 0] += 0.07 * signal.sawtooth(2 * np.pi * f * 1.003 * t)
        pad[i:j, 1] += 0.07 * signal.sawtooth(2 * np.pi * f * 0.997 * t)
bass = signal.lfilter(*signal.butter(2, 300, fs=SR), bass)
pad = signal.lfilter(*signal.butter(2, 2500, fs=SR), pad, axis=0)
mix = drums + bass[:, None] * np.array([0.7, 0.7]) + pad
mix *= lin(-6) / np.max(np.abs(mix))  # premaster: peaks at -6 dBFS, headroom left
write("00_premaster.wav", mix)
report.append(("Premaster (the raw test mix)", [stats("00_premaster.wav", mix)]))

# ---------- limiter used by several experiments ----------
def limiter(x, ceiling_db, look_ms=5, rel_ms=80):
    la = int(SR * look_ms / 1000); c = lin(ceiling_db)
    up = np.abs(signal.resample_poly(x, 4, 1, axis=0))[: 4 * len(x)]
    peak = np.max(up.reshape(len(x), 4, -1), axis=(1, 2))
    g = np.minimum(1.0, c / np.maximum(peak, 1e-12))
    g = minimum_filter1d(g, size=2 * la + 1)  # attack spread over lookahead
    a = np.exp(-1 / (SR * rel_ms / 1000)); out = np.empty_like(g); s = 1.0
    for i, v in enumerate(g):
        s = v if v < s else a * s + (1 - a) * v; out[i] = s
    return np.clip(x * out[:, None], -c, c)
def master_to(x, target_lufs, ceiling_db):
    lo, hi = -10.0, 30.0
    for _ in range(14):
        g = (lo + hi) / 2; y = limiter(x * lin(g), ceiling_db)
        lo, hi = (g, hi) if lufs(y) < target_lufs else (lo, g)
    return y, g

# ---------- EXP 1: loudness bias (blind +1 dB) ----------
A = mix * lin(-20 - lufs(mix)); B = A * lin(1.0)
pair = [("A_original", A), ("B_plus1dB", B)]; random.Random(os.urandom(4)).shuffle(pair)
write("01_blind_X.wav", pair[0][1]); write("01_blind_Y.wav", pair[1][1])
with open(os.path.join(OUT, "01_answer_key_DONT_PEEK.txt"), "w") as f:
    f.write(f"X = {pair[0][0]}\nY = {pair[1][0]}\nSame audio. Only difference: 1 dB of gain.\n")
report.append(("Exp 1 — loudness bias (identical audio, one is +1 dB)", [stats("01_blind_X.wav", pair[0][1]), stats("01_blind_Y.wav", pair[1][1])]))

# ---------- EXP 2: LUFS vs peak, and what streaming normalization does ----------
gentle, gg = master_to(mix, -14, -1.0); crushed, gc = master_to(mix, -9, -0.1)
write("02_master_gentle_-14LUFS.wav", gentle); write("02_master_crushed_-9LUFS.wav", crushed)
g_norm = gentle * lin(-14 - lufs(gentle)); c_norm = crushed * lin(-14 - lufs(crushed))
write("02_gentle_after_normalization.wav", g_norm); write("02_crushed_after_normalization.wav", c_norm)
report.append((f"Exp 2 — two masters (limiter drive: gentle +{gg:.1f} dB, crushed +{gc:.1f} dB), then both turned to -14 LUFS like a streaming service",
               [stats("02_master_gentle_-14LUFS.wav", gentle), stats("02_master_crushed_-9LUFS.wav", crushed),
                stats("02_gentle_after_normalization.wav", g_norm), stats("02_crushed_after_normalization.wav", c_norm)]))

# ---------- EXP 3: inter-sample peaks ----------
n = SR * 3; k = np.arange(n)
isp = np.sin(2 * np.pi * (SR / 4) * k / SR + np.pi / 4)  # 11.025 kHz; samples land at ±0.707 of true amplitude
isp *= lin(-0.1) / np.max(np.abs(isp)); isp = np.stack([isp, isp], 1) * 0.999
write("03_isp_sine.wav", isp, "PCM_24")
tp_c = true_peak(crushed)
os.system(f"ffmpeg -loglevel error -y -i {OUT}/02_master_crushed_-9LUFS.wav -c:a aac -b:a 128k {OUT}/03_crushed.m4a && "
          f"ffmpeg -loglevel error -y -i {OUT}/03_crushed.m4a -c:a pcm_f32le {OUT}/03_crushed_decoded.wav")
dec, _ = sf.read(f"{OUT}/03_crushed_decoded.wav"); over = int(np.sum(np.abs(dec) > 1.0))
gen = gentle
os.system(f"ffmpeg -loglevel error -y -i {OUT}/02_master_gentle_-14LUFS.wav -c:a aac -b:a 128k {OUT}/03_gentle.m4a && "
          f"ffmpeg -loglevel error -y -i {OUT}/03_gentle.m4a -c:a pcm_f32le {OUT}/03_gentle_decoded.wav")
dg, _ = sf.read(f"{OUT}/03_gentle_decoded.wav"); over_g = int(np.sum(np.abs(dg) > 1.0))
report.append(("Exp 3 — inter-sample peaks", [
    dict(file="03_isp_sine.wav", sample_peak=round(sample_peak(isp), 2), true_peak=round(true_peak(isp), 2)),
    dict(file="crushed master → AAC 128k → decoded", sample_peak_after=round(sample_peak(dec), 2), samples_over_0dBFS=over),
    dict(file="gentle master → AAC 128k → decoded", sample_peak_after=round(sample_peak(dg), 2), samples_over_0dBFS=over_g)]))

# ---------- EXP 4: dither vs truncation at 16-bit ----------
n = SR * 6; t = np.arange(n) / SR
fade = np.sin(2 * np.pi * 1000 * t) * lin(np.linspace(-40, -96, n))  # quiet tone fading into the noise floor
q = 1 / 32768
trunc = np.floor(fade / q) * q
tpdf = (rng.random(n) - rng.random(n)) * q
dith = np.round((fade + tpdf) / q) * q
boost = lin(60)  # listen to the tail, loudly — START WITH VOLUME LOW
for nm, x in (("truncated", trunc), ("dithered", dith)):
    write(f"04_fade16_{nm}_+60dB_LISTEN_QUIETLY.wav", np.stack([x, x], 1) * boost * 0.5)
def thd_like(x):  # energy at harmonics of 1 kHz vs total error, last 2 s
    seg = (x - fade)[-2 * SR:]; S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2; f = np.fft.rfftfreq(len(seg), 1 / SR)
    harm = sum(S[np.abs(f - h * 1000) < 5].sum() for h in range(2, 20)); return 10 * np.log10(harm / S.sum() + 1e-20)
report.append(("Exp 4 — 16-bit reduction of a fading 1 kHz tone (error = output minus original)", [
    dict(file="truncated", error_rms_dBFS=round(db(np.sqrt(np.mean((trunc - fade) ** 2))), 1), harmonic_share_of_error_dB=round(thd_like(trunc), 1)),
    dict(file="TPDF dithered", error_rms_dBFS=round(db(np.sqrt(np.mean((dith - fade) ** 2))), 1), harmonic_share_of_error_dB=round(thd_like(dith), 1))]))

# ---------- EXP 5: compressor attack / release on the drums ----------
def compress(x, thr_db, ratio, att_ms, rel_ms, knee_db=6):
    pk = np.max(np.abs(x), axis=1); e = np.empty_like(pk); r = np.exp(-1 / (SR * 0.01)); v = 0.0
    for i, p in enumerate(pk):
        v = p if p > v else r * v; e[i] = v
    lvl = db(e); over = lvl - thr_db
    gr = np.where(over <= -knee_db / 2, 0, np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                  (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    aa, ar = np.exp(-1 / (SR * att_ms / 1000)), np.exp(-1 / (SR * rel_ms / 1000)); s = 0.0; out = np.empty_like(gr)
    for i, v in enumerate(gr):
        c = aa if v > s else ar; s = c * s + (1 - c) * v; out[i] = s
    return x * lin(-out)[:, None], out
d = drums * lin(-21 - lufs(drums))
rows = [stats("05_drums_dry.wav", d)]; write("05_drums_dry.wav", d)
for nm, att, rel in (("fastA_fastR", 0.3, 40), ("slowA_fastR", 30, 40), ("fastA_slowR", 0.3, 400), ("slowA_slowR", 30, 400)):
    y, gr = compress(d, -20, 4, att, rel); y = y * lin(-21 - lufs(y))  # LEVEL-MATCHED to the dry file
    fn = f"05_drums_{nm}.wav"; write(fn, y); s = stats(fn, y); s["avg_GR_dB"] = round(gr.mean(), 1); s["max_GR_dB"] = round(gr.max(), 1); rows.append(s)
report.append(("Exp 5 — compressor, 4:1, threshold -20 dBFS, 6 dB knee; every output level-matched to -21 LUFS", rows))

with open("RESULTS.md", "w") as f:
    f.write("# Mastering spike — results\n\nAll audio in `out/`. PLR = true peak minus LUFS (a crest-factor measure for loudness).\n")
    for title, rows in report:
        f.write(f"\n## {title}\n\n"); keys = list(dict.fromkeys(k for r in rows for k in r))
        f.write("| " + " | ".join(keys) + " |\n|" + "---|" * len(keys) + "\n")
        for r in rows: f.write("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |\n")
print(open("RESULTS.md").read())
