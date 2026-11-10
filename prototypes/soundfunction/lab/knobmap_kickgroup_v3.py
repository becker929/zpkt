"""Knob map, HW002 kick group: ten rows, 13 steps each, on the rig.

Per step: set one parameter on one group device over Path B (write), read it
back in a separate call, loop-record 8 bars of the real arrangement tapped
from the group bus into the capture track, copy the clip out, write a
sidecar. Restore the parameter after its row and verify. Resumable: a step
with wav + sidecar is skipped. Crash rules: write and read are separate
calls, one device per call, no long sleeps inside a call.

The bus is kick + rumble (rumble with LFOTool on). Every sidecar says so: a
row here is about the group as heard, not a solo kick.
"""
import json, shutil, sys, time, wave, math, audioop
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, "/Users/anthonybecker/.agents/skills/ableton-live-control/scripts")
from live_mcp import LiveMcp

GROUP, CAP = 1, 18
LOOP_START, LOOP_BEATS, SETTLE = 0.0, 32.0, 1.5
OUT = Path("out/knobmap_hw002_kickgroup_v3_roar_on"); OUT.mkdir(parents=True, exist_ok=True)
ROWS = [  # v3: what Roar would do. Roar's Device On is 0 in the set; it is FORCED ON for these rows and restored.
    ("roar_drive_on", 1, 1, "Drive"), ("roar_tone_amt_on", 1, 2, "Tone Amt"), ("roar_blend_on", 1, 5, "Blend"),
]
HOLD = (1, 0, "Device On", 1.0)   # (device, param, name, value) held for every row, restored at the end
STEPS = 13
live = LiveMcp()
def run(code):
    r = live.execute(code)
    if r.status != "ok": raise RuntimeError(f"MCP error:\n{code}\n-> {r.error}")
    return r.result
def P(di, pi): return f"song.tracks[{GROUP}].devices[{di}].parameters[{pi}]"
def peak_dbfs(p):
    with wave.open(str(p), "rb") as w:
        mx = 0; n = w.getnframes(); sw = w.getsampwidth(); ch = w.getnchannels()
        while n > 0:
            fr = w.readframes(min(1 << 20, n)); n -= len(fr) // (sw * ch)
            if not fr: break
            mx = max(mx, audioop.max(fr, sw))
    return -math.inf if mx == 0 else 20 * math.log10(mx / float(1 << (8 * sw - 1)))

tempo = float(run("result = song.tempo"))
assert run(f"result = song.tracks[{GROUP}].name") == "kick group"
assert run(f"result = song.tracks[{CAP}].name") == "STEM_CAP"
bus = run(f"result = {{'members': [{{'index': i, 'name': t.name, 'mute': bool(t.mute)}} for i, t in enumerate(song.tracks) if t.group_track and t.group_track.name == 'kick group'],"
          f" 'rumble_lfotool_on': song.tracks[3].devices[4].parameters[0].value,"
          f" 'group_devices': [{{'index': i, 'name': d.name, 'class_name': d.class_name, 'on': d.parameters[0].value}} for i, d in enumerate(song.tracks[{GROUP}].devices)]}}")
saved = run("result = {'loop': song.loop, 'loop_start': song.loop_start, 'loop_length': song.loop_length}")
print(f"tempo={tempo} bus={[m['name'] for m in bus['members']]} lfotool_on={bus['rumble_lfotool_on']} saved_loop={saved}", flush=True)

run(f"tr = song.tracks[{CAP}]\n_rt = next(r for r in tr.available_input_routing_types if r.display_name == 'kick group')\n"
    f"tr.input_routing_type = _rt\ntr.arm = 1\ntr.current_monitoring_state = 1\nresult = tr.input_routing_type.display_name")
run(f"song.loop_start = {LOOP_START}\nsong.loop_length = {LOOP_BEATS}\nsong.loop = 1\nresult = 'loop set'")
hold_orig = float(run(f"result = {P(HOLD[0],HOLD[1])}.value"))
run(f"{P(HOLD[0],HOLD[1])}.value = {HOLD[3]}"); time.sleep(0.5)
assert abs(float(run(f"result = {P(HOLD[0],HOLD[1])}.value")) - HOLD[3]) < 1e-4
print(f"HOLD {HOLD[2]}: {hold_orig:.4f} -> {HOLD[3]}", flush=True)

