"""Publish the current best mix alternates to /skrng batch 5.

  uv run --with librosa --with pedalboard python spikes/hw002_mixclimb/publish.py [--upload]

Each track: the drop (bars 125-132) as mixed, a short gap, then the same bars with one
change. Both halves at -14 LUFS. Track 7 stacks all six changes. File names carry the
attempt that found each best, so a new best gets a new URL. Writes the site checkout's
skrng/manifest.json and batches.json (default ~/_agent_scratch/site, env SKRNG_SITE).
"""
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chains as C  # noqa: E402
import climb as K  # noqa: E402
from mlab import loudness as L  # noqa: E402

W = K.W
SITE = os.environ.get("SKRNG_SITE", os.path.expanduser("~/_agent_scratch/site")) + "/skrng/"
OUT = W + "publish/"
UP = "--upload" in sys.argv
DATE, BATCH = "2026-10-06", 5
AB = tuple(K.LAYOUT["ab"])
NUM = ["one", "two", "three", "four", "five", "six", "seven"]
ORDER = ["kick_distortion", "density", "deep_sub", "mono_low", "colour", "space"]
SLUG = {"kick_distortion": "kick-distortion", "density": "drop-power", "deep_sub": "deep-sub",
        "mono_low": "mono-low-end", "colour": "colour", "space": "space"}
SHOW = {  # aspect: [(feature, label, fmt)]
    "kick_distortion": [("third_octave_rel.1995.3", "2 kHz band", "{:.1f} dB"), ("block_crest_median_db", "peak density (block crest)", "{:.1f} dB")],
    "density": [("block_crest_median_db", "block crest", "{:.1f} dB"), ("transient_contrast_db", "transient contrast", "{:.1f} dB")],
    "deep_sub": [("third_octave_rel.31.6", "31.5 Hz band", "{:.1f} dB"), ("third_octave_rel.39.8", "40 Hz band", "{:.1f} dB")],
    "mono_low": [("corr.20-120", "low-end correlation", "{:.3f}"), ("side_mid.20-120", "low-end side", "{:.1f} dB")],
    "colour": [("third_octave_rel.1995.3", "2 kHz band", "{:.1f} dB"), ("third_octave_rel.10000.0", "10 kHz band", "{:.1f} dB"), ("ears.centroid_hz", "spectral centroid", "{:.0f} Hz")],
    "space": [("corr.2000-8000", "2-8 kHz correlation", "{:.2f}"), ("side_mid.2000-8000", "2-8 kHz side", "{:.1f} dB")],
}
PLAIN = {
    "kick_distortion": lambda p: f"Kick bus, mono, clean below {p['clean_below_hz']:.0f} Hz: {p['emphasis_db']:.1f} dB lift at {p['emphasis_hz']:.0f} Hz into {p['drive_db']:.1f} dB of drive, low-passed at {p['tone_lowpass_hz']/1000:.1f} kHz, {p['mix']*100:.0f}% blended.",
    "density": lambda p: f"Drum bus, mono part: {p['clip_drive_db']:.1f} dB into a soft clipper, plus {p['parallel_mix']*100:.0f}% parallel compression ({p['comp_ratio']:.1f}:1 at {p['comp_threshold_db']:.0f} dB, {p['comp_attack_ms']:.1f} ms attack, {p['comp_release_ms']:.0f} ms release).",
    "deep_sub": lambda p: f"Kick bus: {p['sub_db']:+.1f} dB at {p['sub_hz']:.0f} Hz (Q {p['sub_q']:.1f}), {p['upper_bass_db']:+.1f} dB at {p['upper_bass_hz']:.0f} Hz.",
    "mono_low": lambda p: f"Mix: the side signal is turned down {abs(p['side_below_db']):.0f} dB below {p['crossover_hz']:.0f} Hz.",
    "colour": lambda p: f"Mix EQ: {p['mid_db']:+.1f} dB at {p['mid_hz']:.0f} Hz (Q {p['mid_q']:.1f}), {p['lowmid_db']:+.1f} dB at {p['lowmid_hz']:.0f} Hz, high shelf {p['air_db']:+.1f} dB from {p['air_shelf_hz']/1000:.1f} kHz.",
    "space": lambda p: f"Perc bus: reverb (size {p['room_size']:.2f}, damping {p['damping']:.2f}, wet {p['reverb_wet']*100:.0f}%), side lifted {p['side_lift_db']:.1f} dB above {p['widen_above_hz']:.0f} Hz.",
}


def cut(y, sr, span, start_bar):
    return y[int((span[0] - start_bar) * K.BAR * sr):int((span[1] - start_bar + 1) * K.BAR * sr)]


def at(x, sr, lufs=-14.0):
    return x * 10 ** ((lufs - L.integrated(x, sr)) / 20)


