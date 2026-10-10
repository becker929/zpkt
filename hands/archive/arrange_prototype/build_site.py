"""Assemble skrng batches 1-3: entries, announcements (TTS), uploads, batches.json.

python3 build_site.py [--upload]
"""
import json
import os
import subprocess
import sys

S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"
SITE = S + "site/skrng/"
TTS = S + "tts/"
UPLOAD = "--upload" in sys.argv
os.makedirs(TTS, exist_ok=True)
sys.path.insert(0, S)
_argv, sys.argv = sys.argv, sys.argv[:1]
import entries as E  # noqa: E402  (reference lists; the module also runs its own builder on import)
sys.argv = _argv

plan = json.load(open(S + "plan3.json"))
res = {}
for l in open(S + "batch3_results.jsonl"):
    d = json.loads(l)
    if d["ok"]:
        res[d["id"]] = d

manifest = json.load(open(SITE + "manifest.json"))
old = {m["id"]: m for m in manifest}


def bars_txt(segs):
    return ", ".join(f"{a}–{b}" if a != b else f"{a}" for a, b in segs)


out = []
# batch 3: hat progressions under 40 s
for i, (vid, segs, name, desc) in enumerate(plan["batch3"]):
    d = res.get(vid)
    if not d:
        print("skip (not verified):", vid)
        continue
    out.append({"id": f"2026-10-01-hw002-{vid}", "batch": 3, "title": f"HW002 — {name}, {int(d['duration_s'])} s",
                "date": "2026-10-01", "file": f"/audio/skrng/2026-10-01-hw002-{vid}.mp3", "duration_s": d["duration_s"],
                "bpm": 160, "lufs": d["lufs"], "true_peak_dbtp": d["true_peak_dbtp"],
                "notes": f"{desc} Source bars {bars_txt(segs)}. Unmastered.", "refs": E.SHORTS, "_mp3": d["mp3"]})
# batch 2: re-rendered shapes after references
for vid, segs in plan["rerender_batch2"]:
    d = res.get(vid)
    prev = old.get(f"2026-10-01-hw002-{vid}")
    if not prev:
        continue
    e = dict(prev)
    e["batch"] = 2
    if d:
        e.update({"file": f"/audio/skrng/2026-10-01-hw002-{vid}-r2.mp3", "duration_s": d["duration_s"], "lufs": d["lufs"],
                  "true_peak_dbtp": d["true_peak_dbtp"], "_mp3": d["mp3"]})
        if "Re-rendered" not in e["notes"]:
            e["notes"] += " Re-rendered 1 Oct: the first render opened with about a second of misplaced audio (a recording glitch)."
    else:
        print("batch 2 keeps old render:", vid)
    out.append(e)
# batch 1: the 30 Sep renders
for m in manifest:
    if m["date"] == "2026-09-30":
        e = dict(m)
        e["batch"] = 1
        out.append(e)

# announcements: 500 ms silence, spoken title, 500 ms silence
counters = {}
for e in out:
    counters[e["batch"]] = counters.get(e["batch"], 0) + 1
    k = counters[e["batch"]]
    title = e["title"].replace("HW002 — ", "").replace(" s:", " seconds:")
    title = title[:-2] + " seconds" if title.endswith(" s") else title
    text = f"Batch {e['batch']}, track {k}. {title}."
    aiff, mp3 = TTS + e["id"] + ".aiff", TTS + e["id"] + ".mp3"
    subprocess.run(["say", "-v", "Daniel", "-o", aiff, text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-i", aiff,
                    "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
                    "[1:a]aresample=44100,aformat=channel_layouts=stereo,silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5,aresample=44100[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]",
                    "-map", "[a]", "-b:a", "128k", mp3], check=True)
    e["announce"] = f"/audio/skrng/tts/{e['id']}.mp3"
    e["_tts"] = mp3


def put(key, path, ctype="audio/mpeg"):
    r = subprocess.run(["npx", "-y", "wrangler@4.145.0", "r2", "object", "put", f"anthonybecker-audio/{key}", "--file", path,
                        "--content-type", ctype, "--remote"], cwd=os.path.expanduser("~/Desktop/zpkt"), capture_output=True, text=True)
    print(("up " if r.returncode == 0 else "FAIL ") + key)


if UPLOAD:
    for e in out:
        if "_mp3" in e and "--tts-only" not in sys.argv:
            put(e["file"].lstrip("/"), e["_mp3"])
        put(e["announce"].lstrip("/"), e["_tts"])

clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in out]
json.dump(clean, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "manifest.json", "a").write("\n")
batches = [
    {"n": 1, "title": "Batch 1 — first renders (30 Sep)", "notes": "The first 30 s experiment and the first 60 s demo. Both predate later fixes.", "ordered": True},
    {"n": 2, "title": "Batch 2 — shapes after references (1 Oct)", "notes": "Ten cuts shaped after genre Shorts, label previews (NineTimesNine, SNTS) and two of the audio references, plus the fixed 60 s demo. Re-rendered to remove a glitch in the first second.", "ordered": True},
    {"n": 3, "title": "Batch 3 — hat progressions, all under 40 s (1 Oct)", "notes": "Each cut climbs through the song's own layering: the hats and percussion step up every few bars instead of holding one level.", "ordered": True},
]
json.dump(batches, open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "batches.json", "a").write("\n")
print(len(clean), "entries:", {b: sum(1 for e in clean if e["batch"] == b) for b in (1, 2, 3)})
