"""Publish /skrng batch 6: the batch 5 aspects, made in Live with the set's own devices.

  uv run --with librosa python spikes/hw002_mixclimb/publish6.py [--upload]

Reads the Live hill climbs in ~/_agent_scratch/probepack/climb_b6_<aspect>/ (climb_live.py).
Each track: the original and the best version, both rendered by Live (8-bar kit patterns),
first bar dropped (the previous pattern's tail rings into it), both halves at -14 LUFS.
An aspect whose climb never beat the original by more than the measured noise gets no track;
the batch notes say so. Writes the site checkout's skrng manifest.json and batches.json.
"""
import json
import math
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402
import publish as P5  # noqa: E402  (ab_file, announce, cut-free helpers from batch 5)
from mlab import loudness as L  # noqa: E402

DATA = os.path.expanduser("~/_agent_scratch/probepack/")
SITE = os.environ.get("SKRNG_SITE", os.path.expanduser("~/_agent_scratch/site")) + "/skrng/"
OUT = DATA + "publish6/"
P5.OUT = OUT
UP = "--upload" in sys.argv
DATE, BATCH, PATIENCE = "2026-10-06", 6, 3
ORDER = ["kick_distortion", "density", "deep_sub", "mono_low", "colour", "space"]
NAME = {"kick_distortion": "Kick distortion", "density": "Drop power", "deep_sub": "Deep sub",
        "mono_low": "Mono low end", "colour": "Colour", "space": "Space"}
SLUG = {"kick_distortion": "kick-distortion", "density": "drop-power", "deep_sub": "deep-sub",
        "mono_low": "mono-low-end", "colour": "colour", "space": "space"}
NUM = ["one", "two", "three", "four", "five", "six", "seven"]
NEUTRAL = json.load(open(DATA + "b6_neutral_params.json"))


def human(key, v):
    """'track/device/param' + value -> readable text."""
    track, dev, param = key.split("/", 2)
    p = param.split("/")[-1]
    eq = "second EQ Eight" if dev == "1" else "EQ Eight"
    if dev in ("Decapitator", "Dist COLDFIRE", "ValhallaSupermassive"):
        return f"{dev} on {track}: {param} {v * 100:.0f}%"
    if p == "Freq":
        return f"{eq} on {track}, band {int(param.split('.')[1][0]) + 1}: {v:.0f} Hz"
    if p == "Gain" and param.startswith("Bands"):
        return f"{eq} on {track}, band {int(param.split('.')[1][0]) + 1}: {v:+.1f} dB"
    if p == "Threshold":
        return f"Compressor on {track}: threshold {20 * math.log10(max(v, 1e-6)):.1f} dB"
    if p == "Ratio":
        return f"Compressor on {track}: ratio {v:.1f}:1"
    if p in ("Attack", "Release"):
        return f"Compressor on {track}: {p.lower()} {v:.2f} ms"
    if p == "Gain":
        return f"Compressor on {track}: makeup {v:+.1f} dB"
    if p == "DryWet":
        return f"Compressor on {track}: dry/wet {v * 100:.0f}%"
    if p == "BassMono":
        return f"Utility on {track}: Bass Mono {'on' if v else 'off'}"
    if p == "BassMonoFrequency":
        return f"Utility on {track}: Bass Mono below {v:.0f} Hz"
    if p == "StereoWidth":
        return f"Utility on {track}: width {v * 100:.0f}%"
    return f"{track} {dev} {param}: {v}"


def changes(aspect, params):
    """['Device on track: param before → after', ...] for the knobs that differ from the set."""
    before = NEUTRAL[aspect]                 # the set's own values (written from the kit template)
    out = []
    for k, v in params.items():
        if isinstance(v, bool) and v == before[k] or not isinstance(v, bool) and abs(v - before[k]) <= 1e-6 * max(1, abs(before[k])):
            continue
        if human(k, before[k]) == human(k, v):
            continue                     # a change too small to show at this precision
        b, a = human(k, before[k]).split(" "), human(k, v).split(": ", 1)[1].split(" ")
        n = len(b) - len(a)              # skip the words the after-value repeats ("Drive 27% → 0%")
        while n < len(b) - 1 and a[0] == b[n]:
            a, n = a[1:], n + 1
        out.append(f"{' '.join(b)} → {' '.join(a)}")
    return out


def upload(uploads, out=None):
    """[(site key, local mp3)] -> R2, skipping keys already uploaded (registry in out/uploaded.json)."""
    reg_path = (out or OUT) + "uploaded.json"
    reg = set(json.load(open(reg_path))) if os.path.exists(reg_path) else set()
    for key, path in uploads:
        if key in reg:
            continue
        r = subprocess.run(["npx", "-y", "wrangler@4.145.0", "r2", "object", "put", f"anthonybecker-audio/{key.lstrip('/')}",
                            "--file", path, "--content-type", "audio/mpeg", "--remote"],
                           cwd=os.path.expanduser("~/Desktop/zpkt"), capture_output=True, text=True)
        print(("up " if r.returncode == 0 else "FAIL ") + key, flush=True)
        if r.returncode == 0:
            reg.add(key)
    json.dump(sorted(reg), open(reg_path, "w"))


def climb(aspect):
    d = DATA + f"climb_b6_{aspect}/"
    if not os.path.exists(d + "state.json"):
        return None
    st = json.load(open(d + "state.json"))
    h = st["history"]
    if not h:
        return None
    wins = [x for x in h if x["improved"]]
    first = h[0]
    return {"dir": d, "state": st, "done": st["misses"] >= PATIENCE, "win": wins[-1] if wins else None, "first": first}


def load_part(path):
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    return x[int(1.5 * sr):], sr                      # drop the first bar


