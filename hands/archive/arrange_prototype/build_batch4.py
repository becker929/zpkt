"""Add batch 4 to skrng and swap batches 2-3 to their on-grid re-trims.  python3 build_batch4.py [--upload]"""
import json
import os
import subprocess
import sys

S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"
SITE = S + "site/skrng/"
TTS = S + "tts/"
UP = "--upload" in sys.argv
plan = json.load(open(S + "plan4.json"))
res = {}
for l in open(S + "batch4_results.jsonl"):
    d = json.loads(l)
    if d["ok"]:
        res[d["id"]] = d
retrim = json.load(open(S + "retrim_results.json"))
m = json.load(open(SITE + "manifest.json"))
uploads = []

LAYER_NAMES = {"A": "open offbeats", "B": "16th closed", "C": "8th ride", "D": "bright 16ths", "E": "quiet ride"}


def bars_txt(segs):
    out, prev = [], None
    for a, b in segs:
        t = f"{a}–{b}"
        if out and out[-1][0] == t:
            out[-1][1] += 1
        else:
            out.append([t, 1])
    return ", ".join(t + (f" ×{n}" if n > 1 else "") for t, n in out)


new = []
for vid, name, desc, p in plan:
    d = res.get(vid)
    if not d:
        print("missing", vid); continue
    order = []
    for _, _, L in p["hats"]:
        for ch in L:
            if ch not in order:
                order.append(ch)
    e = {"id": f"2026-10-01-hw002-{vid}", "batch": 4, "title": f"HW002 — {name}, {int(d['duration_s'])} s", "date": "2026-10-01",
         "file": f"/audio/skrng/2026-10-01-hw002-{vid}.mp3", "duration_s": d["duration_s"], "bpm": 160, "lufs": d["lufs"],
         "true_peak_dbtp": d["true_peak_dbtp"],
         "notes": f"{desc} Source bars {bars_txt(p['segs'])}. Hats enter as: " + ", ".join(LAYER_NAMES[c] for c in order) + ". Unmastered."}
    uploads.append((e["file"], d["mp3"]))
    new.append(e)

for e in m:
    if e.get("batch") in (2, 3):
        vid = e["id"].replace("2026-10-01-hw002-", "")
        r = retrim.get(vid)
        if r and r["ok"]:
            e["file"] = f"/audio/skrng/2026-10-01-hw002-{vid}-r3.mp3"
            e["lufs"], e["true_peak_dbtp"] = r["lufs"], r["true_peak_dbtp"]
            if "Re-trimmed" not in e["notes"]:
                e["notes"] += " Re-trimmed 1 Oct: it started about 0.9 s early, half a bar off the grid."
            uploads.append((e["file"], r["mp3"]))
m = new + [e for e in m if e.get("batch") != 4]

for k, e in enumerate(new, 1):
    title = e["title"].replace("HW002 — ", "")
    title = title[:-2] + " seconds" if title.endswith(" s") else title
    aiff, mp3 = TTS + e["id"] + ".aiff", TTS + e["id"] + ".mp3"
    subprocess.run(["say", "-v", "Daniel", "-o", aiff, f"Batch 4, track {k}. {title}."], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-i", aiff,
                    "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
                    "[1:a]aresample=44100,aformat=channel_layouts=stereo,silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5,aresample=44100[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]",
                    "-map", "[a]", "-b:a", "128k", mp3], check=True)
    e["announce"] = f"/audio/skrng/tts/{e['id']}.mp3"
    uploads.append((e["announce"], mp3))

if UP:
    for key, path in uploads:
        r = subprocess.run(["npx", "-y", "wrangler@4.145.0", "r2", "object", "put", f"anthonybecker-audio{key.replace('/audio', '/audio', 1)}".replace("anthonybecker-audio/", "anthonybecker-audio/", 1) if False else f"anthonybecker-audio/{key.lstrip('/')}",
                            "--file", path, "--content-type", "audio/mpeg", "--remote"], cwd=os.path.expanduser("~/Desktop/zpkt"), capture_output=True, text=True)
        print(("up " if r.returncode == 0 else "FAIL ") + key, flush=True)

json.dump(m, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "manifest.json", "a").write("\n")
b = json.load(open(SITE + "batches.json"))
b = [x for x in b if x["n"] != 4]
for x in b:
    if x["n"] in (2, 3) and "re-trimmed" not in x["notes"]:
        x["notes"] += " Re-trimmed onto the grid on 1 Oct (they had started about 0.9 s early)."
b.append({"n": 4, "title": "Batch 4 — longer, on the grid, hats that stack (1 Oct)",
          "notes": "Answers the first commute feedback: 36–48 s, sections of 4 or 8 bars, a longer scoop, hats added one layer at a time without dropping any, a longer pre-kick sound, and drop-outs before the kick.",
          "ordered": True})
json.dump(b, open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "batches.json", "a").write("\n")
print(len(new), "batch-4 entries;", len(uploads), "files")
