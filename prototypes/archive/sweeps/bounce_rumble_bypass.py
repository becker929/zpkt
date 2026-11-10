"""Two-pass rumble bounce for live_rumble_bypass_v1.

Pass A records HW002_14 track 3 ("rumble") exactly as it is. Pass B records
it again with ONLY the LFOTool device bypassed. Everything else is identical:
same clone, same arrangement, same length, same capture track.

Mechanism is the one `bounce_multitrack.py` already proved: tap the source
track's own output into a reusable capture audio track and arrangement-record
the whole set. Tapping pre-group matters here, because "kick group" carries a
compressor and two distortion units that would react differently to the two
takes and contaminate the division.

Path-B crash rules honoured: writes and reads are separate calls, one device
per call, no call holds a long sleep (the render wait happens client-side).
"""
from __future__ import annotations
import json, shutil, sys, time, wave
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/Users/anthonybecker/.agents/skills/ableton-live-control/scripts")
from live_mcp import LiveMcp  # noqa: E402

SRC_TRACK = 3
LFO_DEVICE = 4
OUT = Path("/Users/anthonybecker/sandbox/sound-function/stems/hw002_bypass")
SOURCE_SET = "/Users/anthonybecker/_agent_scratch/HW002_rumble_bypass/HW002_14.als"
SETTLE = 4.0

live = LiveMcp()


def run(code):
    r = live.execute(code)
    if r.status != "ok":
        raise RuntimeError(f"MCP error:\n{code}\n-> {r.error}")
    return r.result


def peak_dbfs(path: Path) -> float:
    import audioop
    with wave.open(str(path), "rb") as wf:
        w, n = wf.getsampwidth(), wf.getnframes()
        mx = 0
        left = n
        while left > 0:
            frames = wf.readframes(min(1 << 20, left))
            if not frames:
                break
            left -= len(frames) // (w * wf.getnchannels())
            mx = max(mx, audioop.max(frames, w))
    full = float(1 << (8 * w - 1))
    import math
    return -math.inf if mx == 0 else 20 * math.log10(mx / full)


def ensure_capture(cap_idx: int, source_name: str):
    run(f"tr = song.tracks[{cap_idx}]\n"
        f"_rt = next((rt for rt in tr.available_input_routing_types"
        f" if rt.display_name == {source_name!r}), None)\n"
        f"if _rt is None: raise RuntimeError('no routing: '"
        f" + str([x.display_name for x in tr.available_input_routing_types]))\n"
        f"tr.input_routing_type = _rt\n"
        f"tr.arm = 1\n"
        f"tr.current_monitoring_state = 1\n"
        f"result = tr.input_routing_type.display_name")


def bounce(out_wav: Path, cap_idx: int, beats: float, tempo: float) -> bool:
    run(f"tr = song.tracks[{cap_idx}]\n"
        f"[tr.delete_clip(c) for c in list(tr.arrangement_clips)]\n"
        f"for s in range(8):\n"
        f"    cs = tr.clip_slots[s]\n"
        f"    if cs.has_clip: cs.delete_clip()\n"
        f"result = 'cleared'")
    run("song.loop = 0\n"
        "song.back_to_arranger = 0\n"
        "song.current_song_time = 0.0\n"
        "song.record_mode = 1\n"
        "song.start_playing()\n"
        "result = 'rec+play'")
    dur = beats / tempo * 60.0 + SETTLE
    print(f"  recording {dur:.0f}s ...", flush=True)
    time.sleep(dur)
    run("song.record_mode = 0; song.stop_playing(); result = 'stop'")
    time.sleep(1.0)
    fp = run(f"acs = list(song.tracks[{cap_idx}].arrangement_clips)\n"
             f"result = acs[0].file_path if acs else None")
    if not fp or not Path(fp).exists():
        print(f"  no clip: {fp}")
        return False
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fp, out_wav)
    return True


def main():
    assert run("result = 1 + 1") == 2, "bridge dead"
    tempo = float(run("result = song.tempo"))
    beats = float(run("result = song.last_event_time"))
    n = int(run("result = len(song.tracks)"))
    name = run(f"result = song.tracks[{SRC_TRACK}].name")
    assert name == "rumble", f"track {SRC_TRACK} is {name!r}, not 'rumble'"
    print(f"tempo={tempo} beats={beats:.1f} ({beats/tempo*60:.0f}s/pass) tracks={n}")

    # Capture track: reuse a trailing agent track if present, else create one.
    last = run(f"result = song.tracks[{n-1}].name")
    if last == "STEM_CAP":
        cap = n - 1
    else:
        run("song.create_audio_track(-1)")
        time.sleep(1.0)
        n = int(run("result = len(song.tracks)"))   # re-fetch after create
        cap = n - 1
        run(f"song.tracks[{cap}].name = 'STEM_CAP'")
        time.sleep(0.5)
    print(f"capture track = {cap} ({run(f'result = song.tracks[{cap}].name')})")

    ensure_capture(cap, "rumble")
    results = {}
    try:
        # ---- Pass A: exactly as it is -------------------------------------
        on = run(f"result = song.tracks[{SRC_TRACK}].devices[{LFO_DEVICE}].parameters[0].value")
        assert on == 1.0, f"LFOTool should start ON, got {on}"
        print("[A] rumble, LFOTool ON")
        a = OUT / "03__rumble.wav"
        if not (a.exists() and a.stat().st_size > 1_000_000):
            if not bounce(a, cap, beats, tempo):
                raise RuntimeError("pass A produced no clip")
        print(f"  -> {a.name} {a.stat().st_size/1e6:.0f} MB peak {peak_dbfs(a):.1f} dBFS")

        # ---- Bypass LFOTool: write, then read back in a SEPARATE call -----
        run(f"song.tracks[{SRC_TRACK}].devices[{LFO_DEVICE}].parameters[0].value = 0")
        time.sleep(0.5)
        off = run(f"result = song.tracks[{SRC_TRACK}].devices[{LFO_DEVICE}].parameters[0].value")
        assert off == 0.0, f"LFOTool bypass did not take, value={off}"
        print("[B] rumble, LFOTool BYPASSED (verified value=0.0)")

        b = OUT / "03__rumble__lfotool-off.wav"
        if not (b.exists() and b.stat().st_size > 1_000_000):
            if not bounce(b, cap, beats, tempo):
                raise RuntimeError("pass B produced no clip")
        print(f"  -> {b.name} {b.stat().st_size/1e6:.0f} MB peak {peak_dbfs(b):.1f} dBFS")
        results = {"a": str(a), "b": str(b), "tempo": tempo, "beats": beats, "cap": cap}
    finally:
        # Always restore LFOTool and disarm, whatever happened.
        run(f"song.tracks[{SRC_TRACK}].devices[{LFO_DEVICE}].parameters[0].value = 1")
        time.sleep(0.5)
        back = run(f"result = song.tracks[{SRC_TRACK}].devices[{LFO_DEVICE}].parameters[0].value")
        run(f"song.tracks[{cap}].arm = 0; result = 'disarmed'")
        print(f"restored LFOTool on={back}, capture disarmed")

    (OUT / "_bounce_result.json").write_text(json.dumps(results, indent=2))
    print("DONE")


if __name__ == "__main__":
    main()
