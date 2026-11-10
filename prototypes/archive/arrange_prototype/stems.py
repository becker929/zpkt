"""Render HW002 bars 121-144 as the full mix plus one stem per group (for the mix-climb spike).

  uv run python stems.py            (from ~/Desktop/zpkt/hands, PYTHONPATH=this folder)

The main bus holds only a Utility, so the four group stems sum to the mix; the script
checks that. Refuses to start while another agent is driving Live (an AbletonLiveMCP
connection in the last QUIET_S seconds of Live's log). Output, bar 121 at sample 0:
~/_agent_scratch/mixclimb/stems/{mix,kick,perc,sfx,brk}.wav
"""
import datetime as dt
import json
import os
import re
import sys

import numpy as np
import soundfile as sf

import arrange as A

VID = "mixclimb-stems"
SEGS = [(119, 144)]          # bars 119-120 are the lead-in and are trimmed off (119 has an automation reference)
LEAD, BAR = 2, 1.5
KEEP_BARS = 24               # bars 121-144
OUT = os.environ.get("STEMS_OUT", os.path.expanduser("~/_agent_scratch/mixclimb/stems/"))
GROUPS = {"kick": "kick group", "perc": "perc group", "sfx": "SFX group", "brk": "Break group"}
LOG = os.path.expanduser("~/Library/Preferences/Ableton/Live 12.4.6/Log.txt")
QUIET_S = 300


def last_mcp_activity():
    last = None
    with open(LOG, errors="ignore") as f:
        for line in f:
            if "AbletonLiveMCP: connected" in line:
                last = line[:26]
    return dt.datetime.fromisoformat(last) if last else None


def trim(take):
    timing = json.load(open(take + ".timing.json"))
    x, sr = sf.read(take, always_2d=True, dtype="float32")
    start = int(round(timing["song_zero_seconds"] * sr)) + int(LEAD * BAR * sr)
    return x[start:start + int(KEEP_BARS * BAR * sr)], sr


def solo_only(name):
    A.r(f"""
for t in song.tracks:
    t.solo = (t.name == {name!r}) if {name!r} else False
result = [t.name for t in song.tracks if t.solo]""")


def from_set(name, bars, keep, layout):
    """Stems of an already-built version set (e.g. a batch version), lead-in trimmed."""
    global KEEP_BARS
    KEEP_BARS = keep
    path = os.path.join(A.PROJ, name + ".als")
    if A.front() != name:
        A.open_set(path, name)
    A.r("song.loop = False")
    takes = {}
    for stem, group in [("mix", "")] + list(GROUPS.items()):
        solo_only(group)
        takes[stem] = A.record_arrangement(transport=A.T, filename=f"{name}-{stem}.wav", duration_beats=bars * 4.0,
                                           output_dir=A.OUT, tail_beats=2.0)
    solo_only("")
    A.menu("File", "Save Live Set")
    return takes


def main():
    last = last_mcp_activity()
    if last and (dt.datetime.now() - last).total_seconds() < QUIET_S and "--force" not in sys.argv:
        sys.exit(f"Live was driven by an agent at {last:%T}; waiting for {QUIET_S} s of quiet")
    os.makedirs(OUT, exist_ok=True)
    if "--from-set" in sys.argv:              # --from-set NAME BARS_INCL_LEAD 'LAYOUT_JSON'
        i = sys.argv.index("--from-set")
        name, bars, layout = sys.argv[i + 1], int(sys.argv[i + 2]), json.loads(sys.argv[i + 3])
        takes = from_set(name, bars, bars - LEAD, layout)
        json.dump({**layout, "source": name}, open(OUT + "layout.json", "w"), indent=1)
    else:
        res = A.make(VID, SEGS)                    # full mix, saved set
        takes = {"mix": res["raw"]}
        bars = sum(b - a + 1 for a, b in SEGS)
        for stem, group in GROUPS.items():
            solo_only(group)
            takes[stem] = A.record_arrangement(transport=A.T, filename=f"{VID}-{stem}.wav", duration_beats=bars * 4.0,
                                               output_dir=A.OUT, tail_beats=2.0)
        solo_only("")
        A.menu("File", "Save Live Set")
    audio = {}
    for stem, take in takes.items():
        audio[stem], sr = trim(take)
        sf.write(OUT + f"{stem}.wav", audio[stem], sr, subtype="FLOAT")
    n = min(len(v) for v in audio.values())
    s = sum(audio[k][:n] for k in GROUPS)
    m = audio["mix"][:n]
    resid = 10 * np.log10(np.mean((s - m) ** 2) / np.mean(m ** 2))
    print(json.dumps({"stems": list(audio), "seconds": round(n / sr, 2), "sum_vs_mix_residual_db": round(float(resid), 1),
                      "takes": takes}))


if __name__ == "__main__":
    main()
