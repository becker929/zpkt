"""Add batches 4.3 (splashes) and 4.4 (hats) to skrng.  python3 build_batch43_44.py [--upload]

Spoken announcements follow docs/hw002/batch-4.2-decisions.md: say what to listen for,
one idea per sentence, no ids and no "point". Detail stays in the page notes.
SITE is a checkout of the site repo (default ~/_agent_scratch/site, env SKRNG_SITE).
Results come from run_batch.py (~/_agent_scratch/renders/<plan>_results.jsonl).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) + "/"
SITE = os.environ.get("SKRNG_SITE", os.path.expanduser("~/_agent_scratch/site")) + "/skrng/"
RENDERS = os.path.expanduser("~/_agent_scratch/renders/")
TTS = RENDERS + "tts/"
UP = "--upload" in sys.argv
DATE = "2026-10-06"
NUM = ["one", "two", "three", "four", "five"]

BATCHES = [
    (4.3, "plan43.json", "Batch 4.3 — fewer splashes (6 Oct)",
     "Four versions that change only the splashes. Kick, rumble, splash and hats play. "
     "Each one starts on the scooped kick. Batch 4.2 had a splash on every section. "
     "Here there are fewer of them, or only short ones.",
     {"b43-01-splash-every-8-bars-30s": "A splash every eight bars.",
      "b43-02-splash-every-16-bars-30s": "Two splashes, far apart.",
      "b43-03-one-splash-only-30s": "One splash, when the kick comes in.",
      "b43-04-short-splash-only-30s": "Short splashes only."}),
    (4.4, "plan44.json", "Batch 4.4 — the hats (6 Oct)",
     "Five versions that change only the hats. Kick, rumble and hats play, with no splashes. "
     "Tracks one and two are batch 4's numbers 7 and 9. "
     "Tracks three to five leave out the quiet ride.",
     {"b44-01-steps-every-4-bars-30s": "A new hat every four bars.",
      "b44-02-climb-then-scoop-36s": "The hats climb before the scoop.",
      "b44-03-loud-layers-every-2-bars-30s": "A new hat every two bars.",
      "b44-04-ride-before-sixteenths-30s": "The loud ride comes in early.",
      "b44-05-all-hats-land-with-the-kick-30s": "All the hats land with the kick."}),
]


def results(planfile):
    res = {}
    for l in open(RENDERS + planfile.replace(".json", "_results.jsonl")):
        d = json.loads(l)
        if d["ok"] or d["id"] not in res or not res[d["id"]]["ok"]:
            res[d["id"]] = d
    return res


def announce(entry_id, text):
    os.makedirs(TTS, exist_ok=True)
    aiff, mp3 = TTS + entry_id + ".aiff", TTS + entry_id + ".mp3"
    subprocess.run(["say", "-v", "Daniel", "-o", aiff, text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-i", aiff,
                    "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
                    "[1:a]aresample=44100,aformat=channel_layouts=stereo,silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5,aresample=44100[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]",
                    "-map", "[a]", "-b:a", "128k", mp3], check=True)
    return mp3


nums = [n for n, *_ in BATCHES]
manifest = [e for e in json.load(open(SITE + "manifest.json")) if e.get("batch") not in nums]
batches = [x for x in json.load(open(SITE + "batches.json")) if x["n"] not in nums]
new, uploads = [], []
for n, planfile, btitle, bnotes, spoken in BATCHES:
    plan = sorted(json.load(open(HERE + planfile)), key=lambda x: x[0])
    res = results(planfile)
    entries = []
    for k, (vid, name, desc, p) in enumerate(plan, 1):
        d = res.get(vid)
        if not d or not d["ok"]:
            sys.exit(f"{vid}: no verified render")
        e = {"id": f"{DATE}-hw002-{vid}", "batch": n, "title": f"HW002 — {name}, {int(d['duration_s'])} s", "date": DATE,
             "file": f"/audio/skrng/{DATE}-hw002-{vid}.mp3", "duration_s": d["duration_s"], "bpm": 160, "lufs": d["lufs"],
             "true_peak_dbtp": d["true_peak_dbtp"], "notes": desc + " Unmastered."}
        uploads.append((e["file"], d["mp3"]))
        e["announce"] = f"/audio/skrng/tts/{e['id']}.mp3"
        uploads.append((e["announce"], announce(e["id"], f"Track {NUM[k - 1]}. {spoken[vid]}")))
        entries.append(e)
    new = entries + new  # newest batch first, tracks in page order
    batches.append({"n": n, "title": btitle, "notes": bnotes, "ordered": True})
if UP:
    for key, path in uploads:
        r = subprocess.run(["npx", "-y", "wrangler@4.145.0", "r2", "object", "put", f"anthonybecker-audio/{key.lstrip('/')}",
                            "--file", path, "--content-type", "audio/mpeg", "--remote"], cwd=os.path.expanduser("~/Desktop/zpkt"), capture_output=True, text=True)
        print(("up " if r.returncode == 0 else "FAIL ") + key, flush=True)
json.dump(new + manifest, open(SITE + "manifest.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "manifest.json", "a").write("\n")
json.dump(batches, open(SITE + "batches.json", "w"), indent=2, ensure_ascii=False)
open(SITE + "batches.json", "a").write("\n")
print(len(new), "entries;", len(uploads), "files", "(uploaded)" if UP else "(not uploaded)")
