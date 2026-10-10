"""Publish /skrng batches 7.1-7.6: six Live versions of each batch 6 aspect, titled against the references.

  uv run --with librosa python spikes/hw002_mixclimb/publish7.py [--upload]

Reads the sweeps rendered by zpkt hands/archive/probe_pack/sweep_live.py (~/_agent_scratch/probepack/
sweep7/<aspect>/): 32 Live renders of the drop, pattern 0 = the set as mixed. Picks six versions: the
original and five spread along the sweep, one of them the closest to the references. Each track is one
version, 7 bars (first bar dropped), at -14 LUFS. Each title places the aspect's two main features against
the references' range (min to max over the four Bandcamp references, measured the same way).
"""
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

import climb as K  # the spike's own modules, beside this script
import features as F
import publish as P5  # at, announce, SHOW
import publish6 as P6  # human, changes, upload, NAME, SLUG, ORDER

DATA = P6.DATA
SITE = P6.SITE
OUT = DATA + "publish7/"
P5.OUT = OUT
UP = "--upload" in sys.argv
DATE, N_VERSIONS = "2026-10-06", 6
TITLE = {  # aspect: the two features its titles report
    "kick_distortion": ["third_octave_rel.1995.3", "block_crest_median_db"],
    "density": ["block_crest_median_db", "transient_contrast_db"],
    "deep_sub": ["third_octave_rel.31.6", "third_octave_rel.39.8"],
    "mono_low": ["corr.20-120", "side_mid.20-120"],
    "colour": ["third_octave_rel.1995.3", "ears.centroid_hz"],
    "space": ["side_mid.500-2000", "side_mid.8000-20000"],   # in the drop, 2-8 kHz is already in range
}
SHORT = {"third_octave_rel.1995.3": "2 kHz", "block_crest_median_db": "crest", "transient_contrast_db": "transients",
         "third_octave_rel.31.6": "31.5 Hz", "third_octave_rel.39.8": "40 Hz", "corr.20-120": "low-end correlation",
         "side_mid.20-120": "low-end side", "ears.centroid_hz": "centroid", "third_octave_rel.10000.0": "10 kHz",
         "corr.2000-8000": "2-8 kHz correlation", "side_mid.2000-8000": "2-8 kHz side",
         "side_mid.500-2000": "0.5-2 kHz side", "side_mid.8000-20000": "8-20 kHz side"}
SPOKEN = {"third_octave_rel.1995.3": "two kilohertz", "block_crest_median_db": "crest", "transient_contrast_db": "transients",
          "third_octave_rel.31.6": "thirty one hertz", "third_octave_rel.39.8": "forty hertz", "corr.20-120": "low end correlation",
          "side_mid.20-120": "low end side", "ears.centroid_hz": "centroid", "third_octave_rel.10000.0": "ten kilohertz",
          "corr.2000-8000": "high correlation", "side_mid.2000-8000": "high side",
          "side_mid.500-2000": "mid side", "side_mid.8000-20000": "air side"}
FMT = {k: fmt for fs in P5.SHOW.values() for k, _, fmt in fs} | {"side_mid.500-2000": "{:.1f} dB", "side_mid.8000-20000": "{:.1f} dB"}
LABEL = {k: lab for fs in P5.SHOW.values() for k, lab, _ in fs} | {"side_mid.500-2000": "0.5-2 kHz side", "side_mid.8000-20000": "8-20 kHz side"}
SWEEP = {  # what sweep_live.py turns when the aspect's climb found nothing (its "primary" mode)
    "kick_distortion": "Decapitator drive on rumble and COLDFIRE drive on the kick group, together from 0 to 100%",
    "density": "the kick group Compressor, threshold from 0 to -30 dB while the ratio goes from 1.5:1 to 12:1",
    "deep_sub": "the three low EQ Eight bands (two on the kick group, one on rumble), together from -15 to +6 dB",
    "mono_low": "the Utility width on rumble, from 120% down to 0% (mono)",
    "colour": "a tilt on the kick group, perc 2 and rumble EQ Eights: mid bands from -6 to +12 dB while high bands go from +6 to -12 dB",
    "space": "Supermassive mix on perc 2, from 0 to 90%",
}


def rel(k, v, tg, first=True):
    """'2 kHz 3.1 dB under the references' / 'crest in range'."""
    lo, hi = tg[k]["min"], tg[k]["max"]
    if v is None:
        return f"{SHORT[k]} not measurable"
    if lo <= v <= hi:
        return f"{SHORT[k]} within the references' range" if first else f"{SHORT[k]} in range"
    side = "under" if v < lo else "over"
    return f"{SHORT[k]} {FMT[k].format(lo - v if v < lo else v - hi)} {side}" + (" the references" if first else "")


def spoken(k, v, tg):
    lo, hi = tg[k]["min"], tg[k]["max"]
    if v is None:
        return ""
    if lo <= v <= hi:
        return f"{SPOKEN[k]}, in range."
    d = lo - v if v < lo else v - hi
    unit = FMT[k].split("}")[1].strip()
    amount = {"dB": f"{d:.0f} decibels", "Hz": f"{d:.0f} hertz"}.get(unit, f"{d:.2f}")
    return f"{SPOKEN[k]}, {amount} {'under' if v < lo else 'over'}."


