"""Add batch 4.1 to skrng.  python3 build_batch41.py [--upload]"""
import json
import os
import subprocess
import sys

S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"
SITE = S + "site/skrng/"
TTS = S + "tts/"
UP = "--upload" in sys.argv
BATCH = 4.1
plan = json.load(open(S + "plan41.json"))
plan.sort(key=lambda x: x[0])  # b41-01 .. b41-10 in page order
res = {}
for l in open(S + "batch41_results.jsonl"):
    d = json.loads(l)
    if d["ok"]:
        res[d["id"]] = d
m = [e for e in json.load(open(SITE + "manifest.json")) if e.get("batch") != BATCH]
new, uploads = [], []
for k, (vid, name, desc, p) in enumerate(plan, 1):
    d = res.get(vid)
    if not d:
        print("missing", vid); continue
    e = {"id": f"2026-10-02-hw002-{vid}", "batch": BATCH, "title": f"HW002 — {name}, {int(d['duration_s'])} s", "date": "2026-10-02",
         "file": f"/audio/skrng/2026-10-02-hw002-{vid}.mp3", "duration_s": d["duration_s"], "bpm": 160, "lufs": d["lufs"],
         "true_peak_dbtp": d["true_peak_dbtp"], "notes": desc + " Unmastered."}
    uploads.append((e["file"], d["mp3"]))
    title = e["title"].replace("HW002 — ", "")
    title = title[:-2] + " seconds" if title.endswith(" s") else title
    aiff, mp3 = TTS + e["id"] + ".aiff", TTS + e["id"] + ".mp3"
    subprocess.run(["say", "-v", "Daniel", "-o", aiff, f"Batch 4 point 1, track {k}. {title}."], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-i", aiff,
                    "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
                    "[1:a]aresample=44100,aformat=channel_layouts=stereo,silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5,aresample=44100[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]",
                    "-map", "[a]", "-b:a", "128k", mp3], check=True)
    e["announce"] = f"/audio/skrng/tts/{e['id']}.mp3"
    uploads.append((e["announce"], mp3))
    new.append(e)
if UP:
    for key, path in uploads:
        r = subprocess.run(["npx", "-y", "wrangler@4.145.0", "r2", "object", "put", f"anthonybecker-audio/{key.lstrip('/')}",
                            "--file", path, "--content-type", "audio/mpeg", "--remote"], cwd=os.path.expanduser("~/Desktop/zpkt"), capture_output=True, text=True)
        print(("up " if r.returncode == 0 else "FAIL ") + key, flush=True)
json.dump(new + m, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "manifest.json", "a").write("\n")
b = [x for x in json.load(open(SITE + "batches.json")) if x["n"] != BATCH]
b.append({"n": BATCH, "title": "Batch 4.1 — track 1 earlier, track 2's beatbox fixed, splash lengths (2 Oct)",
          "notes": "Tracks 1–3 bring track 1's excitement forward. Tracks 4–7 play track 2's beatbox phrase once, with its final wuh stretched x2, x1.5, x1 and x3, ending at the silence before the kick. Tracks 8–10 compare splash lengths of 6, 8 and 3 beats against the whole-note splash used elsewhere.",
          "ordered": True})
json.dump(b, open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "batches.json", "a").write("\n")
print(len(new), "entries;", len(uploads), "files")
