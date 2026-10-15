"""Make the map checklist's check sounds in Live: build the set, render each variant, encode for the page.

  cd hands && uv run python scripts/ui_sounds/make.py build             # in a new, empty Live set (File > New Live Set)
  cd hands && uv run python scripts/ui_sounds/make.py render anvil      # its hit, strong and land, one export each
  cd hands && uv run python scripts/ui_sounds/make.py render anvil hit  # just one
  cd hands && uv run python scripts/ui_sounds/make.py measure           # onset, peak, tail, loudness of each render
  cd hands && uv run python scripts/ui_sounds/make.py encode            # renders -> .m4a, named by content, + the manifest
  cd hands && uv run python scripts/ui_sounds/make.py upload            # the .m4a files -> R2 (wrangler's login)

The sounds are stock Live devices only (Operator, Saturator, Echo, Delay, Drum Buss, Glue Compressor, Limiter), no
samples. Settings are in variants.py. Renders go to <data_dir>/ui_sounds (hands.config). Audio never goes in git: encode
writes <data_dir>/ui_sounds/web/<id>-<kind>-<hash>.m4a, each cut where the render stays under -80 dBFS (nothing
audible is cut; no fade, no gain), and the manifest naming them, lib/harness/.../checklist/map/sounds.json; upload
puts the files in R2 at audio/zpkt/check-sounds/, where the harness fetches them once (its check_sound route). The
Limiter's ceiling is -3.5 dB so AAC's overshoot never reaches full scale.

Each Live step is checked: no dialog before an export, every parameter found. Keep runs short and supervised
(docs: hands README; a lost reply or a dialog stops the run). Live 11+ note calls only: the legacy set_notes and
remove_notes raise a hidden "older process to modify MIDI notes" prompt that blocks the LOM.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from variants import BASE, VARIANTS, merge, strong

from hands import config
from hands.live import render, ui
from hands.live.transport import LiveClient

LIVE = LiveClient()
ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "lib/harness/src/harness/studio/static/checklist/map/sounds.json"
BUCKET = "anthonybecker-audio/audio/zpkt/check-sounds"
OUT = config.rig().data_dir / "ui_sounds"        # not under ~/Music: a Save panel there asks for Apple Music access
KINDS = ("hit", "strong", "land")
BEATS = {"thunder": (8, 8), "vault": (3, 6)}       # hit and strong render lengths at 120 BPM, long enough for the tail

# Set a parameter in its display units: a binary search over str_for_value (the LOM only takes raw values).
HELPER = r'''
import re
def _num(s):
    m = re.match(r"\s*(-?inf|-?[\d.]+)\s*(k?Hz|ms|s|dB|%)?", s)
    if not m: return None
    v = -1e9 if 'inf' in m.group(1) else float(m.group(1))
    return v * (1000 if (m.group(2) or '') in ('s', 'kHz') else 1)
def _set(d, name, want):
    ps = [p for p in d.parameters if p.name == name]
    if not ps: return name + '?'
    p = ps[0]
    if isinstance(want, str) and p.is_quantized:
        p.value = float(list(p.value_items).index(want)); return None
    if isinstance(want, str):
        t = _num(want); lo, hi = p.min, p.max
        for _ in range(40):
            mid = (lo + hi) / 2
            if _num(p.str_for_value(mid)) < t: lo = mid
            else: hi = mid
        p.value = hi; return None
    p.value = float(want); return None
'''


def dev(track, idx: int) -> str:
    if track == "master":
        return f"song.master_track.devices[{idx}]"
    if isinstance(track, str) and track.startswith("ret"):
        return f"song.return_tracks[{int(track[3:])}].devices[{idx}]"
    return f"song.tracks[{track}].devices[{idx}]"


def setp(track, idx: int, params: dict) -> None:
    """Set a device's parameters, 18 to a call (each call well under the LOM's 12 s)."""
    items = list(params.items())
    for k in range(0, len(items), 18):
        code = HELPER + f"d = {dev(track, idx)}\nbad = []\n" + "".join(
            f"bad.append(_set(d, {n!r}, {v!r}))\n" for n, v in items[k:k + 18]) + "result = [b for b in bad if b]"
        missing = LIVE.run(code)
        if missing:
            sys.exit(f"STOP: {dev(track, idx)} has no {missing}")


def load(track: str, kind: str, name: str) -> None:
    LIVE.run(f"load_to({track}, browser.{kind}, {name!r})\ntime.sleep(0.4)\nresult = 'requested'")
    time.sleep(1)


def build() -> None:
    """From Live's default new set (two MIDI tracks, two audio, returns A-Reverb and B-Delay)."""
    names = LIVE.run("result = [t.name for t in song.tracks] + [r.name for r in song.return_tracks]")
    if len(names) != 6 or not names[-1].endswith("Delay"):
        sys.exit(f"STOP: not a new default set: {names}")
    LIVE.run("song.tracks[0].name = 'Body'\nsong.tracks[1].name = 'Click'\nsong.create_midi_track(2)\nresult = 'ok'")
    LIVE.run("song.tracks[2].name = 'Splash'\nsong.delete_track(4)\nresult = 'ok'")
    LIVE.run("song.delete_track(3)\nsong.tempo = 120.0\nresult = 'ok'")
    for i in range(3):
        load(f"song.tracks[{i}]", "instruments", "Operator")
    load("song.tracks[0]", "audio_effects", "Saturator")
    load("song.tracks[2]", "audio_effects", "Echo")
    for name in ("Drum Buss", "Glue Compressor", "Limiter"):
        load("song.master_track", "audio_effects", name)
    devices = LIVE.run("result = [[d.name for d in t.devices] for t in list(song.tracks) + [song.master_track]]")
    want = [["Operator", "Saturator"], ["Operator"], ["Operator", "Echo"], ["Drum Buss", "Glue Compressor", "Limiter"]]
    if devices != want:
        sys.exit(f"STOP: devices {devices}")
    # what the variants never change: each layer's oscillators, envelopes' shapes and filters' kinds
    setp(0, 0, {"Osc-A Wave": "Sine", "Ae Attack": 0.0, "Ae Sustain": 0.0, "Ae Release": "60 ms", "Pe On": "On",
                "Pe Attack": 0.0, "Pe Sustain": 0, "Pe End": 0, "Pe Amount": 1.0, "Shaper Type": "Soft", "Shaper Drive": 6,
                "Filter Freq": "2.69 kHz"})
    setp(1, 0, {"Algorithm": "Alg. 11", "Osc-A Wave": "Noise White", "Ae Attack": 0.0, "Ae Sustain": 0.0,
                "Ae Release": "5 ms", "Filter Type": "Highpass", "Filt < Key": 0})
    setp(2, 0, {"Algorithm": "Alg. 1", "Osc-A Wave": "Sine", "Ae Attack": 0.0, "Ae Sustain": 0.0, "Ae Release": "80 ms",
                "Be Attack": 0.0, "Be Sustain": 0.1, "Filt < Key": 0})
    setp(0, 1, {"Output": "-4 dB"})
    setp(2, 1, {"L Sync": "On", "Link": "On", "Channel Mode": "Ping Pong"})
    setp("ret1", 0, {"Ping Pong": "On", "Link": "On", "Filter On": "On", "Filter Width": "6"})
    setp("master", 0, {"Compressor On": "On"})
    LIVE.run("for i in range(3):\n    song.tracks[i].create_midi_clip(0.0, 4.0)\nresult = 'ok'")
    print("built: Body, Click, Splash; Echo, Delay return; Drum Buss, Glue Compressor, Limiter on Main")