def bounce(out_wav):
    run(f"tr = song.tracks[{CAP}]\n[tr.delete_clip(c) for c in list(tr.arrangement_clips)]\nresult='cleared'")
    run(f"song.back_to_arranger = 0\nsong.current_song_time = {LOOP_START}\nsong.record_mode = 1\nsong.start_playing()\nresult='go'")
    time.sleep(LOOP_BEATS / tempo * 60.0 + SETTLE)
    run("song.record_mode = 0; song.stop_playing(); result='stop'")
    time.sleep(0.8)
    fp = run(f"acs = list(song.tracks[{CAP}].arrangement_clips)\nresult = acs[0].file_path if acs else None")
    if not fp or not Path(fp).exists(): return False
    shutil.copy2(fp, out_wav); return True

try:
    for row, di, pi, pname in ROWS:
        rdir = OUT / row; rdir.mkdir(exist_ok=True)
        meta = run(f"p = {P(di,pi)}\nresult = {{'name': p.name, 'min': p.min, 'max': p.max, 'value': p.value, 'device': song.tracks[{GROUP}].devices[{di}].name}}")
        assert meta["name"] == pname, meta
        orig, lo, hi = meta["value"], meta["min"], meta["max"]
        values = [lo + (hi - lo) * i / (STEPS - 1) for i in range(STEPS)]
        print(f"[{row}] {meta['device']}/{pname} orig={orig:.4f} range=({lo},{hi})", flush=True)
        try:
            for v in values:
                tag = f"{row}__{v:.6f}"; wav = rdir / f"{tag}.wav"; side = rdir / f"{tag}.params.json"
                if wav.exists() and side.exists(): print(f"  skip {v:.4f} (exists)", flush=True); continue
                run(f"{P(di,pi)}.value = {v}"); time.sleep(0.5)
                got = float(run(f"result = {P(di,pi)}.value"))
                if abs(got - v) > 1e-3 * max(1.0, hi - lo): print(f"  WARN set {v:.5f} read {got:.5f}", flush=True)
                ok = False
                for attempt in (1, 2):
                    if bounce(wav) and peak_dbfs(wav) > -60: ok = True; break
                    print(f"  attempt {attempt} dead, retrying", flush=True)
                if not ok: raise RuntimeError(f"{tag}: bounce failed twice")
                side.write_text(json.dumps(dict(row=row, device=meta["device"], device_index=di, param=pname, param_index=pi,
                    value_set=v, value_read=got, original_value=orig, param_min=lo, param_max=hi, tempo=tempo,
                    loop_start_beats=LOOP_START, loop_beats=LOOP_BEATS, capture_track=CAP, tap="kick group (bus output)",
                    bus=bus, held={HOLD[2]: HOLD[3], "original": hold_orig},
                    note="Row is about the kick group bus as heard: kick + rumble, rumble's LFOTool on. Not a solo kick. Roar Device On FORCED to 1 for this row; in Anthony's set it is 0 (bypassed). Not Anthony's setting.",
                    source_set="/Users/anthonybecker/_agent_scratch/HW002_rumble_bypass/HW002_14.als",
                    wav=wav.name, peak_dbfs=round(peak_dbfs(wav), 2), timestamp_utc=datetime.now(timezone.utc).isoformat()), indent=1))
                print(f"  {v:.4f} -> {wav.name} peak {peak_dbfs(wav):.1f}", flush=True)
        finally:
            run(f"{P(di,pi)}.value = {orig}"); time.sleep(0.5)
            back = float(run(f"result = {P(di,pi)}.value"))
            print(f"  restored {pname} -> {back:.5f} (orig {orig:.5f}) {'OK' if abs(back-orig)<1e-4 else 'MISMATCH'}", flush=True)
finally:
    run(f"{P(HOLD[0],HOLD[1])}.value = {hold_orig}"); time.sleep(0.5)
    print(f"HOLD restored {HOLD[2]} -> {float(run(f'result = {P(HOLD[0],HOLD[1])}.value')):.4f} (orig {hold_orig:.4f})", flush=True)
    run(f"song.loop = {int(bool(saved['loop']))}\nsong.loop_start = {saved['loop_start']}\nsong.loop_length = {saved['loop_length']}\nresult='loop restored'")
    run(f"song.tracks[{CAP}].arm = 0; result='disarmed'")
    print("loop restored, capture disarmed", flush=True)
print("RIG DONE", flush=True)
