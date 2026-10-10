"""Phase 1b: batched LOM edits, save of a changed set, and the three render modes.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_renders.py
"""
import os
import time

import pp
from pp import A, log, timed

BEATS = 22 * 4.0          # lead 2 bars + 20 bars


def main():
    name = "HW002_121_pp_render"
    pp.copy_set(pp.CANON, name)
    pp.prepare_switch()
    timed("load_canon", pp.open_set, name, meta={"rep": 4})

    path = "song.tracks[2].devices[1].parameters[1]"
    t = time.time()
    A.r(f"for _ in range(50):\n    {path}.value = {path}.value\nresult = 50")
    log("lom_param_set_x50_one_call", time.time() - t)
    t = time.time()
    A.r("result = song.tempo")
    log("lom_roundtrip_trivial", time.time() - t)

    A.r("song.tracks[2].mute = not song.tracks[2].mute")
    A.r("song.tracks[2].mute = not song.tracks[2].mute")
    t = time.time(); ok = pp.save(name); log("save_canon_changed", time.time() - t, wrote=str(ok))

    os.makedirs(pp.DATA + "takes", exist_ok=True)
    t = time.time(); pp.record("rt_main_22bars", BEATS); log("render_realtime_main", time.time() - t, beats=BEATS)
    t = time.time(); pp.export(pp.DATA + "takes/ex_main_22bars.wav", 0.0, BEATS, "Main")
    log("render_export_main", time.time() - t, beats=BEATS)
    t = time.time(); pp.export(pp.DATA + "takes/ex_all_22bars.wav", 0.0, BEATS, "All Individual Tracks")
    log("render_export_all_tracks", time.time() - t, beats=BEATS,
        files=len([f for f in os.listdir(pp.DATA + "takes") if f.startswith("ex_all_22bars")]))


if __name__ == "__main__":
    main()
