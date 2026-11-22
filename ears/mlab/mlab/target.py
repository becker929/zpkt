"""A mix against references, section by section.

HW002 is compared with purchased reference tracks in two windows: the BUILD
(16 bars before the drop) and the DROP (16 bars from it). The references are
mastered and the mix is not, so every spectral value here is shape, not
level: band power in dB minus the window's own integrated loudness
("dB rel LUFS"). That is the normalisation of the earlier one-off analysis
(contrib/arranger/spectral.py); keep it so the numbers stay comparable.

- `windows`: build/drop spans in seconds from the drop time and the bar length.
- `profile`: per window LUFS, true peak, PLR, 1/3-octave bands and named
  regions (dB rel LUFS), side-minus-mid per region, block crest and punch;
  plus the section contrast, LUFS(drop) - LUFS(build).
- `ref_stats`, `gaps`: the references' mean (of dB values), min and max for
  every value, and the mix's diff (mix - mean) and outside (0 inside the
  references' range, else the signed distance to the nearest edge).
- `load_refs`: the arranger's refs.json (id, file, drop, barSeconds, set).

Band power integrates the PSD exactly: each bin is a constant density
over its own width, so a band edge may cut a bin. The PSD weights every
sample of a window equally (see psd), so a beat-locked hop cannot tilt it. spectrum.third_octave
sums with a trapezoid over the bins inside a band, which reads the 25-50 Hz
bands 1-3 dB low, and differently at 44.1 and 48 kHz (LEARNINGS L-019).
Mix and references may have different sample rates: the PSD is a density
per Hz and loudness builds its K-weighting per rate.

A one-channel file is measured as dual mono (as it plays on two speakers),
so its dB rel LUFS match the same audio in a stereo file.

Known answers: calibration/checks.py (check_target).
"""
from __future__ import annotations

import json
import os

import numpy as np

from . import dynamics as D
from . import loudness as L
from . import spectrum as S
from .util import pdb

BARS = 16                                   # build and drop: 16 bars each
MIN_BARS = 4                                # a window clipped below 4 bars is skipped
LAYOUT = {"build": (-BARS, 0), "drop": (0, BARS)}   # bar offsets from the drop
SCORE_HZ = (31.5, 16000.0)                  # 1/3-octave bands that count in scores
SM_FLOOR = -99.0                            # side-minus-mid floor (a mono file has no side)
SCALARS = ("lufs", "true_peak_db", "plr_db", "block_crest_median_db", "transient_contrast_median_db")

# key, label, lo Hz, hi Hz. The first eight tile 20 Hz-20 kHz; side/mid uses their edges.
REGIONS = [
    ("sub", "sub 20-60", 20, 60), ("bass", "bass 60-120", 60, 120),
    ("low_mids", "low mids 120-300", 120, 300), ("mud", "mud 300-600", 300, 600),
    ("mids", "mids 600-1.5k", 600, 1500), ("upper_mids", "upper mids 1.5-4k", 1500, 4000),
    ("presence", "presence 4-8k", 4000, 8000), ("air", "air 8-20k", 8000, 20000),
    ("deep_sub", "deep sub 20-48", 20, 48), ("kick_body", "kick/bass body 55-120", 55, 120),
    ("bite", "bite 1-4k", 1000, 4000), ("air_8_14k", "air 8-14k", 8000, 14000),
]
REGION_KEYS = [k for k, *_ in REGIONS]
LABELS = {k: lab for k, lab, *_ in REGIONS}
SM_EDGES = (20, 60, 120, 300, 600, 1500, 4000, 8000, 20000)
SM_KEYS = REGION_KEYS[:8]
NOMINAL = ["25", "31.5", "40", "50", "63", "80", "100", "125", "160", "200", "250", "315", "400", "500",
           "630", "800", "1k", "1.25k", "1.6k", "2k", "2.5k", "3.15k", "4k", "5k", "6.3k", "8k", "10k",
           "12.5k", "16k", "20k"]                 # IEC nominal names of spectrum.CENTRES


def nominal(hz):
    """Nominal name of a 1/3-octave centre: 31.6 -> '31.5', 1258.9 -> '1.25k'."""
    i = int(np.argmin(np.abs(np.log(S.CENTRES / hz))))
    return NOMINAL[i] if abs(np.log(S.CENTRES[i] / hz)) < 0.05 else f"{hz:g}"