def ab_file(a, b, sr, path):
    a, b = at(a, sr), at(b, sr)
    peak = max(np.max(np.abs(a)), np.max(np.abs(b)))
    if peak > 0.89:
        a, b = a * 0.89 / peak, b * 0.89 / peak
    fade = np.linspace(0, 1, int(0.01 * sr))[:, None]
    for z in (a, b):
        z[:len(fade)] *= fade
        z[-len(fade):] *= fade[::-1]
    y = np.concatenate([a, np.zeros((int(0.6 * sr), 2)), b])
    wav = path[:-4] + ".wav"
    sf.write(wav, y.astype(np.float32), sr, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-b:a", "192k", path], check=True)
    return round(len(y) / sr, 1)


def announce(entry_id, text):
    aiff, mp3 = OUT + entry_id + ".aiff", OUT + entry_id + "-tts.mp3"
    subprocess.run(["say", "-v", "Daniel", "-o", aiff, text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-i", aiff,
                    "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
                    "[1:a]aresample=44100,aformat=channel_layouts=stereo,silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5,aresample=44100[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]",
                    "-map", "[a]", "-b:a", "128k", mp3], check=True)
    return mp3


def status(aspect):
    d = W + f"runs/{aspect}/done.json"
    if os.path.exists(d):
        j = json.load(open(d))
        return f"Plateaued after {j['attempts']} rounds." if j["plateaued"] else f"Stopped after {j['attempts']} rounds."
    return "Still climbing."


def main():
    os.makedirs(OUT, exist_ok=True)
    stems, sr = K.load_stems((K.STEM_START, 144))
    orig = cut(C.render(stems, sr, {}), sr, AB, K.STEM_START)
    tg = json.load(open(W + "targets.json"))["targets"]
    bests = {a: json.load(open(W + f"runs/{a}/best.json")) for a in ORDER if os.path.exists(W + f"runs/{a}/best.json")}
    bests = {a: b for a, b in bests.items() if b["attempt"] > 0}   # nothing to hear until an aspect beats the original
    entries, uploads = [], []
    for i, a in enumerate(ORDER + ["all"], 1):
        if a == "all":
            if len(bests) < 2:
                continue
            choices = {k: np.array(v["u"]) for k, v in bests.items()}
            rev = "-".join(str(bests[k]["attempt"]) for k in ORDER if k in bests)
            name, slug = "All six together", "all-six"
            feat = K.measure_render(K.load_stems(K.PROC)[0], sr, choices)[0]
            base = next(iter(bests.values()))["baseline_features"]
            lines = [f"{lab}: {fmt.format(base[k])} to {fmt.format(feat[k])} (references {fmt.format(tg[k]['min'])} to {fmt.format(tg[k]['max'])})."
                     for k, lab, fmt in [("block_crest_median_db", "Block crest", "{:.1f} dB"), ("third_octave_rel.1995.3", "2 kHz band", "{:.1f} dB"),
                                         ("third_octave_rel.31.6", "31.5 Hz band", "{:.1f} dB"), ("corr.20-120", "Low-end correlation", "{:.3f}")]]
            notes = "Every change at once, stacked in mix order. Nothing was tuned for the combination. " + " ".join(lines)
        else:
            if a not in bests:
                continue
            b = bests[a]
            choices = {a: np.array(b["u"])}
            rev, name, slug = str(b["attempt"]), C.ASPECTS[a][3], SLUG[a]
            lines = [f"{lab[0].upper() + lab[1:]}: {fmt.format(b['baseline_features'][k])} to {fmt.format(b['features'][k])} (references {fmt.format(tg[k]['min'])} to {fmt.format(tg[k]['max'])})."
                     for k, lab, fmt in SHOW[a]]
            notes = (PLAIN[a](b["params"]) + " " + " ".join(lines) +
                     f" Score {b['score']:.2f}, found in round {b['attempt']}. {status(a)}")
        eid = f"{DATE}-hw002-b5-{i:02d}-{slug}-r{rev}"
        alt = cut(C.render(stems, sr, choices), sr, AB, K.STEM_START)
        mp3 = OUT + eid + ".mp3"
        dur = ab_file(orig.copy(), alt, sr, mp3)
        e = {"id": eid, "batch": BATCH, "title": f"HW002 — {name}: before and after, {int(dur)} s", "date": DATE,
             "file": f"/audio/skrng/{eid}.mp3", "duration_s": dur, "bpm": 160,
             "notes": f"{K.LAYOUT['ab_label']}: first as mixed, then with the change. Both halves at -14 LUFS. " + notes + " Unmastered.",
             "announce": f"/audio/skrng/tts/{eid}.mp3"}
        uploads += [(e["file"], mp3), (e["announce"], announce(eid, f"Track {NUM[i - 1]}. {name}. First the original, then the new version."))]
        entries.append(e)
    if UP:
        reg_path = OUT + "uploaded.json"
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
    m = [e for e in json.load(open(SITE + "manifest.json")) if e.get("batch") != BATCH]
    json.dump(entries + m, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "manifest.json", "a").write("\n")
    done = all(os.path.exists(W + f"runs/{a}/done.json") for a in ORDER)
    bt = [x for x in json.load(open(SITE + "batches.json")) if x["n"] != BATCH]
    bt.append({"n": BATCH, "title": "Batch 5 — six mix changes, tuned toward the references (6 Oct)",
               "notes": "Each track plays the drop twice: as mixed, then with one change. Both halves are equally loud. "
                        "A program tuned each change toward the four Bandcamp references. "
                        "It stops when ten rounds in a row find nothing better. "
                        + ("All six have stopped; these are final." if done else "This page updates when a change improves."),
               "ordered": True})
    json.dump(bt, open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
    open(SITE + "batches.json", "a").write("\n")
    print(json.dumps({"entries": [e["id"] for e in entries], "uploaded": UP, "all_done": done}))


if __name__ == "__main__":
    main()