def main():
    os.makedirs(OUT, exist_ok=True)
    tg = json.load(open(os.path.expanduser("~/_agent_scratch/mixclimb/targets.json")))["targets"]
    entries, uploads, skipped, done = [], [], [], []
    for i, a in enumerate(ORDER, 1):
        c = climb(a)
        if c is None:
            continue
        if c["done"]:
            done.append(a)
        if c["win"] is None:
            if c["done"]:
                skipped.append(NAME[a])
            continue
        w = c["win"]
        orig, sr = load_part(c["dir"] + "a000/pattern_00.wav")
        best, _ = load_part(c["dir"] + f"a{w['attempt']:03d}/pattern_{w['top_pattern']:02d}.wav")
        n = min(len(orig), len(best))
        fo, fb = F.flat(F.measure(orig[:n], sr)), F.flat(F.measure(best[:n], sr))
        lines = [f"{lab[0].upper() + lab[1:]}: {fmt.format(fo[k])} to {fmt.format(fb[k])} (references {fmt.format(tg[k]['min'])} to {fmt.format(tg[k]['max'])})."
                 for k, lab, fmt in P5.SHOW[a]]
        status = f"Plateaued after {c['state']['attempt']} rounds." if c["done"] else "Still climbing."
        eid = f"{DATE}-hw002-b6-{i:02d}-{SLUG[a]}-r{w['attempt']}"
        mp3 = OUT + eid + ".mp3"
        dur = P5.ab_file(orig[:n].copy(), best[:n].copy(), sr, mp3)
        notes = ("The drop of the canonical shape, 7 bars: first as mixed, then with the change. Both rendered in Live; "
                 "both halves at -14 LUFS. Changed: " + "; ".join(changes(a, w["params"])) + ". " + " ".join(lines) +
                 f" Score {w['best']:.2f} (original {c['first']['control']:.2f}), found in round {w['attempt'] + 1}. {status} Unmastered.")
        e = {"id": eid, "batch": BATCH, "title": f"HW002 — {NAME[a]}, in Live: before and after, {int(dur)} s", "date": DATE,
             "file": f"/audio/skrng/{eid}.mp3", "duration_s": dur, "bpm": 160, "notes": notes,
             "announce": f"/audio/skrng/tts/{eid}.mp3"}
        uploads += [(e["file"], mp3), (e["announce"], P5.announce(eid, f"Track {NUM[len(entries)]}. {NAME[a]}. First the original, then the new version."))]
        entries.append(e)
    cj = DATA + "climb_b6_all/combined.json"            # combine_live.py: all the bests in one Live render
    wins = [a for a in ORDER if (climb(a) or {}).get("win")]
    if len(wins) > 1 and os.path.exists(cj) and json.load(open(cj))["aspects"] == wins:
        cb = json.load(open(cj))
        orig, sr = load_part(DATA + "climb_b6_all/pattern_00.wav")
        both, _ = load_part(DATA + "climb_b6_all/pattern_01.wav")
        n = min(len(orig), len(both))
        fo, fb = F.flat(F.measure(orig[:n], sr)), F.flat(F.measure(both[:n], sr))
        lines = [f"{lab[0].upper() + lab[1:]}: {fmt.format(fo[k])} to {fmt.format(fb[k])} (references {fmt.format(tg[k]['min'])} to {fmt.format(tg[k]['max'])})."
                 for a in wins for k, lab, fmt in P5.SHOW[a][:1]]
        eid = f"{DATE}-hw002-b6-07-all-{'-'.join(SLUG[a] for a in wins)}"
        mp3 = OUT + eid + ".mp3"
        dur = P5.ab_file(orig[:n].copy(), both[:n].copy(), sr, mp3)
        e = {"id": eid, "batch": BATCH, "title": f"HW002 — All {len(wins)} changes together, in Live: before and after, {int(dur)} s",
             "date": DATE, "file": f"/audio/skrng/{eid}.mp3", "duration_s": dur, "bpm": 160,
             "notes": ("The drop as mixed, then with every change above at once (" + ", ".join(NAME[a].lower() for a in wins) +
                       "), rendered together in Live. Both halves at -14 LUFS. Changed: " +
                       "; ".join(x for a in wins for x in changes(a, cb["params"][a])) + ". " + " ".join(lines) + " Unmastered."),
             "announce": f"/audio/skrng/tts/{eid}.mp3"}
        uploads += [(e["file"], mp3), (e["announce"], P5.announce(eid, f"Track {NUM[len(entries)]}. All the changes together. First the original, then the new version."))]
        entries.append(e)
    if UP:
        upload(uploads)
    m = [e for e in json.load(open(SITE + "manifest.json")) if e.get("batch") != BATCH]
    json.dump(entries + m, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "manifest.json", "a").write("\n")
    all_done = len(done) == len(ORDER)
    notes = ("The batch 5 changes again, made in Live with the devices already in the set: Decapitator, COLDFIRE, "
             "the Compressor, EQ Eights, Utility and Supermassive. Each track plays the drop twice, as mixed and changed. "
             "A program tuned each change toward the four Bandcamp references, 32 Live renders at a time.")
    if skipped:
        notes += " No setting beat the original for: " + ", ".join(skipped) + "."
    notes += " All aspects have stopped; these are final." if all_done else " This page updates as each aspect finishes."
    bt = [x for x in json.load(open(SITE + "batches.json")) if x["n"] != BATCH]
    bt.append({"n": BATCH, "title": "Batch 6 — the six mix changes, made in Live (6 Oct)", "notes": notes, "ordered": True})
    json.dump(sorted(bt, key=lambda x: x["n"]), open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "batches.json", "a").write("\n")
    print(json.dumps({"entries": [e["id"] for e in entries], "skipped": skipped, "done": done, "uploaded": UP}))


if __name__ == "__main__":
    main()