def hz_text(hz):
    n = nominal(hz)
    return n[:-1] + " kHz" if n.endswith("k") else n + " Hz"


# ------------------------------------------------------------------ windows
def windows(drop_s, bar_s, layout=None):
    """{name: (start_s, end_s)}: build = 16 bars before the drop, drop = 16 bars from it.

    `layout` adds or replaces windows as bar offsets from the drop, e.g.
    {"drop2": (16, 24)}; a value of None removes a default window."""
    lay = dict(LAYOUT)
    lay.update(layout or {})
    return {k: (float(drop_s + v[0] * bar_s), float(drop_s + v[1] * bar_s))
            for k, v in lay.items() if v is not None}


def _stereo(x):
    x = np.asarray(x, dtype=float)
    x = x[:, None] if x.ndim == 1 else x
    return np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x


TP_CONTEXT = 512                            # samples of real context each side for true peak


def window_true_peak(x, sr, a, b):
    """True peak (dBTP) of samples [a, b) oversampled with up to TP_CONTEXT samples of real
    context each side, so a window edge cut through a loud sample is not read as a step."""
    lo, hi = max(0, a - TP_CONTEXT), min(len(x), b + TP_CONTEXT)
    env = L.true_peak_envelope(x[lo:hi], sr)[a - lo:b - lo]
    return float(20 * np.log10(np.max(env))) if env.size and np.max(env) > 0 else float("-inf")


def segments(x, sr, wins, bar_s=None):
    """Clip each window to the file. Returns ({name: (span, seg)}, {name: why skipped})."""
    dur = len(x) / sr
    min_s = max(MIN_BARS * bar_s if bar_s else 0.0, 0.4)    # at least one 400 ms loudness block
    keep, skipped = {}, {}
    for name, (a, b) in wins.items():
        a2, b2 = max(0.0, float(a)), min(dur, float(b))
        if b2 - a2 < min_s - 1e-6:
            skipped[name] = (f"{max(0.0, b2 - a2):.2f} s inside the file, needs {min_s:.2f} s"
                             + (f" ({MIN_BARS} bars)" if bar_s else ""))
            continue
        keep[name] = ((a2, b2), x[int(round(a2 * sr)):int(round(b2 * sr))])
    return keep, skipped


# ------------------------------------------------------------------ spectrum
SEG_S = 0.75                                # Hann segment length in seconds, at every rate


def nperseg(sr):
    """Segment length: 0.75 s at any rate, rounded to a multiple of 4 samples so the
    75 % overlap hop is exact. 44.1 and 48 kHz share one grid of ~1.33 Hz bins."""
    return 4 * int(round(SEG_S * sr / 4))


def psd(seg, sr):
    """Channel-averaged PSD that weights every sample of the window equally.

    Hann segments at 75 % overlap: squared Hann windows then sum to a constant,
    so no moment counts more than another. The window is zero-padded by one
    segment at each end, so its first and last samples are covered like the
    rest, and rescaled by that coverage: the PSD integrates to the window's mean
    square (Parseval). Plain Welch at 50 % overlap swings its time weight by
    2:1 every hop; a 0.375 s hop is one beat at 160 BPM, so it locked to the
    beat. It also dropped the tail after the last full segment (LEARNINGS L-023)."""
    from scipy import signal as sps
    x = np.asarray(seg, dtype=float)
    x = x[:, None] if x.ndim == 1 else x
    x = x - x.mean(axis=0)                  # constant detrend over the whole window
    n = nperseg(sr)
    hop = n // 4
    z = np.zeros((n, x.shape[1]))
    xp = np.concatenate([z, x, z])
    f, p = sps.welch(xp, sr, window="hann", nperseg=n, noverlap=n - hop, detrend=False, axis=0,
                     scaling="density")
    k = (len(xp) - n) // hop + 1            # segments welch averaged
    # mean over k segments of sum(w^2 x^2) / sum(w^2): coverage sum_k w^2 = 1.5 on the window,
    # sum(w^2) = 3n/8, so the mean is 4 * sum(x^2) / (k n); the window's mean square is sum(x^2) / L
    return f, p.mean(axis=1) * k * n / (4.0 * len(x))


def band_grid(sr):
    """Centres and edges of spectrum.third_octave's bands that fit under Nyquist."""
    c = S.CENTRES[S.CENTRES * 10 ** 0.05 <= sr / 2]
    return c, c / 10 ** 0.05, c * 10 ** 0.05