def apply(s: dict, *, land: bool = False) -> None:
    b, c, p, e, d, u, g = (s[k] for k in ("body", "click", "splash", "echo", "delay", "buss", "glue"))
    setp(0, 0, {"Volume": b["vol"], "Ae Decay": b["decay"], "Pe Peak": b["pe"], "Pe Init": b["pe"], "Pe Decay": b["pe_decay"],
                "Osc-A Feedb": b["feedb"]})
    setp(0, 1, {"Drive": b["sat"], "Type": b["sat_type"]})
    setp(1, 0, {"Volume": c["vol"], "Ae Decay": c["decay"], "Filter Freq": c["hp"], "Filter Res": c["res"]})
    setp(2, 0, {"Volume": p["vol"], "Ae Decay": p["decay"], "Osc-B Level": p["b_level"], "Osc-B Wave": p["b_wave"],
                "B Coarse": p["b_coarse"], "Be Decay": p["b_decay"], "Filter Type": p["ftype"], "Filter Freq": p["freq"],
                "Filter Res": p["res"]})
    setp(2, 1, {"L Synced": e["sync"], "L Sync Mode": e["mode"], "Feedback": e["fb"], "Dry Wet": e["wet"],
                "HP Freq": e["hp"], "LP Freq": e["lp"]})
    setp("ret1", 0, {"L 16th": d["16th"], "Feedback": d["fb"], "Filter Freq": d["freq"]})
    setp("master", 0, {"Drive": u["drive"], "Drive Type": u["type"], "Crunch": u["crunch"], "Transients": u["trans"],
                       "Boom Amt": u["boom"], "Boom Freq": u["boom_f"], "Boom Decay": u["boom_d"]})
    setp("master", 1, {"Threshold": g["thr"], "Ratio": g["ratio"], "Attack": g["attack"], "Release": g["release"],
                       "Output": g["out"]})
    lim = float(g["lim"].split()[0])
    setp("master", 2, {"Input Gain": f"{min(0.0, lim) - 12 if land else lim} dB", "Ceiling": "-3.5 dB"})
    vel = 70.0 if land else 120.0
    notes = ((b["note"], 0.5, vel), (60, 0.1, vel - 5), (p["note"], 0.25, vel - 10))
    LIVE.run(f"""import Live
song.tracks[2].mute = {land}
song.tracks[1].mixer_device.sends[1].value = {0.0 if land else d['click']}
song.tracks[2].mixer_device.sends[1].value = {d['splash']}
for i, (pitch, dur, v) in enumerate({notes!r}):
    c = song.tracks[i].arrangement_clips[0]
    c.remove_notes_extended(0, 128, 0.0, 4.0)
    c.add_new_notes((Live.Clip.MidiNoteSpecification(pitch=pitch, start_time=0.0, duration=dur, velocity=float(v)),))
result = 'ok'""")


