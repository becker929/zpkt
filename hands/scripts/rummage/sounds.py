"""The Rummage's interface sounds, made in Live like SH001 (docs/sound.md: interface sounds are rendered files).

  cd hands && uv run python scripts/rummage/sounds.py new        # File > New Live Set, saved as SH001_ui (no keys)
  cd hands && uv run python scripts/rummage/sounds.py build      # tracks, instruments, pads, notes, mix, Main
  cd hands && uv run python scripts/rummage/sounds.py render     # one export of every slot -> renders/ui/all.wav
  cd hands && uv run python scripts/rummage/sounds.py cut        # slice, trim, fade -> renders/ui/<name>.wav + stats
  cd hands && uv run python scripts/rummage/sounds.py encode     # -> ui-<name>-<hash8>.m4a + rummage/sounds.json

Paper, tin, wood, brass and found objects: Core Library samples on a Drum Rack (one-shots), two Simplers on a paper
rustle (a whoosh and a rip, with the pitch envelope and filter a pad's Simpler lacks), a music box and a tin bell
in D, a warm pad for the finish, and an Operator thump. Main: EQ Eight (high-pass 130 Hz, a cut above 8 kHz: the
energy where a phone speaker has it), Glue Compressor, Limiter (True Peak, ceiling -3.5 dB).

Every sound has its own slot of SLOT beats at 120 BPM, so one export renders them all; `cut` slices the slots, trims
each where it stays under -60 dBFS (plus 30 ms), fades the last 20 ms and checks the peak (at most -3 dBFS). Audio
never goes in git; the .m4a files are added beside SH001's in ~/_agent_scratch/studio/regions/rummage/audio/.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SET_NAME = "SH001_ui"
os.environ.setdefault("ZPKT_SETS_DIR", str(Path(f"~/_agent_scratch/rummage/set/{SET_NAME} Project").expanduser()))
sys.path.insert(0, str(Path(__file__).parent))
import liveops as L  # noqa: E402  (after the rig environment above)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "lib/harness/src/harness/studio/static/checklist/rummage/sounds.json"
OUT = L.SCRATCH / "renders" / "ui"
WEB = Path("~/_agent_scratch/studio/regions/rummage/audio").expanduser()
BPM = 120.0
SLOT = 12.0                                   # beats per sound (6 s): room for the finish's tail
GATE = {"Trigger Mode": "Gate"}

# ---- the instruments ----------------------------------------------------------------------------------------------
PADS = {   # the found objects: note -> (Core Library sample, its Simpler's settings)
    36: ("Paper LDre.wav", {**GATE, "S Start": "12 %", "Ve Attack": "1 ms", "Ve Decay": "60 ms", "Ve Sustain": "-36 dB",
                            "Ve Release": "40 ms", "Transpose": "-5 st"}),                       # a step, three ways
    37: ("Paper LDre.wav", {**GATE, "S Start": "41 %", "Ve Attack": "1 ms", "Ve Decay": "55 ms", "Ve Sustain": "-36 dB",
                            "Ve Release": "40 ms", "Transpose": "-7 st"}),
    38: ("Paper LDre.wav", {**GATE, "S Start": "66 %", "Ve Attack": "1 ms", "Ve Decay": "70 ms", "Ve Sustain": "-36 dB",
                            "Ve Release": "40 ms", "Transpose": "-4 st"}),
    41: ("Wood Under The Rug.wav", {"Transpose": "-3 st"}),                                     # the felt under it
    42: ("Foley Door Lock.wav", {}),                                                            # the latch
    43: ("E-Perc Spring.wav", {**GATE, "Ve Release": "220 ms"}),                                # its spring
    44: ("Wood Resonant Knock.wav", {}),                                                        # the plinth's wood
    45: ("Kick Door.aif", {**GATE, "Ve Release": "180 ms", "Volume": "-8 dB"}),                  # a heavy door's body
    46: ("Impact Short Metal.wav", {"Volume": "-8 dB"}),                                        # the slam's metal
    47: ("Metallic Rattle.wav", {"Volume": "-8 dB"}),                                           # tin rattling
    48: ("Perc Knock Rattle.wav", {}),                                                          # one ratchet tooth
    49: ("Click Vinyl.wav", {}),                                                                # the needle
    50: ("Crackle Tuning.wav", {**GATE, "Ve Release": "300 ms"}),                                # the groove's crackle
    51: ("Tamb Metal.wav", {}),                                                                 # loose tin
    52: ("Wood Tip Tag.wav", {"Volume": "-20 dB"}),                                             # a detent
    53: ("Snare Box Slap.aif", {}),                                                             # a rubber stamp
    54: ("E-Perc Scrape Shake.wav", {"Transpose": "+5 st"}),                                    # fibres giving
    55: ("Clap Foley.aif", {"Transpose": "+3 st"}),                                             # the paper parts
}
TRACKS = [
    {"name": "found", "src": ("instruments", None, "Drum Rack"), "pads": PADS, "vol": 0.0, "send": -18},
    {"name": "whoosh", "src": ("samples", None, "Paper LDre.wav"), "fx": ["Utility"], "vol": 0.0, "send": -14,
     "set": {0: {**GATE, "Snap": "Off", "S Start": "20 %", "Ve Attack": "25 ms", "Ve Decay": "180 ms",
                 "Ve Sustain": "-10 dB", "Ve Release": "90 ms", "Pe < Env": "9 st", "Pe Attack": "120 ms",
                 "Pe Decay": "300 ms", "Pe Sustain": "0 %", "Transpose": "2 st", "Vol < Vel": "20 %"},
             1: {"Output": "20 dB"}}},
    {"name": "rip", "src": ("samples", None, "Paper LDre.wav"), "fx": ["Utility"], "vol": 0.0, "send": -20,
     "set": {0: {**GATE, "Snap": "Off", "S Start": "46 %", "Ve Attack": "8 ms", "Ve Decay": "600 ms",
                 "Ve Sustain": "-8 dB", "Ve Release": "60 ms", "Pe < Env": "5 st", "Pe Attack": "700 ms",
                 "Pe Decay": "200 ms", "Pe Sustain": "100 %", "Transpose": "3 st", "Vol < Vel": "10 %",
                 "Volume": "0 dB"},
             1: {"Output": "15 dB"}}},
    {"name": "chime", "src": ("sounds", "Piano & Keys", "Music Box.adg"), "fx": ["Utility"], "vol": 0.0, "send": -12,
     "set": {1: {"Output": "14 dB"}}},
    {"name": "bell", "src": ("sounds", "Mallets", "Tin Bell.adg"), "vol": -4.0, "send": -14},
    {"name": "swell", "src": ("sounds", "Pad", "Organic Lo-Fi Pad.adv"), "vol": -4.0, "send": -12},
    {"name": "body", "src": ("instruments", None, "Operator"), "fx": ["Saturator"], "vol": -6.0, "send": None,
     "set": {0: {"Osc-A Wave": "Sine", "Ae Attack": 0.0, "Ae Decay": "180 ms", "Ae Sustain": 0.0, "Ae Release": "60 ms",
                 "Pe On": "On", "Pe Amount": 1.0, "Pe Init": 14, "Pe Peak": 14, "Pe Decay": "45 ms", "Pe Sustain": 0,
                 "Pe End": 0, "Osc-A Feedb": 30},
             1: {"Type": "Medium Curve", "Drive": "8 dB", "Output": "-5 dB"}}},
]

# ---- the sounds: (track, beat in the slot, pitch, length in beats, velocity); 1 beat = 0.5 s -----------------------
D = {"D3": 50, "A3": 57, "D4": 62, "E4": 64, "A4": 69, "D5": 74, "A5": 81, "D6": 86, "A6": 93}
RATCHET = [0.0, 0.05, 0.09, 0.125, 0.155, 0.18]      # teeth, faster and faster (90 ms), into the slam at 0.2 (100 ms)
SOUNDS = {
    "step-1": [("found", 0.0, 36, 0.12, 70), ("found", 0.005, 41, 0.1, 54)],
    "step-2": [("found", 0.0, 37, 0.12, 64), ("found", 0.005, 41, 0.1, 48)],
    "step-3": [("found", 0.0, 38, 0.12, 74), ("found", 0.005, 41, 0.1, 58)],
    "pickup": [("whoosh", 0.0, 60, 0.5, 100), ("chime", 0.06, D["A5"], 1.0, 96), ("chime", 0.12, D["D6"], 1.5, 104),
               ("bell", 0.12, D["D5"], 0.8, 46)],
    "place": [("found", 0.0, 44, 0.3, 118), ("body", 0.0, D["D3"], 0.4, 100), ("bell", 0.008, D["D5"], 1.2, 88),
              ("bell", 0.012, D["A4"], 1.0, 56)],
    "open": [("found", 0.0, 42, 1.6, 112), ("found", 0.69, 45, 0.5, 74), ("body", 0.69, D["D3"], 0.3, 84),
             ("found", 0.74, 43, 1.3, 88)],
    "lever": [("found", b, 48, 0.04, 70 + 8 * i) for i, b in enumerate(RATCHET)] + [
              ("found", 0.2, 45, 0.6, 124), ("found", 0.2, 46, 0.6, 118), ("body", 0.2, 38, 0.5, 124),
              ("found", 0.22, 47, 0.5, 110), ("found", 0.28, 51, 0.3, 92), ("found", 0.5, 51, 0.3, 70),
              ("found", 0.66, 47, 0.5, 74), ("bell", 0.21, D["D4"], 1.6, 84), ("bell", 0.21, D["A4"], 1.2, 60)],
    "finish": [("found", 0.0, 49, 0.1, 118), ("found", 0.04, 50, 2.6, 96),
               ("swell", 0.3, D["D3"], 4.2, 92), ("swell", 0.3, D["A3"], 4.2, 86), ("swell", 0.3, D["D4"], 4.2, 84),
               ("swell", 0.3, D["E4"], 4.2, 78), ("chime", 2.2, D["A5"], 2.0, 70), ("chime", 2.32, D["D6"], 2.0, 78)],
    "tear": [("rip", 0.0, 60, 1.55, 110), ("found", 0.18, 54, 0.1, 50), ("found", 0.47, 54, 0.1, 62),
             ("found", 0.8, 54, 0.1, 74), ("found", 1.1, 54, 0.1, 84), ("found", 1.5, 55, 0.2, 92)],
    "tick": [("found", 0.0, 52, 0.1, 96)],
    "stamp": [("found", 0.0, 53, 0.2, 116), ("body", 0.0, D["D3"], 0.2, 70), ("found", 0.01, 41, 0.1, 90)],
}
NAMES = list(SOUNDS)
NAMED = {"step": ["step-1", "step-2", "step-3"]}   # sounds.json: a list per name (step has three)


def tix(name: str) -> int:
    return [t["name"] for t in TRACKS].index(name)


def T(name: str) -> str:
    return f"song.tracks[{tix(name)}]"


# ---- Live -----------------------------------------------------------------------------------------------------------
def new_set() -> None:
    """File > New Live Set (the front set must be saved: Live would ask), then Save As SH001_ui. No keystrokes."""
    from hands.live import ui
    if ui.menu_enabled("File", "Save Live Set"):
        sys.exit(f"STOP: {ui.front_title()} has unsaved changes; save it first")
    if not ui.menu("File", "New Live Set"):
        sys.exit("STOP: File > New Live Set stayed disabled")
    for _ in range(40):
        if ui.front_title() == "Untitled":
            break
        time.sleep(0.25)
    else:
        sys.exit(f"STOP: no new set in front ({ui.windows()})")
    time.sleep(1.0)
    if ui.dialogs():
        sys.exit(f"STOP: a dialog after New Live Set: {ui.windows()}")
    print(L.save_as(L.SCRATCH / "set", SET_NAME))


def build() -> None:
    L.guard("ui build")
    L.run(f"song.tempo = {BPM}\nresult = 'ok'")
    have = L.run("result = [(t.name, t.has_midi_input, len(t.devices)) for t in song.tracks]")
    for i in range(len(have) - 1, -1, -1):                          # drop Live's empty audio tracks
        if not have[i][1] and have[i][2] == 0:
            L.run(f"song.delete_track({i})\nresult = 'ok'")
    while len(L.run("result = [t.name for t in song.tracks]")) < len(TRACKS):
        L.run("song.create_midi_track(-1)\nresult = 'ok'")
    names = [t["name"] for t in TRACKS]
    L.run(f"for i, n in enumerate({names!r}):\n    song.tracks[i].name = n\nresult = 'ok'")
    got = L.run("result = [(t.name, t.has_midi_input) for t in song.tracks]")
    if [g[0] for g in got][:len(names)] != names or not all(g[1] for g in got[:len(names)]):
        sys.exit(f"STOP: tracks {got}")
    for t in TRACKS:                                                # instruments and effects
        path, (root, folder, item) = T(t["name"]), t["src"]
        devs = L.devices(path)
        if not devs:
            L.guard(f"load {t['name']}")
            L.load_item(path, root, folder, item)
            devs = L.devices(path)
        if not devs or devs[0] not in (item.rsplit(".", 1)[0], "Simpler"):
            sys.exit(f"STOP: {t['name']} has {devs}")
        for fx in t.get("fx", []):
            if fx not in devs[1:]:
                L.load_item(path, "audio_effects", None, fx)
                devs = L.devices(path)
        print(f"{t['name']:8s} {devs}")
        if root == "samples":
            L.run(f"s = {path}.devices[0]\ns.playback_mode = 0\nresult = 'ok'")
            L.run(f"s = {path}.devices[0]\ns.sample.warping = False\nresult = 'ok'")
    for t in TRACKS:                                                # samples onto the pads
        path, dr = T(t["name"]), f"{T(t['name'])}.devices[0]"
        for note, (sample, settings) in t.get("pads", {}).items():
            if not L.run(f"result = len({dr}.drum_pads[{note}].chains)"):
                L.select_track(path)
                L.run(f"""{dr}.view.selected_drum_pad = {dr}.drum_pads[{note}]