def band_power(f, p, lo, hi):
    """Integral of the PSD over [lo, hi) Hz (scalars or arrays).

    Each bin is a constant density over its own width (f[k] +/- df/2), so the
    running integral is piecewise linear in f and interpolates exactly."""
    e = np.concatenate([[0.0], (f[:-1] + f[1:]) / 2, [f[-1]]])
    c = np.concatenate([[0.0], np.cumsum(p * np.diff(e))])
    return np.interp(hi, e, c) - np.interp(lo, e, c)


def region_edges(sr):
    lo = np.array([r[2] for r in REGIONS], float)
    return lo, np.minimum([r[3] for r in REGIONS], sr / 2)


def spectral(seg, sr, lufs):
    """1/3-octave bands [[hz, dB rel LUFS], ...] and regions {key: dB rel LUFS}."""
    f, p = psd(seg, sr)
    c, lo, hi = band_grid(sr)
    bands = [[float(cc), float(pdb(v) - lufs)] for cc, v in zip(c, band_power(f, p, lo, hi))]
    rp = band_power(f, p, *region_edges(sr))
    return bands, {k: float(pdb(v) - lufs) for k, v in zip(REGION_KEYS, rp)}


def side_minus_mid(seg, sr):
    """Side energy minus mid energy per region (dB), spectrum.stereo_by_band's method.
    A mono file has no side: it reads SM_FLOOR."""
    seg = _stereo(seg)
    st = S.stereo_by_band(seg, sr, SM_EDGES)
    return {k: max(SM_FLOOR, float(b["side_minus_mid_db"])) for k, b in zip(SM_KEYS, st)}


# ------------------------------------------------------------------ profile
def profile(x, sr, wins, bar_s=None):
    """Measures of one file per window. Pass bar_s so windows clipped to under
    MIN_BARS bars are skipped (a silent window is skipped too).

    Per window: lufs, true_peak_db, plr_db, bands [[hz, dB rel LUFS]], regions,
    side_minus_mid_db (per region of SM_KEYS), block_crest_median_db,
    transient_contrast_median_db (punch). Top level: contrast_lu = LUFS(drop) - LUFS(build)."""
    x = np.asarray(x, dtype=float)
    chans = 1 if x.ndim == 1 else int(x.shape[1])
    x = _stereo(x)
    keep, skipped = segments(x, sr, wins, bar_s)
    out = {"sr": int(sr), "duration_s": len(x) / sr, "bar_s": bar_s, "windows": {}, "skipped": skipped}
    for name, ((a, b), seg) in keep.items():
        lufs = L.integrated(seg, sr)
        if not np.isfinite(lufs):
            skipped[name] = "silent (below the -70 LUFS gate)"
            continue
        tp = window_true_peak(x, sr, int(round(a * sr)), int(round(a * sr)) + len(seg))
        bands, regions = spectral(seg, sr, lufs)
        tc = D.transient_contrast(seg, sr)
        out["windows"][name] = {
            "span_s": [a, b], "clipped": bool(abs(a - wins[name][0]) > 1e-6 or abs(b - wins[name][1]) > 1e-6),
            "lufs": float(lufs), "true_peak_db": float(tp), "plr_db": float(tp - lufs),
            "bands": bands, "regions": regions, "side_minus_mid_db": side_minus_mid(seg, sr),
            "block_crest_median_db": D.micro(seg, sr).get("block_crest_median_db"),
            "transient_contrast_median_db": tc.get("transient_contrast_median_db"),
            "onsets": tc.get("onsets"),
        }
    w = out["windows"]
    out["contrast_lu"] = float(w["drop"]["lufs"] - w["build"]["lufs"]) if "drop" in w and "build" in w else None
    out["channels"] = chans
    return out


# ------------------------------------------------------------------ references
def load_refs(path, set_name=None, base_dir=None):
    """Entries of refs.json ({"refs": [{"id", "title", "file", "drop", "barSeconds", "bpm", "set"}]}).
    `file` is relative to the JSON's folder unless base_dir is given. Adds `path` and `bar_s`."""
    with open(path) as fh:
        data = json.load(fh)
    base = base_dir or os.path.dirname(os.path.abspath(path))
    out = []
    for r in data.get("refs", []):
        if set_name and r.get("set") != set_name:
            continue
        out.append({**r, "path": os.path.join(base, r["file"]), "drop": float(r["drop"]),
                    "bar_s": float(r["barSeconds"])})
    return out


