"""Make the Marrow cumbia in Live: build the set, render it (and each track alone), measure, encode.

  cd hands && uv run python scripts/marrow/newset.py               # once: a new, empty Live 12 set, MARROW_cumbia
  cd hands && uv run python scripts/marrow/make.py build [step]    # tracks | instruments | notes | mix | master
  cd hands && uv run python scripts/marrow/make.py save
  cd hands && uv run python scripts/marrow/make.py render [tag]    # the mix -> renders/marrow-cumbia[-tag].wav
  cd hands && uv run python scripts/marrow/make.py stems [names]   # each track alone through Main
  cd hands && uv run python scripts/marrow/make.py stems --raw     # ... with Main's dynamics off, and the raw mix
  cd hands && uv run python scripts/marrow/make.py measure [files] # length, peak, true peak, LUFS
  cd hands && uv run python scripts/marrow/make.py encode [tag]    # AAC 192k .m4a beside the WAV, checked

The arrangement is parts.py; the notes come from tab.py's local copy of the transcription. Live 12 Suite's own
instruments, kits and Core Library samples only. The set and the renders live under ~/_agent_scratch/marrow/ (never
~/Music); no audio and no transcription in git: this is a cover, for Anthony's ears, not for publishing.

Each Live step is checked as in SH001 (hands/scripts/rummage): hands' guard before it, a read-back after it, short LOM
calls, notes through add_new_notes, exports through liveops.export (no keystrokes).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ops  # noqa: E402  - the rig environment before hands
import parts as P  # noqa: E402
from ops import L  # noqa: E402

RENDERS = ops.SCRATCH / "renders"
SECONDS = P.BEATS * 60.0 / P.BPM
NAMES = [t["name"] for t in P.TRACKS]


def T(name: str) -> str:
    return f"song.tracks[{NAMES.index(name)}]"


# ---- build ---------------------------------------------------------------------------------------------------------------
def build_tracks() -> None:
    """Exactly one MIDI track per parts.TRACKS entry, in order and named (the new set's audio tracks go); tempo."""
    L.run(f"song.tempo = {P.BPM}\nsong.signature_numerator = 4\nsong.signature_denominator = 4\nresult = 'ok'")
    have = L.run("result = [(t.name, t.has_midi_input, len(t.devices)) for t in song.tracks]")
    for i in reversed(range(len(have))):
        name, midi, ndev = have[i]
        if not midi:
            if ndev:
                sys.exit(f"STOP: audio track {i} {name!r} has devices; build from a new set")
            L.run(f"song.delete_track({i})\nresult = 'ok'")
    while len(L.run("result = [t.name for t in song.tracks]")) < len(NAMES):
        L.run("song.create_midi_track(-1)\nresult = 'ok'")
    L.run(f"for i, n in enumerate({NAMES!r}):\n    song.tracks[i].name = n\nresult = 'ok'")
    got = L.run("result = ([(t.name, t.has_midi_input) for t in song.tracks], song.tempo)")
    if [n for n, _ in got[0]] != NAMES or not all(m for _, m in got[0]) or abs(got[1] - P.BPM) > 1e-6:
        sys.exit(f"STOP: tracks {got}")
    print("tracks:", got)


def build_instruments() -> None:
    """Each track's instrument (a preset or an empty Drum Rack) and effects, unless there; then the Drum Racks' pads
    (a Core Library sample each, with its Simpler settings); then parts.TRACKS[...]['set']."""
    for t in P.TRACKS:
        path = T(t["name"])
        devs = L.devices(path)
        root, folder, item = t["src"]
        want0 = item.rsplit(".", 1)[0]
        if not devs:
            L.guard(f"load {t['name']}")
            L.load_item(path, root, folder, item)
            devs = L.devices(path)
        if not devs or devs[0] != want0:
            sys.exit(f"STOP: {t['name']} has {devs}, expected {want0}")
        for fx in t["fx"]:
            if fx not in devs[1:]:
                L.load_item(path, "audio_effects", None, fx)
                devs = L.devices(path)
                if fx not in devs:
                    sys.exit(f"STOP: {t['name']}: {fx} did not load ({devs})")
        print(f"{t['name']:10s} {devs}")
    for t in P.TRACKS:
        build_pads(t)
    build_params()


def build_pads(t: dict) -> None:
    path = T(t["name"])
    dr = f"{path}.devices[0]"
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
        got = L.run(f"p = {dr}.drum_pads[{note}]\nresult = (p.name, [[d.name for d in c.devices] for c in p.chains])")
        if got[0] != sample.rsplit(".", 1)[0] or not got[1]:
            sys.exit(f"STOP: pad {note} of {t['name']} holds {got}, not {sample}")
        if settings:
            L.setp(f"{dr}.drum_pads[{note}].chains[0].devices[0]", settings)
        print(f"{t['name']:10s} pad {note}: {got[0]}")


def build_params() -> None:
    for t in P.TRACKS:
        for k, values in t.get("set", {}).items():
            L.setp(f"{T(t['name'])}.devices[{k}]", values)
            print(f"{t['name']:10s} dev {k}:", L.params(f"{T(t['name'])}.devices[{k}]", list(values)))


def write_notes(path: str, notes: list[tuple], beats: float = P.BEATS) -> None:
    """Replace the track's arrangement with one MIDI clip over the whole song holding `notes` (Live keeps one note
    per pitch and start: the louder, then longer, stays)."""
    best: dict = {}
    for b, p, d, v in notes:
        key = (int(p), round(float(b), 4))
        if key not in best or (v, d) > (best[key][3], best[key][2]):
            best[key] = (b, p, d, v)
    notes = sorted(best.values())
    L.run(f"""t = {path}
for c in list(t.arrangement_clips):
    t.delete_clip(c)
t.create_midi_clip(0.0, {float(beats)})
result = 'ok'""")
    for k in range(0, len(notes), 150):
        chunk = [(int(p), round(float(b), 4), round(float(d), 4), float(v)) for b, p, d, v in notes[k:k + 150]]
        L.run(f"""import Live
c = {path}.arrangement_clips[0]
c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v) for p, s, d, v in {chunk!r}))
result = 'ok'""")
    n = L.run(f"c = {path}.arrangement_clips[0]\nresult = (len(c.get_notes_extended(0, 128, 0.0, {float(beats)})), c.start_time, c.end_time)")
    if n[0] != len(notes) or n[1] != 0.0 or n[2] != float(beats):
        sys.exit(f"STOP: {path}: clip has {n}, expected {len(notes)} notes over 0-{beats}")


def build_notes(only: str | None = None) -> None:
    for t in P.TRACKS:
        if only and only != t["name"]:
            continue
        L.guard(f"notes {t['name']}")
        write_notes(T(t["name"]), t["notes"]())
        print(f"{t['name']:10s} notes written")


def build_mix() -> None:
    for t in P.TRACKS:
        L.mixer(T(t["name"]), t["vol"], t["sends"])
    print(L.run("result = [(t.name, t.mixer_device.volume.str_for_value(t.mixer_device.volume.value), "
                "[s.str_for_value(s.value) for s in t.mixer_device.sends]) for t in song.tracks]"))


def build_master() -> None:
    devs = L.devices("song.master_track")
    for name in ("EQ Eight", "Glue Compressor", "Limiter"):
        if name not in devs:
            L.load_item("song.master_track", "audio_effects", None, name)
            devs = L.devices("song.master_track")
    if devs != ["EQ Eight", "Glue Compressor", "Limiter"]:
        sys.exit(f"STOP: Main has {devs}")
    for k, values in P.RETURNS.items():
        L.setp(f"song.return_tracks[{k}].devices[0]", values)
        print(f"return {k}:", L.params(f"song.return_tracks[{k}].devices[0]", list(values)))
    for k, values in P.MASTER.items():
        L.setp(f"song.master_track.devices[{k}]", values)
        print(f"main {k}:", L.params(f"song.master_track.devices[{k}]", list(values)))


def set_mutes(on: set[str] | None) -> None:
    """Un-mute the tracks in `on` (all when None), mute the rest; read back."""
    mutes = [on is not None and n not in on for n in NAMES]
    L.run(f"for i, m in enumerate({mutes!r}):\n    song.tracks[i].mute = m\nresult = 'ok'")
    if L.run(f"result = [song.tracks[i].mute for i in range({len(mutes)})]") != mutes:
        sys.exit("STOP: the mutes did not take")


# ---- render, measure, encode -----------------------------------------------------------------------------------------------
def _fresh(out: Path) -> Path:
    if out.exists():
        old = out.parent / "old"
        old.mkdir(parents=True, exist_ok=True)
        out.rename(old / f"{int(time.time())}-{out.name}")
    return out


def render(tag: str = "") -> Path:
    out = _fresh(RENDERS / f"marrow-cumbia{'-' + tag if tag else ''}.wav")
    L.guard("render")
    set_mutes(None)
    t0 = time.time()
    L.export(out, 0.0, float(P.BEATS))
    s = check(out)
    print(f"{out.name}  {time.time() - t0:4.1f} s  {s['seconds']:.3f} s  peak {s['peak_dbfs']:.1f}  rms {s['rms_dbfs']:.1f}")
    return out


def main_dynamics(on: bool) -> None:
    """Main's Glue Compressor and Limiter on or off (off: stems that sum to the mix, for the masking measure)."""
    L.run(f"for d in list(song.master_track.devices)[1:3]:\n    d.parameters[0].value = {1.0 if on else 0.0}\nresult = 'ok'")
    got = L.run("result = [d.parameters[0].value for d in list(song.master_track.devices)[1:3]]")
    if got != [1.0 if on else 0.0] * 2:
        sys.exit(f"STOP: Main's dynamics did not turn {'on' if on else 'off'}: {got}")


def stems(names: list[str], raw: bool = False) -> list[Path]:
    """Each track alone through Main; raw: with Main's dynamics off, and the raw mix too (renders/raw/)."""
    folder = RENDERS / ("raw" if raw else "stems")
    outs = []
    if raw:
        main_dynamics(False)
    try:
        for name in names or NAMES:
            out = _fresh(folder / f"stem-{name}.wav")
            L.guard(f"stem {name}")
            set_mutes({name})
            L.export(out, 0.0, float(P.BEATS))
            outs.append(out)
        if raw and not names:
            set_mutes(None)
            outs.append(L.export(_fresh(folder / "mix.wav"), 0.0, float(P.BEATS)))
    finally:
        set_mutes(None)
        if raw:
            main_dynamics(True)
    return outs


def check(path: Path) -> dict:
    from hands import audio
    return audio.check_audio(path, seconds=SECONDS, tol_s=0.01, min_rms_dbfs=-60.0)


def loudness(path: Path) -> dict:
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], check=False, capture_output=True, text=True)
    tail = run.stderr[run.stderr.rfind("Summary:"):]
    val = {}
    for line in tail.splitlines():
        line = line.strip()
        for key, name in (("I:", "lufs"), ("LRA:", "lra"), ("Peak:", "true_peak")):
            if line.startswith(key):
                val[name] = float(line.split()[1])
    return val


