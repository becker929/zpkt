"""E1: Live memory and all-tracks export time vs submix count, warm vs fresh.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_e1_memory.py [warm] [1] [4] [8] [final]

warm : on the set already in front (must be HW002_121_pp_v08), export all tracks under
       the current, possibly bloated, memory state.
S    : restart Live, open HW002_121_pp_v<S>, export all tracks (fresh process).
Snr  : like S, but Live is already fresh on 'Untitled': open the set without restarting.
final: save HW002_121_pp_v08 (must be in front) and check no dialog is open.
No argument runs all parts in order. Any guard or error stops the run (no recovery).
"""
import os
import sys
import time

import pp
from pp import A, log

BEATS = 88.0                      # 2-bar lead-in + 20 bars at 160 BPM
OUT = pp.DATA + "e1/"
MODE = "All Individual Tracks"

_close_calls = []
_orig_close = pp.close_dialogs


def _traced_close():              # pp.export cancels a stranded dialog before its retry: record it
    _close_calls.append(time.strftime("%FT%T"))
    log("e1_export_retry_close_dialogs", 0)
    _orig_close()


pp.close_dialogs = _traced_close


def wavs(stem):
    return sorted(f for f in os.listdir(OUT)
                  if f.endswith(".wav") and (f == stem + ".wav" or f.startswith(stem + " ")))


def state():
    return {**pp.live_footprint_gb(), **pp.mem()}


def export_all(stem, S, step, **kw):
    if wavs(stem):
        raise pp.Guard(f"{stem}: output files already exist; refusing to overwrite")
    t = time.time()
    written = pp.export(OUT + stem + ".wav", 0.0, BEATS, MODE)
    dt = time.time() - t
    return log(step, dt, S=S, files=len(written), files_in_dir=len(wavs(stem)), **kw, **state())


def warm():
    name = "HW002_121_pp_v08"
    pp.check("e1 warm before", expect_front=name)
    log("e1_mem_warm_before", 0, S=8, **state())
    export_all("warm_v08", 8, "e1_export_warm")
    pp.check("e1 warm after", expect_front=name)


def fresh(S):
    name = f"HW002_121_pp_v{S:02d}"
    pp.check(f"e1 S={S} before restart")
    before = pp.live_footprint_gb()
    t = time.time()
    boot = pp.restart_live()
    dt = time.time() - t
    default = A.front()
    log("e1_restart", dt, S=S, boot_s=round(boot, 3), default_set=default,
        before_mem_gb=before["live_mem_gb"], before_compressed_gb=before["live_compressed_gb"], **state())
    pp.check(f"e1 S={S} after restart", ours=False)
    if default == name:
        raise pp.Guard(f"e1 S={S}: Live reopened {name} on launch; load would not be measured")
    t = time.time()
    pp.open_set(name)
    dt = time.time() - t
    n = A.r("result = len(song.tracks)")
    log("e1_load_fresh", dt, S=S, tracks=n, **state())
    pp.check(f"e1 S={S} after load", expect_front=name)
    export_all(f"fresh_v{S:02d}", S, "e1_export_fresh", tracks=n)
    pp.check(f"e1 S={S} after export", expect_front=name)


def fresh_norestart(S):
    """Live was just relaunched (by hand) and sits on the default 'Untitled' set: open directly."""
    name = f"HW002_121_pp_v{S:02d}"
    front, n_dlg = A.front(), pp.dialogs()
    if front != "Untitled" or n_dlg != 0:
        raise pp.Guard(f"e1 S={S} no-restart: expected 'Untitled' and no dialog, got {front!r}, {n_dlg} dialog(s)")
    log("e1_fresh_baseline", 0, S=S, default_set=front, **state())
    t = time.time()
    pp.open_set(name)
    dt = time.time() - t
    n = A.r("result = len(song.tracks)")
    log("e1_load_fresh", dt, S=S, tracks=n, restart="manual", **state())
    pp.check(f"e1 S={S} after load", expect_front=name)
    export_all(f"fresh_v{S:02d}", S, "e1_export_fresh", tracks=n, restart="manual")
    pp.check(f"e1 S={S} after export", expect_front=name)


def final():
    name = "HW002_121_pp_v08"
    pp.check("e1 final before save", expect_front=name)
    t = time.time()
    ok = pp.save(name)
    log("e1_final_save", time.time() - t, wrote=str(ok), **pp.live_footprint_gb())
    pp.check("e1 final after save", expect_front=name)


def main():
    os.makedirs(OUT, exist_ok=True)
    parts = sys.argv[1:] or ["warm", "1", "4", "8", "final"]
    for p in parts:
        if p == "warm":
            warm()
        elif p == "final":
            final()
        elif p.endswith("nr"):         # e.g. "8nr": fresh run on an already-fresh Live, no restart
            fresh_norestart(int(p[:-2]))
        else:
            fresh(int(p))
    if _close_calls:
        print("NOTE: pp.export cancelled a stranded dialog and retried at", _close_calls, flush=True)


if __name__ == "__main__":
    main()