def single_file(x, sr, path):
    x = P5.at(x, sr)
    peak = np.max(np.abs(x))
    if peak > 0.89:
        x = x * 0.89 / peak
    fade = np.linspace(0, 1, int(0.01 * sr))[:, None]
    x[:len(fade)] *= fade
    x[-len(fade):] *= fade[::-1]
    wav = path[:-4] + ".wav"
    sf.write(wav, x.astype(np.float32), sr, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-b:a", "192k", path], check=True)
    return round(len(x) / sr, 1)


def pick(feats, aspect, tg):
    """Pattern indices: 0 (original) + five spread along the sweep, one of them the closest to the references."""
    n = len(feats)
    idx = list(np.linspace(1, n - 1, N_VERSIONS - 1).round().astype(int))
    d = [sum(K.dist(k, feats[j].get(k), tg) for k in TITLE[aspect]) for j in range(n)]
    best = int(np.argmin(d[1:])) + 1
    if best not in idx:
        idx[int(np.argmin([abs(j - best) for j in idx]))] = best
    return [0] + sorted(set(idx)), best


def main():
    os.makedirs(OUT, exist_ok=True)
    tg = json.load(open(os.path.expanduser("~/_agent_scratch/mixclimb/targets.json")))["targets"]
    entries, uploads, batches = [], [], []
    for i, a in enumerate(P6.ORDER, 1):
        d = DATA + f"sweep7/{a}/"
        if not os.path.exists(d + "sweep.json"):
            continue
        sw = json.load(open(d + "sweep.json"))
        parts = [P6.load_part(d + f"pattern_{j:02d}.wav") for j in range(len(sw["params"]))]
        sr = parts[0][1]
        feats = [F.flat(F.measure(x, sr)) for x, _ in parts]
        chosen, closest = pick(feats, a, tg)
        n = round(7 + i / 10, 1)
        for v, j in enumerate(chosen, 1):
            f = feats[j]
            k1, k2 = TITLE[a]
            orig = j == 0
            eid = f"{DATE}-hw002-b7-{i}-{P6.SLUG[a]}-{sw['made']}-v{v}"
            mp3 = OUT + eid + ".mp3"
            dur = single_file(parts[j][0].copy(), sr, mp3)
            if orig:
                what = "The set as mixed."
            elif sw["mode"] == "path":
                what = (f"{sw['t'][j]:.2f} times the change the batch 6 climb found (1.00 is its best): "
                        + "; ".join(P6.changes(a, sw["params"][j])) + ".")
            else:
                what = "Changed: " + "; ".join(P6.changes(a, sw["params"][j])) + "."
            meas = " ".join(f"{LABEL[k][0].upper() + LABEL[k][1:]} {FMT[k].format(f[k])} (references {FMT[k].format(tg[k]['min'])} to {FMT[k].format(tg[k]['max'])})."
                            for k in TITLE[a] + [k for k, _, _ in P5.SHOW[a] if k not in TITLE[a]] if f.get(k) is not None)
            close = " Closest of the sweep to the references." if j == closest else ""
            e = {"id": eid, "batch": n,
                 "title": f"HW002 — {P6.NAME[a]} {v}{' (original)' if orig else ''}: {rel(k1, f[k1], tg)}, {rel(k2, f[k2], tg, first=False)}",
                 "date": DATE, "file": f"/audio/skrng/{eid}.mp3", "duration_s": dur, "bpm": 160,
                 "notes": f"{what}{close} Measured at -14 LUFS: {meas} 7 bars of the drop, rendered in Live (sweep pattern {j}). Unmastered.",
                 "announce": None}
            say = f"{P6.NAME[a]}, {P6.NUM[v - 1]}{', the original' if orig else ''}. {spoken(k1, f[k1], tg)}"
            e["announce"] = f"/audio/skrng/tts/{eid}-{hashlib.md5(say.encode()).hexdigest()[:6]}.mp3"   # new words, new URL
            uploads += [(e["file"], mp3), (e["announce"], P5.announce(eid, say))]
            entries.append(e)
        ranges = "; ".join(f"{LABEL[k]} {FMT[k].format(tg[k]['min'])} to {FMT[k].format(tg[k]['max'])}" for k in TITLE[a])
        how = (SWEEP[a] if sw["mode"] == "primary" else
               "the original moved along the change the batch 6 climb found, past its best to 2.5 times the change")
        lo, hi = chosen[1], chosen[-1]
        trend = "; ".join(f"{LABEL[k]} {FMT[k].format(feats[lo][k])} to {FMT[k].format(feats[hi][k])}"
                          for k in TITLE[a] if feats[lo].get(k) is not None and feats[hi].get(k) is not None)
        c = P6.climb(a)
        if c and c["win"]:
            climbed = " The batch 6 climb's best version is in batch 6."
        elif c and c["done"]:
            climbed = (f" The batch 6 climb ({c['state']['attempt']} rounds of 31 settings) found no setting "
                       "nearer the references than the original, beyond the measurement noise.")
        else:
            climbed = ""
        batches.append({"n": n, "title": f"Batch 7.{i} — {P6.NAME[a]}: {len(chosen)} versions against the references (6 Oct)",
                        "notes": (f"{len(chosen)} versions of the drop, rendered in Live: the original, then {how}. "
                                  f"Titles place each version against the four Bandcamp references, measured the same way at -14 LUFS "
                                  f"({ranges}). Under and over are distances outside that range. Each version is at -14 LUFS. "
                                  f"From the first to the last version of the sweep: {trend}.{climbed}"),
                        "ordered": True})
    if UP:
        P6.upload(uploads, OUT)
    ns = {b["n"] for b in batches}
    m = [e for e in json.load(open(SITE + "manifest.json")) if e.get("batch") not in ns]
    json.dump(entries + m, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "manifest.json", "a").write("\n")
    bt = [x for x in json.load(open(SITE + "batches.json")) if x["n"] not in ns] + batches
    json.dump(sorted(bt, key=lambda x: x["n"]), open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "batches.json", "a").write("\n")
    print(json.dumps({"batches": sorted(ns), "entries": [e["title"] for e in entries], "uploaded": UP}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
