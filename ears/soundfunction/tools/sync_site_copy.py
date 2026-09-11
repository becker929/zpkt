#!/usr/bin/env python3
"""Copy this project into the site repo at research/sound-function/repo/, without audio
or scratch.   python3 tools/sync_site_copy.py"""
import shutil, os
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
DST = Path("/home/user/anthonybecker.me/research/sound-function/repo")
SKIP_DIRS = {"__pycache__", ".git", "scratch", "_raw", "wav", "audio", "results", "stems_results", "stems", "_sep", "pump_synth", "sweeps", "loops", "roles", "node_modules"}
SKIP_EXT = {".wav", ".mp3", ".flac", ".npy", ".pyc"}
SKIP_FILES = {"local.env", ".mailbox_last_id"}   # secrets and per-machine state never reach the site
if DST.exists(): shutil.rmtree(DST)
n = 0
for root, dirs, files in os.walk(SRC):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
    for f in files:
        p = Path(root) / f
        if p.suffix in SKIP_EXT or f.startswith(".") or f in SKIP_FILES or f.endswith(".log"): continue
        rel = p.relative_to(SRC); (DST / rel).parent.mkdir(parents=True, exist_ok=True)
        if rel.as_posix() == "corpus2/results.json":
            # per-track grids stay in the research repo; the copy keeps the scalar results
            import json
            rows = json.load(open(p))
            for r in rows:
                for k in ("beat_energy", "bar_matrix", "bar_low", "profile_energy"): r.pop(k, None)
            json.dump(rows, open(DST / rel, "w")); n += 1; continue
        if rel.as_posix() == "corpus2/stems_results.json":
            # the per-hit feature lists are in out/library_corpus.csv; keep the copy under Cloudflare's 25 MiB per-file limit
            import json
            rows = json.load(open(p))
            for r in rows: r.pop("hits", None)
            json.dump(rows, open(DST / rel, "w")); n += 1; continue
        shutil.copy2(p, DST / rel); n += 1
# keep the ignore file so the copy documents what is left out
shutil.copy2(SRC / ".gitignore", DST / ".gitignore")
print(f"copied {n} files to {DST}")