def measure(paths) -> list[dict]:
    rows = []
    for p in paths:
        s = check(p)
        s.update(loudness(p))
        s["file"] = p.name
        rows.append(s)
        print(f"{p.name:28s} {s['seconds']:.3f} s  peak {s['peak_dbfs']:5.1f}  tp {s.get('true_peak', 0):5.1f} dBTP  "
              f"{s.get('lufs', float('nan')):6.1f} LUFS  LRA {s.get('lra', 0):4.1f}")
    return rows


def encode(tag: str = "") -> Path:
    wav = RENDERS / f"marrow-cumbia{'-' + tag if tag else ''}.wav"
    (row,) = measure([wav])
    out = wav.with_suffix(".m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac_at", "-b:a", "192k", "-ar", "44100",
                    "-movflags", "+faststart", str(out)], check=True)
    got = loudness(out)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(out)], capture_output=True, text=True, check=True).stdout)
    if abs(dur - SECONDS) > 0.05 or abs(got["lufs"] - row["lufs"]) > 0.3:
        sys.exit(f"STOP: {out.name} does not verify: {dur:.3f} s, {got} against {row['lufs']} LUFS")
    print(out, f"{dur:.3f} s", got)
    return out


def save() -> None:
    from hands.live import session
    print("saved" if session.save(ops.SET_NAME) else "nothing to save")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    steps = {"tracks": build_tracks, "instruments": build_instruments, "notes": build_notes, "mix": build_mix,
             "master": build_master, "params": build_params}
    if cmd == "build":
        for name in rest or list(steps):
            if name.startswith("notes:"):
                build_notes(name.split(":", 1)[1])
                continue
            L.guard(f"build {name}")
            steps[name]()
    elif cmd == "render":
        render(rest[0] if rest else "")
    elif cmd == "stems":
        raw = "--raw" in rest
        measure(stems([r for r in rest if r != "--raw"], raw=raw))
    elif cmd == "measure":
        measure([Path(p) for p in rest] or sorted(RENDERS.glob("marrow-cumbia*.wav")))
    elif cmd == "encode":
        encode(rest[0] if rest else "")
    elif cmd == "save":
        save()
    else:
        print(__doc__)
