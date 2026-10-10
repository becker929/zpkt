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
SWEEPS = os.path.expanduser("~/_agent_scratch/probepack/sweep8/")   # hands/scripts/probe_pack/sweep8.py
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
    # Batches 8.2-8.4 (9 Oct): the chord loop under the intro, peak and outro, which Anthony wants more
    # prominent. Rendered by sweep8.py (pattern 0 the baseline, 1-3 the alternatives, Main only).
    "b8_2_chord_level": {
        "n": 8.2, "slug": "chord-level", "date": "2026-10-09", "src": "sweep8",
        "title": "Batch 8.2 — The chord loop up 4, 8 and 12 dB, on batch 6's mix (9 Oct)",
        "notes": ("The processed synth chord loop that plays under the intro, the peak and the outro sits about 21 LU under "
                  "the rest of the mix. It was muted in every batch since 4.3. Here it is back, at its level in the song "
                  "(the baseline) and raised 4, 8 and 12 dB with its own Utility: 17, 13 and 10 LU under the rest. "
                  "Level only, no colour. Tracks 1 to 3 switch every 2 bars, the louder chord first. Track 4 goes round."),
        "intro": ("Batch 8, part 2. The chord loop. It plays under the intro, the peak and the outro, and it sits far "
                  "under the drums. Three levels: up 4, 8 and 12 decibels. Each track starts with the louder chord, "
                  "then switches back to the mix as it is, every 2 bars. Track 4 goes round: the mix as it is, then all three."),
        "alts": ["chord up 4 dB", "chord up 8 dB", "chord up 12 dB"],
        "round": "round: baseline, up 4, up 8, up 12",
    },
    "b8_3_chord_colour": {
        "n": 8.3, "slug": "chord-colour", "date": "2026-10-09", "src": "sweep8",
        "title": "Batch 8.3 — The chord loop's colour through COLDFIRE, with the chord up 8 dB (9 Oct)",
        "notes": ("Colour is only heard once the chord is up, so the baseline here is batch 6's mix with the chord loop "
                  "8 dB up (batch 8.2, track 2). The alternatives switch on the chord's own COLDFIRE (Shine Bright: "
                  "tube into transformer, it was bypassed inside the plugin) and turn its Colour to 0.5, 0.75 and 1. "
                  "Its top octaves rise 4, 6 and 9 dB. Every version keeps the chord at the same loudness (within 0.2 LU), "
                  "so only the colour changes. Measured in the full mix, the top octaves move under 0.5 dB: the hats still cover "
                  "the chord's top, so this one may be subtle. Tracks 1 to 3 switch every 2 bars, the colour first. Track 4 goes round."),
        "intro": ("Batch 8, part 3. The chord loop's colour. The chord is 8 decibels up in every version. Its own COLDFIRE "
                  "distortion comes on, with three amounts of colour, each at the same loudness. Each track starts with "
                  "the colour, then switches back, every 2 bars. Track 4 goes round."),
        "alts": ["colour 0.5", "colour 0.75", "colour 1"],
        "round": "round: chord up 8 dB, colour 0.5, 0.75, 1",
    },
    "b8_4_chord_width": {
        "n": 8.4, "slug": "chord-width", "date": "2026-10-09", "src": "sweep8",
        "title": "Batch 8.4 — The chord loop's width, 50, 100 and 150%, with the chord up 8 dB (9 Oct)",
        "notes": ("The chord loop's Utility narrows it to 10% width, so it sits in the middle with the kick and the rumble. "
                  "The baseline is batch 6's mix with the chord 8 dB up. The alternatives widen it to 50, 100 and 150%, "
                  "each at the same chord loudness (within 0.2 LU): wider, not louder. Tracks 1 to 3 switch every 2 bars, "
                  "the wider chord first. Track 4 goes round."),
        "intro": ("Batch 8, part 4. The chord loop's width. It is nearly mono in the set. The chord is 8 decibels up in "
                  "every version. Three widths: 50, 100 and 150 percent, each at the same loudness. Each track starts "
                  "wide, then switches back, every 2 bars. Track 4 goes round."),
        "alts": ["width 50%", "width 100%", "width 150%"],
        "round": "round: chord up 8 dB, width 50, 100, 150%",
    },
    "b8_5_chord_texture": {
        "n": 8.5, "slug": "chord-texture", "date": "2026-10-09", "src": "sweep8",
        "title": "Batch 8.5 — The chord loop's texture: its Supermassive short and tight, with the chord up 8 dB (9 Oct)",
        "notes": ("Anthony asked for the chord's Supermassive short and tight, to change texture and frequency rather than "
                  "add space. Short delay (0.1), low feedback (0.2), low cut 0.3; Mix 0.3, 0.55 and 0.8. The baseline is "
                  "batch 6's mix with the chord 8 dB up; every version keeps the chord at the same loudness (within "
                  "0.3 LU). At Mix 0.8 the chord's low mids drop about 2 dB and its top rises about 2 dB. "
                  "Tracks 1 to 3 switch every 2 bars, the texture first. Track 4 goes round."),
        "intro": ("Batch 8, part 5. The chord loop's texture. The chord is 8 decibels up in every version. Its own "
                  "Supermassive comes on, short and tight, at three amounts, each at the same loudness. Each track "
                  "starts with the texture, then switches back, every 2 bars. Track 4 goes round."),
        "alts": ["supermassive mix 0.3", "supermassive mix 0.55", "supermassive mix 0.8"],
        "round": "round: chord up 8 dB, mix 0.3, 0.55, 0.8",
    },
    "b8_6_break_space": {
        "n": 8.6, "slug": "break-space", "date": "2026-10-09", "src": "sweep8",
        "title": "Batch 8.6 — Space in the break: the Break group's reverb at 70, 80 and 90% wet (9 Oct)",
        "notes": ("The break (bars 81-88: the synths, the horn and the beatbox) on batch 6's mix. Its group reverb "
                  "(Hybrid: Prism with a Textures convolution in parallel) is 50% wet in the set; here 70, 80 and 90%. "
                  "Same loudness; wetter takes 3-5 dB off the lows and the top and keeps the mids. "
                  "Tracks 1 to 3 switch every 2 bars, the wetter break first. Track 4 goes round."),
        "intro": ("Batch 8, part 6. Space in the break. The break's group reverb, wetter: 70, 80 and 90 percent, "
                  "against 50 in the set. Each track starts wetter, then switches back, every 2 bars. Track 4 goes round."),
        "alts": ["reverb 70% wet", "reverb 80% wet", "reverb 90% wet"],
        "round": "round: 50% wet, then 70, 80, 90",
    },
    "b8_7_break_colour": {
        "n": 8.7, "slug": "break-colour", "date": "2026-10-09", "src": "sweep8",
        "title": "Batch 8.7 — Colour in the break: the Break group's COLDFIRE Colour, dark to bright (9 Oct)",
        "notes": ("The break on batch 6's mix. The Break group's COLDFIRE (wavefolder) has Colour at 0.7 in the set. "
                  "Here 0.3 and 0.5, darker (the top 4 and 2 dB down, the lows up), and 1.0, brighter (the top 3 dB up). "
                  "Every version at the same loudness. Tracks 1 to 3 switch every 2 bars, the new colour first. "
                  "Track 4 goes round."),
        "intro": ("Batch 8, part 7. Colour in the break. The break's COLDFIRE colour: two darker, then one brighter. "
                  "Each track starts with the new colour, then switches back, every 2 bars. Track 4 goes round."),
        "alts": ["colour 0.3, darker", "colour 0.5, a little darker", "colour 1, brighter"],
        "round": "round: as set, 0.3, 0.5, 1",
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
    date = sp.get("date", DATE)
    if sp.get("src") == "sweep8":
        parts = [load(SWEEPS + name + f"/mix/pattern_{k:02d}.wav") for k in range(4)]
    else:
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
    labels = sp["alts"] + [sp.get("round") or "round: baseline, " + ", ".join(a.replace("drive ", "") for a in sp["alts"])]
    tag = str(sp["n"]).replace(".", "-")
    entries, uploads = [], []
    for i, (pieces, label) in enumerate(zip(tracks, labels), 1):
        eid = f"{date}-hw002-b{tag}-{sp['slug']}-t{i}"
        mp3, dur = write(assemble(pieces, sr), sr, eid)
        e = {"id": eid, "title": f"HW002 — Track {i}: {label}", "date": date, "file": f"/audio/skrng/{eid}.mp3",
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
