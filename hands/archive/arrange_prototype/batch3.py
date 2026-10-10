"""Render + verify every version in plan3.json (skips ids already verified ok)."""
import json, subprocess, os, sys
S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"
plan = json.load(open(S + "plan3.json"))
items = [(v, segs) for v, segs, *_ in plan["batch3"]] + [(v, segs) for v, segs in plan["rerender_batch2"]]
done_path = S + "batch3_results.jsonl"
done = {}
if os.path.exists(done_path):
    for l in open(done_path):
        d = json.loads(l); done[d["id"]] = d
for vid, segs in items:
    if done.get(vid, {}).get("ok"):
        continue
    for attempt in range(2):
        a = subprocess.run(["uv", "run", "python", S + "arrange2.py", vid, json.dumps(segs)], cwd=os.path.expanduser("~/Desktop/zpkt/hands"), capture_output=True, text=True)
        line = [l for l in a.stdout.splitlines() if l.startswith("{")]
        if not line:
            print("ARRANGE FAIL", vid, a.stderr[-400:], flush=True); continue
        lead = json.loads(line[-1])["lead_bars"]
        v = subprocess.run(["uv", "run", "--with", "lameenc", "python", S + "verify2.py", vid, json.dumps(segs), str(lead)], cwd=os.path.expanduser("~/Desktop/zpkt/ears/mlab"), capture_output=True, text=True)
        vl = [l for l in v.stdout.splitlines() if l.startswith("{")]
        if not vl:
            print("VERIFY FAIL", vid, v.stderr[-400:], flush=True); continue
        d = json.loads(vl[-1]); d["segments"] = segs
        print(vid, "ok" if d["ok"] else "NOT OK", {k: d[k] for k in ("offset_ms", "timeline_jumps_at_s", "bars_off", "lufs", "true_peak_dbtp")}, flush=True)
        open(done_path, "a").write(json.dumps(d) + "\n")
        if d["ok"]:
            break
print("DONE", flush=True)
