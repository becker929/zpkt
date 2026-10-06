"""Build + verify a batch plan, one retry per version. Renders only; publishes nothing.

  python3 run_batch.py plan44.json [verify4.py]   (run from this folder)
Results append to ~/_agent_scratch/renders/<plan>_results.jsonl; finished versions are skipped.
"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)) + "/"
planfile = sys.argv[1]
verifier = sys.argv[2] if len(sys.argv) > 2 else "verify4.py"
plan = json.load(open(HERE + planfile))
out = os.path.expanduser("~/_agent_scratch/renders/") + planfile.replace(".json", "_results.jsonl")
done = {}
if os.path.exists(out):
    for l in open(out):
        d = json.loads(l); done[d["id"]] = d
only = sys.argv[3:]
for vid, name, desc, p in plan:
    if (only and vid not in only) or done.get(vid, {}).get("ok"):
        continue
    for attempt in range(2):
        a = subprocess.run(["uv", "run", "python", HERE + "arrange43.py", vid, json.dumps(p)], cwd=os.path.expanduser("~/Desktop/zpkt/hands"), capture_output=True, text=True, env={**os.environ, "PYTHONPATH": HERE})
        if not [l for l in a.stdout.splitlines() if l.startswith("{")]:
            print("ARRANGE FAIL", vid, a.stderr[-600:], flush=True); continue
        v = subprocess.run(["uv", "run", "--with", "lameenc", "python", HERE + verifier, vid, json.dumps(p)], cwd=os.path.expanduser("~/Desktop/zpkt/ears/mlab"), capture_output=True, text=True)
        vl = [l for l in v.stdout.splitlines() if l.startswith("{")]
        if not vl:
            print("VERIFY FAIL", vid, v.stderr[-600:], flush=True); continue
        d = json.loads(vl[-1])
        print(vid, "ok" if d.get("ok") else "NOT OK", {k: d.get(k) for k in ("song_zero_ms", "timeline_jumps_at_s", "low_bars_off", "gap_level_db")}, flush=True)
        open(out, "a").write(json.dumps(d) + "\n")
        if d.get("ok"):
            break
print("DONE", flush=True)