time.sleep(0.1)
it = [x for x in browser.samples.children if x.name == {sample!r}][0]
browser.load_item(it)
time.sleep(0.3)
result = 'requested'""")
                time.sleep(1.0)
            got = L.run(f"p = {dr}.drum_pads[{note}]\nresult = (p.name, len(p.chains))")
            if got != [sample.rsplit(".", 1)[0], 1]:
                sys.exit(f"STOP: pad {note} holds {got}, not {sample}")
            if settings:
                L.setp(f"{dr}.drum_pads[{note}].chains[0].devices[0]", settings)
        for k, values in t.get("set", {}).items():
            L.setp(f"{path}.devices[{k}]", values)
    notes()
    mix()


def notes() -> None:
    """One clip per track over all the slots."""
    from make import write_notes
    total = SLOT * len(SOUNDS)
    per = {t["name"]: [] for t in TRACKS}
    for k, name in enumerate(SOUNDS):
        for track, b, p, d, v in SOUNDS[name]:
            per[track].append((k * SLOT + b, p, d, v))
    for t in TRACKS:
        write_notes(T(t["name"]), per[t["name"]], beats=total)
        print(f"{t['name']:8s} {len(per[t['name']])} notes")


def mix() -> None:
    for t in TRACKS:
        L.mixer(T(t["name"]), t["vol"], (t["send"], None))
    L.setp("song.return_tracks[0].devices[0]", {"Decay Time": "700 ms", "Predelay": "6 ms", "Room Size": 40})
    devs = L.devices("song.master_track")
    for name in ("EQ Eight", "Glue Compressor", "Limiter"):
        if name not in devs:
            L.load_item("song.master_track", "audio_effects", None, name)
            devs = L.devices("song.master_track")
    if devs != ["EQ Eight", "Glue Compressor", "Limiter"]:
        sys.exit(f"STOP: Main has {devs}")
    L.setp("song.master_track.devices[0]", {"1 Filter Type A": "High Pass 48dB", "1 Frequency A": "130 Hz",
                                            "1 Filter On A": "On", "8 Filter Type A": "High Shelf",
                                            "8 Frequency A": "8000 Hz", "8 Gain A": "-6 dB", "8 Filter On A": "On"})
    L.setp("song.master_track.devices[1]", {"Threshold": "-10 dB", "Ratio": 0, "Attack": 4, "Release": 2, "Dry/Wet": 1.0})
    L.setp("song.master_track.devices[2]", {"Mode": "True Peak", "Ceiling": "-3.5 dB", "Lookahead": "3 ms",
                                            "Auto": "On", "Input Gain": "0 dB"})
    print(L.run("result = [(t.name, t.mixer_device.volume.str_for_value(t.mixer_device.volume.value)) for t in song.tracks]"))


def render() -> Path:
    out = OUT / "all.wav"
    if out.exists():
        out.rename(out.with_name(f"all-{int(time.time())}.wav"))
    L.run("for t in song.tracks:\n    t.mute = False\nresult = 'ok'")
    return L.export(out, 0.0, SLOT * len(SOUNDS))


# ---- offline: slice, trim, fade, check, encode ------------------------------------------------------------------------
def cut() -> dict:
    import numpy as np
    import soundfile as sf
    y, sr = sf.read(OUT / "all.wav", always_2d=True, dtype="float64")
    n = int(SLOT * 60 / BPM * sr)
    if abs(len(y) - n * len(SOUNDS)) > sr // 100:
        sys.exit(f"STOP: all.wav is {len(y) / sr:.2f} s, expected {n * len(SOUNDS) / sr:.2f}")
    stats = {}
    for k, name in enumerate(SOUNDS):
        x = y[k * n:(k + 1) * n]
        a = np.abs(x).max(axis=1)
        if a.max() < 10 ** (-50 / 20):
            sys.exit(f"STOP: {name} is silent")
        on = max(0, int(np.argmax(a > 10 ** (-60 / 20))) - int(0.002 * sr))
        end = int(np.where(a > 10 ** (-60 / 20))[0].max() + 0.03 * sr)
        z = x[on:min(end, len(x))].copy()
        if a[-int(0.05 * sr):].max() > 10 ** (-60 / 20):
            sys.exit(f"STOP: {name} still sounds at the end of its slot")
        f = int(0.02 * sr)
        z[-f:] *= np.linspace(1, 0, f)[:, None]
        pk = 20 * np.log10(np.abs(z).max())
        if pk > -3.0:
            sys.exit(f"STOP: {name} peaks at {pk:.1f} dBFS")
        sf.write(OUT / f"{name}.wav", z, sr, subtype="PCM_24")
        band = np.abs(np.fft.rfft(z.mean(axis=1))) ** 2
        fr = np.fft.rfftfreq(len(z), 1 / sr)
        mid = 10 * np.log10(band[(fr >= 150) & (fr <= 6000)].sum() / band.sum())
        stats[name] = {"seconds": round(len(z) / sr, 3), "peak": round(pk, 1), "onset_ms": round(on / sr * 1000, 1),
                       "rms": round(20 * np.log10(np.sqrt((z ** 2).mean())), 1), "in_150_6k": round(mid, 1)}
        print(f"{name:8s} {stats[name]}")
    return stats


def encode() -> None:
    from make import loudness
    WEB.mkdir(parents=True, exist_ok=True)
    work = OUT / "m4a"
    work.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in SOUNDS:
        wav, tmp = OUT / f"{name}.wav", work / f"{name}.m4a"
        tmp.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac_at", "-b:a", "160k", "-ar", "44100",
                        str(tmp)], check=True)
        tp = loudness(tmp).get("true_peak", 0.0)
        if tp > -1.0:
            sys.exit(f"STOP: {tmp.name} true peak {tp} dBTP")
        h = hashlib.sha256(tmp.read_bytes()).hexdigest()[:8]
        key = name.split("-")[0]
        named = WEB / f"ui-{key}-{h}.m4a"
        if not named.exists():
            tmp.replace(named)
        files.setdefault(key, []).append(named.name)
        print(f"{named.name}  true peak {tp:.1f} dBTP")
    MANIFEST.write_text(json.dumps(files, indent=2) + "\n")
    print(MANIFEST.relative_to(ROOT))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "new":
        new_set()
    elif cmd == "build":
        build()
    elif cmd == "notes":
        L.guard("ui notes")
        notes()
    elif cmd == "mix":
        L.guard("ui mix")
        mix()
    elif cmd == "render":
        L.guard("ui render")
        print(render())
    elif cmd == "cut":
        cut()
    elif cmd == "encode":
        encode()
    elif cmd == "save":
        from hands.live import session
        print("saved" if session.save(SET_NAME) else "nothing to save")
    else:
        print(__doc__)
