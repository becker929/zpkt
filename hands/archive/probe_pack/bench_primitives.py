"""Phase 1: time Live's primitives on the canonical shape (batch 4.3 track 1).

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_primitives.py

Load, save, LOM edits, Edit-menu time ops, and three render modes:
real-time resampling record, offline export of Main, offline export of all tracks.
"""
import os
import time

import pp
from pp import A, TO, log, timed

BEATS = 22 * 4.0          # lead 2 bars + 20 bars


def main():
    a, b = "HW002_121_pp_load_a", "HW002_121_pp_load_b"
    pp.copy_set(pp.CANON, a)
    pp.copy_set(pp.CANON, b)
    for i in range(3):                                   # alternate so every open is a real load
        pp.prepare_switch()
        timed("load_canon", pp.open_set, a if i % 2 == 0 else b, meta={'rep': i})
    full = "HW002_121_pp_load_full"
    pp.copy_set("HW002_121_full", full)
    pp.prepare_switch()
    timed("load_full", pp.open_set, full, meta={'rep': 0})
    pp.prepare_switch()
    timed("load_canon_after_full", pp.open_set, a, meta={'rep': 0})

    # saves: one after a tiny edit
    A.r("song.tempo = 160.0")
    A.r("song.tracks[2].mute = False")
    t = time.time(); ok = pp.save(a); log("save_canon", time.time() - t, wrote=ok)

    # LOM edits
    path = "song.tracks[2].devices[1].parameters[1]"
    t = time.time()
    for k in range(50):
        A.r(f"{path}.value = {path}.value")
    log("lom_param_set_x50", time.time() - t)
    perc = A.r("result = [i for i, t in enumerate(song.tracks) if t.name == 'perc group'][0]")
    for k in range(3):
        t = time.time()
        A.r(f"song.tracks[{perc}].insert_device('Reverb', len(list(song.tracks[{perc}].devices)))")
        log("lom_insert_reverb", time.time() - t, rep=k)
        t = time.time()
        A.r(f"song.tracks[{perc}].delete_device(len(list(song.tracks[{perc}].devices)) - 1)")
        log("lom_delete_device", time.time() - t, rep=k)
    kick = A.r("result = [i for i, t in enumerate(song.tracks) if t.name == 'kick group'][0]")
    n0 = A.r("result = len(song.tracks)")
    t = time.time(); A.r(f"song.duplicate_track({kick})"); log("lom_duplicate_group", time.time() - t,
                                                               added=A.r("result = len(song.tracks)") - n0)
    t = time.time(); A.r("song.create_audio_track(-1)"); log("lom_create_audio_track", time.time() - t)

    # Edit-menu time ops (GUI)
    for k in range(2):
        t = time.time(); TO.duplicate(8.0, 8.0); log("gui_duplicate_time_2bars", time.time() - t, rep=k)
        t = time.time(); TO.delete(8.0, 8.0); log("gui_delete_time_2bars", time.time() - t, rep=k)

    # back to a clean canonical set for renders
    pp.prepare_switch()
    timed("load_canon", pp.open_set, b, meta={'rep': 3})
    os.makedirs(pp.DATA + "takes", exist_ok=True)
    t = time.time(); pp.record("rt_main_22bars", BEATS); log("render_realtime_main", time.time() - t, beats=BEATS)
    t = time.time(); pp.export(pp.DATA + "takes/ex_main_22bars.wav", 0.0, BEATS, "Main")
    log("render_export_main", time.time() - t, beats=BEATS)
    t = time.time(); pp.export(pp.DATA + "takes/ex_all_22bars.wav", 0.0, BEATS, "All Individual Tracks")
    log("render_export_all_tracks", time.time() - t, beats=BEATS,
        files=len([f for f in os.listdir(pp.DATA + "takes") if f.startswith("ex_all_22bars")]))


if __name__ == "__main__":
    main()