def render_one(name: str, kind: str) -> Path:
    s = merge(BASE, VARIANTS[name][2])
    if kind == "strong":
        s = strong(s)
    apply(s, land=kind == "land")
    if ui.dialogs():
        sys.exit("STOP: a Live dialog is open")
    hit, heavy = BEATS.get(name, (3, 4))
    out = OUT / f"{name}-{kind}.wav"
    if out.exists():                                   # Live will not export over a file; keep the old one aside
        old = OUT / "old"
        old.mkdir(parents=True, exist_ok=True)
        out.rename(old / f"{int(time.time())}-{out.name}")
    (written,) = render.export(LIVE, out, 0, {"hit": hit, "strong": heavy, "land": 2}[kind], bits=24)
    return written


def measure(paths) -> None:
    import numpy as np
    import soundfile as sf
    for p in paths:
        y, sr = sf.read(p)
        a = np.abs(y).max(axis=1)
        peak = a.max()
        on = int(np.argmax(a > peak * 0.05))
        quiet = np.where(a > 10 ** (-60 / 20))[0].max() / sr
        rms = 20 * np.log10(np.sqrt((y.mean(axis=1)[on:on + int(0.3 * sr)] ** 2).mean()) + 1e-9)
        print(f"{Path(p).name:22s} peak {20 * np.log10(peak):5.1f} dBFS  onset {on / sr * 1000:4.1f} ms"
              f"  above -60 dBFS for {quiet:4.2f} s  rms(300 ms) {rms:5.1f} dB")


def encode() -> None:
    import hashlib

    import numpy as np
    import soundfile as sf
    web = OUT / "web"
    web.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in VARIANTS:
        for kind in KINDS:
            y, sr = sf.read(OUT / f"{name}-{kind}.wav")
            a = np.abs(y).max(axis=1)
            y = y[:np.where(a > 10 ** (-80 / 20))[0].max() + int(0.01 * sr)]    # where it stays under -80 dBFS
            wav, m4a = web / f"{name}-{kind}.wav", web / f"{name}-{kind}.m4a"
            sf.write(wav, y, sr, subtype="PCM_16")
            m4a.unlink(missing_ok=True)
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "160000", str(wav), str(m4a)], check=True)
            named = web / f"{name}-{kind}-{hashlib.sha256(m4a.read_bytes()).hexdigest()[:8]}.m4a"
            m4a.replace(named)
            manifest.setdefault(name, {})[kind] = named.name
            print(named.name, f"{len(y) / sr:.2f} s", f"{named.stat().st_size // 1024} KB")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(MANIFEST.relative_to(ROOT))


def upload() -> None:
    """Each file the manifest names, to R2 (immutable: a new render is a new name)."""
    web = OUT / "web"
    for kinds in json.loads(MANIFEST.read_text()).values():
        for file in kinds.values():
            subprocess.run(["npx", "--yes", "wrangler", "r2", "object", "put", f"{BUCKET}/{file}", "--file", str(web / file),
                            "--content-type", "audio/mp4", "--cache-control", "public, max-age=31536000, immutable",
                            "--remote"], check=True)


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    if cmd == "build":
        build()
    elif cmd == "render":
        for kind in rest[1:] or KINDS:
            print(render_one(rest[0], kind))
            measure([OUT / f"{rest[0]}-{kind}.wav"])
    elif cmd == "measure":
        measure(sorted(OUT.glob("*-*.wav")))
    elif cmd == "encode":
        encode()
    elif cmd == "upload":
        upload()
    elif cmd == "list":
        print(json.dumps({k: v[:2] for k, v in VARIANTS.items()}, indent=1))
    else:
        print(__doc__)
