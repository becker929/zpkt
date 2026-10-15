"""Make SH001, The Rummage's short, in Live: build the set, render the 27 combos, measure, encode, write audio.json.

  cd hands && uv run python scripts/rummage/make.py build [step]     # tracks | instruments | notes | mix | master
  cd hands && uv run python scripts/rummage/make.py save             # File > Save Live Set (As, the first time)
  cd hands && uv run python scripts/rummage/make.py render 1-2-3     # one combo; `render all` for the 27
  cd hands && uv run python scripts/rummage/make.py measure          # length, peak, true peak, LUFS of each render
  cd hands && uv run python scripts/rummage/make.py encode           # -> .m4a named by content, + audio.json

The composition and the sounds are in parts.py. Live 12 Suite's own instruments, kits and Core Library samples only.
The set is ~/_agent_scratch/rummage/set/SH001_rummage Project/SH001_rummage.als; renders go to
~/_agent_scratch/rummage/renders/ (never ~/Music), the .m4a files to ~/_agent_scratch/studio/regions/rummage/audio/
(served by the harness), and the manifest to lib/harness/.../static/checklist/rummage/audio.json. Audio never goes
in git.

Each Live step is checked: hands' guard before it (no dialog, this set in front, the LOM answering), a read-back
after it. LOM calls stay short; notes go in with the Live 11+ calls only (add_new_notes, remove_notes_extended).
Exports go through liveops.export, which needs no keystrokes (see liveops.py for why).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import liveops as L  # sets the rig environment before hands is imported
import parts as P

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "lib/harness/src/harness/studio/static/checklist/rummage/audio.json"
RENDERS = L.SCRATCH / "renders"
WEB = Path("~/_agent_scratch/studio/regions/rummage/audio").expanduser()
SECONDS = P.BEATS * 60.0 / P.BPM
NAMES = [t["name"] for t in P.TRACKS]


def tix(name: str) -> int:
    return NAMES.index(name)


def T(name: str) -> str:
    return f"song.tracks[{tix(name)}]"


# ---- build ---------------------------------------------------------------------------------------------------------------
def build_tracks() -> None:
    """One MIDI track per entry in parts.TRACKS, in order and named; tempo and time signature."""
    L.run(f"song.tempo = {P.BPM}\nsong.signature_numerator = 4\nsong.signature_denominator = 4\nresult = 'ok'")
    have = L.run("result = [(t.name, t.has_midi_input, len(t.devices)) for t in song.tracks]")
    for i, (name, midi, ndev) in enumerate(have):
        if not midi and ndev == 0:
            sys.exit(f"STOP: track {i} {name!r} is an audio track; build from a new set or a set of MIDI tracks")
    while len(L.run("result = [t.name for t in song.tracks]")) < len(NAMES):
        L.run("song.create_midi_track(-1)\nresult = 'ok'")
    L.run(f"for i, n in enumerate({NAMES!r}):\n    song.tracks[i].name = n\nresult = 'ok'")
    got = L.run("result = ([t.name for t in song.tracks], song.tempo)")
    if got[0][:len(NAMES)] != NAMES or abs(got[1] - P.BPM) > 1e-6:
        sys.exit(f"STOP: tracks {got}")
    print("tracks:", got)


def build_instruments() -> None:
    """Load each track's instrument (a preset, a kit or a sample into Simpler) and its effects, unless already there."""
    for t in P.TRACKS:
        path = T(t["name"])
        devs = L.devices(path)
        root, folder, item = t["src"]
        want0 = item.rsplit(".", 1)[0]
        if not devs:
            L.guard(f"load {t['name']}")
            L.load_item(path, root, folder, item)
            devs = L.devices(path)
        if not devs or (devs[0] != want0 and not (root == "samples" and devs[0] == "Simpler")
                        and not (root == "samples" and devs[0] == want0)):
            sys.exit(f"STOP: {t['name']} has {devs}, expected {want0}")
        for fx in t["fx"]:
            if fx not in devs[1:]:
                L.load_item(path, "audio_effects", None, fx)
                devs = L.devices(path)
                if fx not in devs:
                    sys.exit(f"STOP: {t['name']}: {fx} did not load ({devs})")
        print(f"{t['name']:18s} {devs}")
    # samples onto empty pads of a track's Drum Rack (the Kitchen kit's kick; the shared track's found sounds)
    for t in P.TRACKS:
        path = T(t["name"])
        dr = f"{path}.{t.get('rack', 'devices[0]')}"
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
                sys.exit(f"STOP: pad {note} of {path} holds {got}, not {sample}")
            if settings:
                L.setp(f"{dr}.drum_pads[{note}].chains[0].devices[0]", settings)
            print(f"{t['name']:18s} pad {note}: {got[0]}")
    # samples into Simpler: Classic mode, unwarped (the hiss loops for the whole short)
    for t in P.TRACKS:
        if t.get("simpler_loop"):
            sim = f"{T(t['name'])}.devices[0]"
            L.run(f"s = {sim}\ns.playback_mode = 0\nresult = 'ok'")
            L.run(f"s = {sim}\ns.sample.warping = False\nresult = 'ok'")
    build_params()


