"""Pass B only: re-record HW002_14 track 3 with LFOTool bypassed, bounded to
the track's REAL content (0 to 704 beats) plus a 4-beat tail, not to
song.last_event_time, which sits far past the end of the music."""
import shutil, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/anthonybecker/.agents/skills/ableton-live-control/scripts")
from live_mcp import LiveMcp

SRC, LFO, CAP = 2, 4, 18
BEATS = 708.0            # 704 content + 4 beat tail
OUT = Path("/Users/anthonybecker/sandbox/sound-function/stems/hw002_bypass")
live = LiveMcp()

def run(code):
    r = live.execute(code)
    if r.status != "ok":
        raise RuntimeError(f"MCP error:\n{code}\n-> {r.error}")
    return r.result

tempo = float(run("result = song.tempo"))
print(f"tempo={tempo} beats={BEATS} -> {BEATS/tempo*60:.0f}s", flush=True)
assert run(f"result = song.tracks[{SRC}].name") == "kick"

run(f"tr = song.tracks[{CAP}]\n"
    f"_rt = next((rt for rt in tr.available_input_routing_types if rt.display_name == 'kick'), None)\n"
    f"if _rt is None: raise RuntimeError('no rumble routing')\n"
    f"tr.input_routing_type = _rt\ntr.arm = 1\ntr.current_monitoring_state = 1\n"
    f"result = tr.input_routing_type.display_name")

try:
    print("kick pass, no device changes", flush=True)

    run(f"tr = song.tracks[{CAP}]\n"
        f"[tr.delete_clip(c) for c in list(tr.arrangement_clips)]\n"
        f"for s in range(8):\n"
        f"    cs = tr.clip_slots[s]\n"
        f"    if cs.has_clip: cs.delete_clip()\n"
        f"result='cleared'")
    run("song.loop = 0\nsong.back_to_arranger = 0\nsong.current_song_time = 0.0\n"
        "song.record_mode = 1\nsong.start_playing()\nresult='go'")
    dur = BEATS / tempo * 60.0 + 3.0
    print(f"recording {dur:.0f}s ...", flush=True)
    time.sleep(dur)
    run("song.record_mode = 0; song.stop_playing(); result='stop'")
    time.sleep(1.0)
    fp = run(f"acs = list(song.tracks[{CAP}].arrangement_clips)\nresult = acs[0].file_path if acs else None")
    assert fp and Path(fp).exists(), f"no clip: {fp}"
    dst = OUT / "02__kick.wav"
    shutil.copy2(fp, dst)
    print(f"-> {dst.name} {dst.stat().st_size/1e6:.0f} MB", flush=True)
finally:
    run(f"song.tracks[{CAP}].arm = 0; result='disarmed'")
print("DONE")