def profile_ref(ref, layout=None):
    """profile() of one load_refs() entry, on its own drop and bar."""
    from . import io as aio
    au = aio.load(ref["path"])
    return profile(au.x, au.sr, windows(ref["drop"], ref["bar_s"], layout), ref["bar_s"])


def _stats(values):
    v = {k: float(x) for k, x in values.items() if x is not None and np.isfinite(x)}
    if not v:
        return None
    a = np.array(list(v.values()))
    return {"mean": float(a.mean()), "min": float(a.min()), "max": float(a.max()), "n": len(v), "values": v}


def _hz(c):
    return round(float(c), 1)


def ref_stats(ref_profs):
    """The references' mean (of dB values), min, max and values for everything profile() reports."""
    names = []
    for p in ref_profs.values():
        names += [w for w in p["windows"] if w not in names]
    out = {"refs": list(ref_profs), "windows": {}}
    for w in names:
        have = {i: p["windows"][w] for i, p in ref_profs.items() if w in p["windows"]}
        per = {i: {_hz(c): v for c, v in pw["bands"]} for i, pw in have.items()}
        hz = sorted({c for d in per.values() for c in d})
        bands = []
        for c in hz:
            st = _stats({i: d.get(c) for i, d in per.items()})
            if st:
                bands.append({"hz": c, **st})
        out["windows"][w] = {
            "n_refs": len(have), "bands": bands,
            "regions": {k: _stats({i: pw["regions"].get(k) for i, pw in have.items()}) for k in REGION_KEYS},
            "side_minus_mid_db": {k: _stats({i: pw["side_minus_mid_db"].get(k) for i, pw in have.items()})
                                  for k in SM_KEYS},
            "scalars": {k: _stats({i: pw.get(k) for i, pw in have.items()}) for k in SCALARS},
        }
    out["contrast_lu"] = _stats({i: p.get("contrast_lu") for i, p in ref_profs.items()})
    return out


def gap(mix, st):
    """mix vs one statistic: diff = mix - mean; outside = 0 inside [min, max], else the signed
    distance to the nearest edge (negative = under the references)."""
    if mix is None or st is None or not np.isfinite(mix):
        return None
    lo, hi = st["min"], st["max"]
    out = mix - hi if mix > hi else (mix - lo if mix < lo else 0.0)
    return {"mix": float(mix), "mean": st["mean"], "min": lo, "max": hi, "diff": float(mix - st["mean"]),
            "outside": float(out), "n": st["n"], "values": st["values"]}


def in_score(hz):
    return SCORE_HZ[0] / 1.06 <= hz <= SCORE_HZ[1] * 1.06


def score(bands):
    """RMS of outside and of diff over the bands of SCORE_HZ (31.5 Hz-16 kHz)."""
    sc = [b for b in bands if in_score(b["hz"])]
    if not sc:
        return {"rms_outside_db": None, "rms_diff_db": None, "bands": 0}
    o = np.array([b["outside"] for b in sc])
    d = np.array([b["diff"] for b in sc])
    return {"rms_outside_db": float(np.sqrt(np.mean(o ** 2))), "rms_diff_db": float(np.sqrt(np.mean(d ** 2))),
            "bands": len(sc)}


def gaps(mix_prof, ref_profs):
    """The mix against the references, per window present in both (see gap())."""
    rs = ref_stats(ref_profs)
    res = {"refs": rs["refs"], "windows": {}}
    for w, mw in mix_prof["windows"].items():
        R = rs["windows"].get(w)
        if not R:
            continue
        rb = {b["hz"]: b for b in R["bands"]}
        bands = [{"hz": _hz(c), **g} for c, v in mw["bands"] if (g := gap(v, rb.get(_hz(c))))]
        res["windows"][w] = {
            "n_refs": R["n_refs"], "bands": bands,
            "regions": {k: gap(mw["regions"].get(k), R["regions"][k]) for k in REGION_KEYS},
            "side_minus_mid_db": {k: gap(mw["side_minus_mid_db"].get(k), R["side_minus_mid_db"][k]) for k in SM_KEYS},
            "scalars": {k: gap(mw.get(k), R["scalars"][k]) for k in SCALARS},
            "score": score(bands),
        }
    res["contrast_lu"] = gap(mix_prof.get("contrast_lu"), rs["contrast_lu"])
    return res
