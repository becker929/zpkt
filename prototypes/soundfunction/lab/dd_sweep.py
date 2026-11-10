"""LFOTool depth sweep under DawDreamer: transport on, 160 BPM, VST2 build.

pedalboard could load the state but not run the LFO (no transport). DawDreamer
runs the transport but its load_state does not accept the raw .als Buffer. So
the state comes from pedalboard's dump: every parameter is set by name on the
DawDreamer instance and read back before anything is rendered.
"""
import json, re, sys, subprocess
from pathlib import Path
import numpy as np, soundfile as sf, dawdreamer as daw

SR=44100; BPM=160.0
VST="/Library/Audio/Plug-Ins/VST/LFOTool.vst"
IN=Path("stems/hw002_bypass/aligned__03__rumble__lfotool-off.wav")
KICK=Path("stems/hw002_bypass/aligned__02__kick.wav")
OUT=Path("out/dd_sweep"); OUT.mkdir(exist_ok=True)
dump=json.load(open("out/lfotool_state/rumble_state_dump.json"))
norm=lambda s: re.sub(r"[^a-z0-9]","",s.lower())

eng=daw.RenderEngine(SR,512); eng.set_bpm(BPM)
p=eng.make_plugin_processor("lfo",VST)
names={norm(p.get_parameter_name(i)):(i,p.get_parameter_name(i)) for i in range(p.get_plugin_parameter_size())}
missing=[k for k in dump if norm(k) not in names]
for k,v in dump.items():
    if norm(k) in names: p.set_parameter(names[norm(k)][0], float(v["raw"]))
bad=[(k,dump[k]["raw"],p.get_parameter(names[norm(k)][0])) for k in dump if norm(k) in names and abs(p.get_parameter(names[norm(k)][0])-dump[k]["raw"])>1e-3]
unset=[n for k,(i,n) in names.items() if k not in {norm(d) for d in dump}]
print(f"state set from dump: {len(dump)-len(missing)}/{len(dump)} params; dump keys unmatched={missing}; host params left unset={unset}; readback mismatches={bad}", flush=True)
if bad: sys.exit("state did not apply cleanly: read-back mismatch")
if missing: print("WARNING: continuing; unmatched names above are recorded in the sidecars", flush=True)
D=names[norm("lfo_depth")][0]

y,_=sf.read(str(IN),dtype='float32',always_2d=True)
pb=eng.make_playback_processor("in", y.T.astype(np.float32))
eng.load_graph([(pb,[]),(p,["in"])])
secs=len(y)/SR
values=[i/12 for i in range(13)]
for v in values:
    p.set_parameter(D, v)
    eng.render(secs); out=eng.get_audio().T[:len(y)]
    tag=f"rumble_lfotool_depth_dd__lfo_depth__{v:.6f}"
    sf.write(str(OUT/f"{tag}.wav"), out, SR, subtype="PCM_24")
    side={"plugin":VST,"host":"dawdreamer "+getattr(daw,"__version__","?"),"bpm":BPM,"transport":"playing",
          "input":str(IN),"param":"LFO Depth","value":v,
          "parameters":{p.get_parameter_name(i):p.get_parameter(i) for i in range(p.get_plugin_parameter_size())}}
    (OUT/f"{tag}.params.json").write_text(json.dumps(side,indent=1))
    e=lambda x: 20*np.log10(np.sqrt(np.convolve((x.mean(1))**2,np.ones(882)/882,'same'))+1e-12)
    ein,eout=e(y[:SR*30]),e(out[:SR*30])
    print(f"depth {v:.3f}: env swing in {np.percentile(ein,95)-np.percentile(ein,5):5.1f} dB -> out {np.percentile(eout,95)-np.percentile(eout,5):5.1f} dB", flush=True)
print("RENDER DONE; measuring", flush=True)
(OUT/"bypass_json").mkdir(exist_ok=True)
for w in sorted(OUT.glob("rumble_lfotool_depth_dd__*.wav")):
    r=subprocess.run([".venv/bin/python","lab/duck_calibration.py","bypass","--kick",str(KICK),"--bass",str(w),"--bypass",str(IN),"--out",str(OUT/"bypass_json"/(w.stem+".json"))],capture_output=True,text=True)
    print(("measured " if r.returncode==0 else "FAILED ")+w.stem, flush=True)
print("SWEEP DONE")
