"""Measure every knob-map step with the measurer of record (ears shim) and
write one CSV per row: value, crest_db, five band shares, peak, rms."""
import csv, json, subprocess, sys
from pathlib import Path
EARS_PY="/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/python"; EARS="/Users/anthonybecker/_agent_scratch/ears_lab/ears_shim.py"
OUT=Path(sys.argv[1] if len(sys.argv)>1 else "out/knobmap_hw002_kickgroup_v1")
COLS=["value_set","value_read","crest_db","sub_share","low_share","mid_share","high_share","air_share","peak_dbfs","rms_dbfs","wav"]
for rdir in sorted(p for p in OUT.iterdir() if p.is_dir()):
    rows=[]
    for side in sorted(rdir.glob("*.params.json")):
        s=json.loads(side.read_text()); wav=rdir/s["wav"]
        r=subprocess.run([EARS_PY,EARS,"analyze",str(wav)],capture_output=True,text=True)
        if r.returncode!=0: print(f"FAIL {wav.name}: {r.stderr[-200:]}", flush=True); continue
        m=json.loads(r.stdout)
        rows.append({"value_set":s["value_set"],"value_read":s["value_read"],**{k:round(m[k],4) for k in ("crest_db","sub_share","low_share","mid_share","high_share","air_share","peak_dbfs","rms_dbfs")},"wav":wav.name})
    rows.sort(key=lambda r:r["value_set"])
    with open(rdir/f"{rdir.name}.ears.csv","w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=COLS,quoting=csv.QUOTE_ALL); w.writeheader(); w.writerows(rows)
    c=[r["crest_db"] for r in rows]; s=[r["sub_share"] for r in rows]
    print(f"{rdir.name:22s} n={len(rows):2d}  crest {min(c):5.2f}..{max(c):5.2f}  sub_share {min(s):.3f}..{max(s):.3f}", flush=True)
print("MEASURE DONE")