def build_params() -> None:
    """Each track's device settings from parts.TRACKS[...]['set'] ({device index: {parameter: value}})."""
    for t in P.TRACKS:
        for k, values in t.get("set", {}).items():
            L.setp(f"{T(t['name'])}.devices[{k}]", values)
            print(f"{t['name']:18s} dev {k}:", L.params(f"{T(t['name'])}.devices[{k}]", list(values)))


def write_notes(path: str, notes: list[tuple], beats: float = P.BEATS) -> None:
    """Replace the track's arrangement with one MIDI clip over the whole short holding `notes`. Two notes on the same
    pitch and start are one note in Live: keep the louder (then longer)."""
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
        if only and only not in t["name"]:
            continue
        L.guard(f"notes {t['name']}")
        write_notes(T(t["name"]), t["notes"]())
        print(f"{t['name']:18s} notes written")


def build_mix() -> None:
    for t in P.TRACKS:
        L.mixer(T(t["name"]), t["vol"], t["sends"])
    print(L.run("result = [(t.name, t.mixer_device.volume.str_for_value(t.mixer_device.volume.value), "
                "[s.str_for_value(s.value) for s in t.mixer_device.sends]) for t in song.tracks]"))


def build_master() -> None:
    """Returns: A a short plate-ish reverb, B a dotted-eighth delay. Main: Glue Compressor, then a Limiter at -1.5 dB."""
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


def build_phone() -> None:
    """Return C, the phone layer (parts.PHONE_RETURN): created once, its devices loaded and set; then each track's
    send to it (parts.TRACKS[...]['phone'] in dB; none for the rest)."""
    spec = P.PHONE_RETURN
    if len(L.run("result = [r.name for r in song.return_tracks]")) < 3:
        L.run("song.create_return_track()\nresult = 'ok'")
    L.run(f"song.return_tracks[2].name = {spec['name']!r}\nresult = 'ok'")
    ret = "song.return_tracks[2]"
    for name in spec["devices"]:
        if name not in L.devices(ret):
            L.load_item(ret, "audio_effects", None, name)
    if L.devices(ret) != spec["devices"]:
        sys.exit(f"STOP: return C has {L.devices(ret)}")
    for k, values in spec["set"].items():
        L.setp(f"{ret}.devices[{k}]", values)
        print(f"return C dev {k}:", L.params(f"{ret}.devices[{k}]", list(values)))
    for t in P.TRACKS:
        level = t.get("phone")
        L.run(HELPER_SEND.format(track=T(t["name"]), level=repr(f"{level} dB") if level is not None else "None"))
    print(L.run("result = [(t.name, t.mixer_device.sends[2].str_for_value(t.mixer_device.sends[2].value)) for t in song.tracks]"))


HELPER_SEND = L.HELPER + """
s = {track}.mixer_device.sends[2]
if {level} is None:
    s.value = 0.0
else:
    _setp(s, {level}, 'send C')
result = 'ok'"""


def set_combo(b: int, d: int, s: int) -> None:
    """Un-mute exactly the tracks of bed b, drums d, bass s."""
    on = set(P.tracks_of("bed", b) + P.tracks_of("drums", d) + P.tracks_of("bass", s) + P.tracks_of("shared", 0))
    mutes = [t["name"] not in on for t in P.TRACKS]
    L.run(f"for i, m in enumerate({mutes!r}):\n    song.tracks[i].mute = m\nresult = 'ok'")
    got = L.run(f"result = [song.tracks[i].mute for i in range({len(mutes)})]")
    if got != mutes:
        sys.exit(f"STOP: mutes {got}, wanted {mutes}")


# ---- render, measure, encode -----------------------------------------------------------------------------------------------
def combo_name(c) -> str:
    return "-".join(str(x) for x in c)


def render(c, tag: str = "") -> Path:
    out = RENDERS / f"sh001-{combo_name(c)}{tag}.wav"
    if out.exists():
        old = RENDERS / "old"
        old.mkdir(parents=True, exist_ok=True)
        out.rename(old / f"{int(time.time())}-{out.name}")
    L.guard(f"render {combo_name(c)}")
    set_combo(*c)
    t0 = time.time()
    L.export(out, 0.0, float(P.BEATS))
    s = check(out)
    print(f"{out.name}  {time.time() - t0:4.1f} s  {s['seconds']:.3f} s  peak {s['peak_dbfs']:.1f}  rms {s['rms_dbfs']:.1f}")
    return out


