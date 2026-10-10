"""Publish a /skrng batch 8 experiment: three alternatives, A/B inside each track.

  uv run --with librosa --with pedalboard python spikes/hw002_mixclimb/publish8.py kick_distortion [--upload]

Reads one experiment rendered in Live by zpkt hands/scripts/probe_pack/ab_live.py
(~/_agent_scratch/probepack/ab8/<experiment>/): pattern 0 is the baseline (batch 6 "all"),
patterns 1-3 the alternatives at the low end, centre and high end of a target range.
The format follows Anthony's review of batches 6 and 7 (zpkt docs/hw002/batch-6-7-decisions.md):

- Tracks 1-3: one alternative against the baseline, switching every 2 bars, the
  alternative first ("on, off, on, off"), 16 bars.
- Track 4: round robin, the baseline then each alternative in turn, 2 bars each, 16 bars.
- The experiment is said once in the batch intro; each track is announced as "Track N".

Each pattern's first bar is dropped (it carries the previous pattern's tail), and the 2-bar
pieces come from bars 2-7 in turn, so every version is heard at more than one place in the
loop. Every version is at -14 LUFS, joins are 10 ms crossfades, peaks are kept under -1 dBFS.
Writes the site checkout's skrng manifest.json and batches.json; --upload sends the audio to R2.
"""
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish as P5  # noqa: E402  (at, announce)
import publish6 as P6  # noqa: E402  (upload, SITE)

sys.path.insert(0, os.path.expanduser("~/Desktop/zpkt/lib/record"))
import batch_intro as BI  # noqa: E402

DATA = os.path.expanduser("~/_agent_scratch/probepack/ab8/")
OUT = os.path.expanduser("~/_agent_scratch/mixclimb/publish8/")
P5.OUT = OUT
SITE = P6.SITE
UP = "--upload" in sys.argv
DATE = "2026-10-07"
BAR = 1.5          # seconds at 160 BPM
PIECES = [0, 2, 4]  # 2-bar pieces: bars 2-3, 4-5 and 6-7 (index 0 is bar 2 once bar 1 is dropped)
XF = 0.01           # crossfade, seconds

SPEC = {
    "kick_distortion": {
        "n": 8.1, "slug": "kick-distortion",
        "title": "Batch 8.1 — Kick distortion between 37% and 50%, on batch 6's mix (7 Oct)",
        "notes": ("Batch 6's mix with all four changes is now the baseline. Batch 7.1's tracks 3 and 4 were the best: "
                  "Decapitator drive on the rumble and COLDFIRE drive on the kick group, together, at 37% and 50%. "
                  "Here the two ends of that range and its middle: 37%, 43.5% and 50% (the baseline is 27% and 12%). "
                  "Tracks 1 to 3 switch every 2 bars, the new drive first, then the baseline. Track 4 goes round: "
                  "the baseline, 37%, 43.5%, 50%. Rendered in Live; every version at -14 LUFS."),
        "intro": ("Batch 8, part 1. Kick distortion. The mix now has all of batch 6's changes. "
                  "Three amounts of drive on the kick and the rumble: 37, 43 and a half, and 50 percent. "
                  "Each track starts with the new drive, then switches back to the mix as it is, every 2 bars. "
                  "Track 4 goes round: the mix as it is, then all three in turn."),
        "alts": ["drive 37%", "drive 43.5%", "drive 50%"],
    },
}


def load(path):
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    return x[int(BAR * sr):], sr       # drop the first bar


def assemble(pieces, sr):
    """[(version array, start bar)] -> one array, 2 bars per piece, 10 ms crossfades at the joins."""
    n2, xf = int(2 * BAR * sr), int(XF * sr)
    y = np.zeros((n2 * len(pieces) + xf, 2))
    ramp = np.linspace(0, 1, xf)[:, None]
    for k, (src, bar) in enumerate(pieces):
        a = int(bar * BAR * sr)
        seg = src[a:a + n2 + xf].copy()
        seg[:xf] *= ramp
        seg[-xf:] *= ramp[::-1]
        y[k * n2:k * n2 + len(seg)] += seg
    y = y[:n2 * len(pieces)]
    y[-xf:] *= ramp[::-1]
    return y


def write(y, sr, eid):
    wav, mp3 = OUT + eid + ".wav", OUT + eid + ".mp3"
    sf.write(wav, y.astype(np.float32), sr, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-b:a", "192k", mp3], check=True)
    return mp3, round(len(y) / sr, 1)


def main():
    name = sys.argv[1]
    sp = SPEC[name]
    os.makedirs(OUT, exist_ok=True)
    ab = json.load(open(DATA + name + "/ab.json"))
    order = [ab["patterns"]["baseline"]] + ab["patterns"]["alternatives"]
    parts = [load(DATA + name + f"/pattern_{k:02d}.wav") for k in order]
    sr = parts[0][1]
    vs = [P5.at(x, sr) for x, _ in parts]                          # every version at -14 LUFS
    peak = max(np.max(np.abs(v)) for v in vs)
    if peak > 0.89:
        vs = [v * 0.89 / peak for v in vs]
    base, alts = vs[0], vs[1:]
    bars = [PIECES[k % len(PIECES)] for k in range(8)]
    tracks = [[(alt if k % 2 == 0 else base, bars[k]) for k in range(8)] for alt in alts]
    tracks.append([(([base] + alts)[k % 4], bars[k]) for k in range(8)])
    labels = sp["alts"] + ["round: baseline, " + ", ".join(a.replace("drive ", "") for a in sp["alts"])]
    tag = str(sp["n"]).replace(".", "-")
    entries, uploads = [], []
    for i, (pieces, label) in enumerate(zip(tracks, labels), 1):
        eid = f"{DATE}-hw002-b{tag}-{sp['slug']}-t{i}"
        mp3, dur = write(assemble(pieces, sr), sr, eid)
        e = {"id": eid, "title": f"HW002 — Track {i}: {label}", "date": DATE, "file": f"/audio/skrng/{eid}.mp3",
             "batch": sp["n"], "bpm": 160, "duration_s": dur,
             "notes": (f"{label[:1].upper() + label[1:]} against the baseline, switching every 2 bars, the new version first."
                       if i <= 3 else "The baseline, then each alternative in turn, 2 bars each."),
             "say": label.replace("%", " percent"),
             "announce": f"/audio/skrng/tts/{eid}.mp3"}
        entries.append(e)
        uploads += [(e["file"], mp3), (e["announce"], P5.announce(eid, f"Track {i}."))]
    if UP:
        P6.upload(uploads, OUT)
    m = [e for e in json.load(open(SITE + "manifest.json")) if e.get("batch") != sp["n"]]
    json.dump(entries + m, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "manifest.json", "a").write("\n")
    bt = [x for x in json.load(open(SITE + "batches.json")) if x["n"] != sp["n"]]
    bt.append({"n": sp["n"], "title": sp["title"], "notes": sp["notes"], "ordered": True})
    bt.sort(key=lambda x: x["n"])
    if UP:
        BI.publish(os.path.dirname(SITE.rstrip("/")), bt, sp["n"], sp["intro"])
    json.dump(bt, open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "batches.json", "a").write("\n")
    print(json.dumps({"batch": sp["n"], "tracks": [(e["id"], e["duration_s"]) for e in entries], "uploaded": UP}))


if __name__ == "__main__":
    main()
