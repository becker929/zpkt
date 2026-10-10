"""Build + verify batch 4 (plan42.json), one retry per version."""
import json, os, subprocess
S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"
plan = json.load(open(S + "plan42.json"))
out = S + "batch42_results.jsonl"
done = {}
if os.path.exists(out):
    for l in open(out):
        d = json.loads(l); done[d["id"]] = d
for vid, name, desc, p in plan:
    if done.get(vid, {}).get("ok"):
        continue
    for attempt in range(2):
        a = subprocess.run(["uv", "run", "python", S + "arrange42.py", vid, json.dumps(p)], cwd=os.path.expanduser("~/Desktop/zpkt/hands"), capture_output=True, text=True)
        if not [l for l in a.stdout.splitlines() if l.startswith("{")]:
            print("ARRANGE FAIL", vid, a.stderr[-600:], flush=True); continue
        v = subprocess.run(["uv", "run", "--with", "lameenc", "python", S + "verify42.py", vid, json.dumps(p)], cwd=os.path.expanduser("~/Desktop/zpkt/ears/mlab"), capture_output=True, text=True)
        vl = [l for l in v.stdout.splitlines() if l.startswith("{")]
        if not vl:
            print("VERIFY FAIL", vid, v.stderr[-600:], flush=True); continue
        d = json.loads(vl[-1])
        print(vid, "ok" if d["ok"] else "NOT OK", {k: d[k] for k in ("song_zero_ms", "timeline_jumps_at_s", "low_bars_off", "gap_level_db", "fx")}, flush=True)
        open(out, "a").write(json.dumps(d) + "\n")
        if d["ok"]:
            break
print("DONE", flush=True)