def check(path: Path) -> dict:
    from hands import audio
    return audio.check_audio(path, seconds=SECONDS, tol_s=0.01, min_rms_dbfs=-40.0)


def loudness(path: Path) -> dict:
    """Integrated loudness (LUFS), loudness range and true peak, from ffmpeg's EBU R128 meter."""
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
        print(f"{p.name:26s} {s['seconds']:.3f} s  peak {s['peak_dbfs']:5.1f}  tp {s.get('true_peak', 0):5.1f} dBTP  "
              f"{s['lufs']:6.1f} LUFS  LRA {s.get('lra', 0):4.1f}")
    return rows


def encode() -> None:
    """Encode every combo, verify each .m4a (decodes, the right length, its loudness close to the WAV's), add it to
    WEB beside the earlier ones (names carry a content hash; the files a published audio.json names are never
    deleted or overwritten), and only then write audio.json."""
    WEB.mkdir(parents=True, exist_ok=True)
    work = RENDERS / "m4a"
    work.mkdir(parents=True, exist_ok=True)
    combos, ready = {}, []
    for c in P.combos():
        wav = RENDERS / f"sh001-{combo_name(c)}.wav"
        (row,) = measure([wav])
        tmp = work / f"sh001-{combo_name(c)}.m4a"
        tmp.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac_at", "-b:a", "192k", "-ar", "44100",
                        "-movflags", "+faststart", str(tmp)], check=True)
        got = loudness(tmp)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(tmp)], capture_output=True, text=True, check=True).stdout)
        if abs(dur - SECONDS) > 0.05 or abs(got["lufs"] - row["lufs"]) > 0.3 or got.get("true_peak", 0) > -0.5:
            sys.exit(f"STOP: {tmp.name} does not verify: {dur:.3f} s, {got} against {row['lufs']} LUFS")
        h = hashlib.sha256(tmp.read_bytes()).hexdigest()[:8]
        ready.append((tmp, WEB / f"sh001-{combo_name(c)}-{h}.m4a"))
        gain = max(-6.0, min(6.0, -14.0 - row["lufs"]))
        combos[combo_name(c)] = {"file": ready[-1][1].name, "lufs": round(row["lufs"], 1), "gain_db": round(gain, 1)}
    for tmp, named in ready:                       # all 27 verified: add them (never replace an existing file)
        if not named.exists():
            tmp.replace(named)
    manifest = {"track": "sh001", "bpm": P.BPM, "bars": P.BARS, "seconds": round(SECONDS, 3), "sample_rate": 44100,
                "parts": P.OPTIONS, "combos": combos}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(MANIFEST.relative_to(ROOT), len(combos), "combos")


def save() -> None:
    from hands.live import session, ui
    front = ui.front_title()
    if front == L.SET_NAME:
        print("saved" if session.save(L.SET_NAME) else "nothing to save")
    else:
        print(L.save_as(L.SCRATCH / "set", L.SET_NAME))


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    steps = {"tracks": build_tracks, "instruments": build_instruments, "notes": build_notes, "mix": build_mix,
             "master": build_master, "phone": build_phone}
    if cmd == "build":
        for name in rest or list(steps):
            if name.startswith("notes:"):
                build_notes(name.split(":", 1)[1])
                continue
            L.guard(f"build {name}")
            steps[name]()
    elif cmd == "combo":
        set_combo(*[int(x) for x in rest[0].split("-")])
    elif cmd == "render":
        todo = P.combos() if rest[0] == "all" else [tuple(int(x) for x in r.split("-")) for r in rest]
        for c in todo:
            render(c)
    elif cmd == "stems":                       # each option alone, for the balance: stem-bed1.wav ...
        for part in ("bed", "drums", "bass"):
            for opt in (1, 2, 3):
                out = RENDERS / "stems" / f"stem-{part}{opt}.wav"
                if out.exists():
                    out.rename(out.with_name(f"{int(time.time())}-{out.name}"))
                mutes = [not (t["part"] == part and t["opt"] == opt) for t in P.TRACKS]
                L.guard(f"stem {part}{opt}")
                L.run(f"for i, m in enumerate({mutes!r}):\n    song.tracks[i].mute = m\nresult = 'ok'")
                if L.run(f"result = [song.tracks[i].mute for i in range({len(mutes)})]") != mutes:
                    sys.exit("STOP: mutes did not take")
                L.export(out, 0.0, float(P.BEATS))
        measure(sorted((RENDERS / "stems").glob("stem-*.wav")))
    elif cmd == "measure":
        measure(sorted(RENDERS.glob("sh001-*.wav")))
    elif cmd == "encode":
        encode()
    elif cmd == "save":
        save()
    else:
        print(__doc__)
