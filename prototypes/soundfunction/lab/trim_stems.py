"""Job live_multitrack_trim_v1: cut each prior stem to its own content length.

The stems in live_multitrack_bounce_v1 were sized from song.last_event_time,
the whole set's length, so most of each file is trailing silence. This writes
a trimmed copy of every stem into the lab/runner.py --local layout, keeps the
originals untouched, and records per-stem lengths. Content end comes from
content_end() in lab/duck_calibration.py: last sample above -60 dBFS relative
to peak, plus a 2 s hold.
"""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parent))
from duck_calibration import content_end

SRC = Path("/Users/anthonybecker/sandbox/autodaw/hands/sweeps/out/live_multitrack_bounce_v1")
DST = Path("/Users/anthonybecker/sandbox/sound-function/local_src/stems")
rows = []
for song in ("hw002", "snts-style-track"):
    (DST / song).mkdir(parents=True, exist_ok=True)
    for wav in sorted((SRC / song).glob("*.wav")):
        y, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        end = content_end(y.mean(1), sr)
        out = DST / song / wav.name
        sf.write(str(out), y[:end], sr, subtype="PCM_24")
        side = wav.with_suffix("").with_suffix(".params.json")
        meta = json.loads(side.read_text()) if side.exists() else {}
        meta.update(original_frames=int(len(y)), original_duration_s=round(len(y)/sr, 3),
                    content_end_frames=int(end), content_duration_s=round(end/sr, 3),
                    trim_method="content_end(): last sample > -60 dBFS re peak, + 2 s hold",
                    trimmed_from=str(wav))
        (DST / song / side.name).write_text(json.dumps(meta, indent=2))
        peak = 20*np.log10(max(float(np.abs(y[:end]).max()), 1e-12)) if end else float("-inf")
        rows.append(dict(song=song, stem=wav.name, original_s=round(len(y)/sr,1),
                         content_s=round(end/sr,1), kept_pct=round(100*end/len(y),1), peak_dbfs=round(peak,1)))
        print(f"{song}/{wav.name:70s} {len(y)/sr:7.1f}s -> {end/sr:6.1f}s  ({100*end/len(y):4.1f}% kept)  peak {peak:6.1f}", flush=True)
Path("/Users/anthonybecker/sandbox/sound-function/local_src/trim_table.json").write_text(json.dumps(rows, indent=2))
print("TRIM DONE", len(rows), "stems")
