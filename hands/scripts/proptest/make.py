"""Make the property-testing explainer into techno in Live: build the set, render, trim to the video, measure, mux.

  cd hands && uv run python scripts/proptest/newset.py               # once: a new, empty Live 12 set, PROPTEST_techno
  cd hands && uv run python scripts/proptest/make.py build [step]    # tracks | audio | instruments | sidechain |
                                                                     #   notes | mix | master  (all, in order)
  cd hands && uv run python scripts/proptest/make.py save
  cd hands && uv run python scripts/proptest/make.py render [tag]    # -> renders/proptest[-tag].wav, the video's length
  cd hands && uv run python scripts/proptest/make.py stems [names]   # each track alone (voice, bed, drums...)
  cd hands && uv run python scripts/proptest/make.py measure [files]
  cd hands && uv run python scripts/proptest/make.py mux [tag]       # .m4a, and the post's video with the new audio

The samples (VEC2's, copied out of iCloud Drive through Live) and the two demucs stems sit in the project's
Samples/Imported. The set, stems and renders live under ~/_agent_scratch/hiki/ (never ~/Music); no audio in git: the
voice and the video are hikikomorphism's.

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
SAMPLES = ops.SET_DIR / "Samples" / "Imported"
VIDEO = ops.SCRATCH / "post" / "video.mp4"
NAMES = [t["name"] for t in P.TRACKS]
EXPORT_FROM, EXPORT_TO = 4.0, 256.0          # whole beats around ORIGIN..END (the Export dialog takes whole beats)


def guard(where: str) -> None:
    """hands' guard, retried when it only failed to read Live's windows (the Hammerspoon path to System Events
    sometimes stalls for 30 s right after an export); a dialog or a wrong set still stops at once."""
    from hands.live.session import Guard
    for k in range(4):
        try:
            L.guard(where)
            return
        except Guard as exc:
            if "cannot read Live's windows" not in str(exc) or k == 3:
                raise
            print(f"  ({where}: windows unreadable, retrying)", flush=True)
            time.sleep(20)


def T(name: str) -> str:
    return f"song.tracks[{NAMES.index(name)}]"


def by_name(name: str) -> dict:
    return P.TRACKS[NAMES.index(name)]


# ---- build ---------------------------------------------------------------------------------------------------------------
def build_tracks() -> None:
    """Exactly parts.TRACKS, in order and named: audio tracks first, then MIDI; the new set's own tracks go."""
    L.run(f"song.tempo = {P.BPM}\nsong.signature_numerator = 4\nsong.signature_denominator = 4\nresult = 'ok'")
    have = L.run("result = [t.name for t in song.tracks]")
    if have == NAMES:
        print("tracks: already", have)
        return
    if have == NAMES[:len(have)]:                       # parts added tracks at the end: make just those
        for t in P.TRACKS[len(have):]:
            kind = "audio" if "audio" in t else "midi"
            L.run(f"song.create_{kind}_track(-1)\nresult = 'ok'")
            L.run(f"song.tracks[len(song.tracks) - 1].name = {t['name']!r}\nresult = 'ok'")
        print("tracks: added", L.run("result = [t.name for t in song.tracks]"))
        return
    if any(n in NAMES for n in have):
        sys.exit(f"STOP: a half-built set: {have}")
    for t in P.TRACKS:
        kind = "audio" if "audio" in t else "midi"
        L.run(f"song.create_{kind}_track(-1)\nresult = 'ok'")
        L.run(f"song.tracks[len(song.tracks) - 1].name = {t['name']!r}\nresult = 'ok'")
    for _ in have:
        L.run("song.delete_track(0)\nresult = 'ok'")
    got = L.run("result = ([(t.name, t.has_audio_input, t.has_midi_input) for t in song.tracks], song.tempo)")
    if [n for n, *_ in got[0]] != NAMES or abs(got[1] - P.BPM) > 1e-6:
        sys.exit(f"STOP: tracks {got}")
    print("tracks:", got)


def place(track: str, file: str, pos: float, f0: float, f1: float, gain_db: float = 0.0) -> None:
    """An unwarped arrangement clip of `file` (file seconds f0..f1) starting at song beat `pos`, at a clip gain."""
    k = L.run(f"result = len({track}.arrangement_clips)")
    L.run(f"{track}.create_audio_clip({str(SAMPLES / file)!r}, {pos!r})\nresult = 'ok'")
    time.sleep(0.4)
    c = f"sorted({track}.arrangement_clips, key=lambda c: c.start_time)"
    idx = L.run(f"cs = {c}\nresult = [i for i, x in enumerate(cs) if abs(x.start_time - {pos!r}) < 1e-6]")
    if len(idx) != 1 or L.run(f"result = len({track}.arrangement_clips)") != k + 1:
        sys.exit(f"STOP: {file} at {pos}: {idx}")
    cl = f"{c}[{idx[0]}]"
    L.run(f"x = {cl}\nx.warping = False\nresult = 'ok'")
    time.sleep(0.3)
    # unwarping moves the markers to the first transient; markers are file seconds now (end before start)
    L.run(f"x = {cl}\nx.loop_end = {f1!r}\nx.end_marker = {f1!r}\nresult = 'ok'")
    L.run(f"x = {cl}\nx.loop_start = {f0!r}\nx.start_marker = {f0!r}\nresult = 'ok'")
    time.sleep(0.3)
    got = L.run(f"x = {cl}\nresult = (x.start_time, x.end_time, x.warping, x.start_marker, x.end_marker)")
    want_end = pos + (f1 - f0) / P.SPB
    if abs(got[0] - pos) > 1e-6 or abs(got[1] - want_end) > 1e-3 or got[2] or abs(got[3] - f0) > 1e-4:
        sys.exit(f"STOP: {file} clip is {got}, wanted {pos}..{want_end} from {f0} s")
    if gain_db:
        # the clip gain is 0..1 on Live's own curve: binary search on its display string
        L.run(f"""x = {cl}
lo, hi = 0.0, 1.0
for _ in range(30):
    x.gain = (lo + hi) / 2
    if float(x.gain_display_string.split()[0]) < {gain_db!r}: lo = x.gain
    else: hi = x.gain
x.gain = hi
result = 'ok'""")
    shown = L.run(f"result = {cl}.gain_display_string")
    print(f"  {file} {f0:6.2f}-{f1:6.2f} s at beat {pos:8.4f}..{got[1]:8.4f}" + (f", gain {shown}" if gain_db else ""))


def build_audio() -> None:
    for name, file, pieces in (("voice", P.VOICE, [(0.0, P.FILE_S, 0.0, 0.0)]), ("bed", P.BED, P.BED_CLIPS)):
        path = T(name)
        L.run(f"t = {path}\nfor c in list(t.arrangement_clips):\n    t.delete_clip(c)\nresult = 'ok'")
        for f0, f1, shift, gain in pieces:
            place(path, file, P.ORIGIN + (f0 + shift) / P.SPB, f0, f1, gain)


def build_instruments() -> None:
    """A Simpler holding its sample on each MIDI track (playback mode and settings from parts), then every track's
    effects, unless there."""
    for t in P.TRACKS:
        path = T(t["name"])
        devs = L.devices(path)
        if "simpler" in t:
            s = t["simpler"]
            if not devs:
                guard(f"load {t['name']}")
                L.load_item(path, "instruments", None, "Simpler")
                devs = L.devices(path)
            if not devs or devs[0] != "Simpler" and devs[0] != s["sample"].rsplit(".", 1)[0]:
                sys.exit(f"STOP: {t['name']} has {devs}")
            dev = f"{path}.devices[0]"
            L.run(f"{dev}.replace_sample({str(SAMPLES / s['sample'])!r})\nresult = 'ok'")
            time.sleep(0.5)
            got = L.run(f"d = {dev}\nresult = (d.sample.file_path if d.sample else None, d.playback_mode)")
            if not got[0] or Path(got[0]).name != s["sample"]:
                sys.exit(f"STOP: {t['name']}'s Simpler holds {got}")
            mode = {"Classic": 0, "One-Shot": 1}[s["mode"]]
            L.run(f"{dev}.playback_mode = {mode}\nresult = 'ok'")
            if s["voices"]:
                L.run(f"{dev}.voices = {s['voices']}\nresult = 'ok'")
            if s["params"]:
                L.setp(dev, s["params"])
            print(f"{t['name']:10s} {Path(got[0]).name} mode/voices {L.run(f'result = ({dev}.playback_mode, {dev}.voices)')}",
                  L.params(dev, list(s["params"])) if s["params"] else "")
        for fx in t["fx"]:
            if fx not in devs[1 if "simpler" in t else 0:]:
                L.load_item(path, "audio_effects", None, fx)
                devs = L.devices(path)
                if fx not in devs:
                    sys.exit(f"STOP: {t['name']}: {fx} did not load ({devs})")
        print(f"{t['name']:10s} {L.devices(path)}")
    build_params()


# device settings, by track and device index, in display units
FX = {
    "voice": {0: {"1 Filter On A": 1.0, "1 Filter Type A": "High Pass 48dB", "1 Frequency A": "90 Hz"},
              1: {"Threshold": "-24 dB", "Ratio": 1 - 1 / 3, "Attack": "3.00 ms", "Release": "80.0 ms",
                  "Output": "3.0 dB"}},
    "bed": {0: {"1 Filter On A": 1.0, "1 Filter Type A": "High Pass 48dB", "1 Frequency A": "120 Hz"},
            1: {"Threshold": "-30 dB", "Ratio": 1 - 1 / 6, "Attack": "1.00 ms", "Release": "110 ms",
                "S/C On": 1.0}},
    "kick": {1: {"Drive": "4.0 dB", "Output": "-3.0 dB", "Dry/Wet": "100 %"}},
    "hat": {1: {"1 Filter On A": 1.0, "1 Filter Type A": "High Pass 48dB", "1 Frequency A": "2.00 kHz"}},
    "open": {1: {"1 Filter On A": 1.0, "1 Filter Type A": "High Pass 48dB", "1 Frequency A": "2.00 kHz"}},
    "ride": {1: {"1 Filter On A": 1.0, "1 Filter Type A": "High Pass 48dB", "1 Frequency A": "2.00 kHz"}},
    "bass": {1: {"Drive": "6.0 dB", "Output": "-4.0 dB", "Dry/Wet": "60 %"}},
}


def build_params() -> None:
    for name, devs in FX.items():
        for k, values in devs.items():
            dev = f"{T(name)}.devices[{k}]"
            L.setp(dev, values)
            print(f"{name:10s} dev {k}:", L.params(dev, list(values)))


def build_sidechain() -> None:
    """The bed's Compressor listens to the kick (its post-fx output), so the bed ducks on every kick."""
    comp = f"{T('bed')}.devices[1]"
    types = L.run(f"result = [x.display_name for x in {comp}.available_input_routing_types]")
    if "kick" not in types:
        sys.exit(f"STOP: the bed's Compressor offers {types}")
    L.run(f"d = {comp}\nd.input_routing_type = [x for x in d.available_input_routing_types if x.display_name == 'kick'][0]\n"
          "result = 'ok'")
    chans = L.run(f"result = [x.display_name for x in {comp}.available_input_routing_channels]")
    want = next((c for c in chans if "Post" in c), chans[0])
    L.run(f"d = {comp}\nd.input_routing_channel = [x for x in d.available_input_routing_channels "
          f"if x.display_name == {want!r}][0]\nresult = 'ok'")
    print("bed sidechain:", L.run(f"d = {comp}\nresult = (d.input_routing_type.display_name, "
                                  "d.input_routing_channel.display_name)"),
          L.params(comp, ["S/C On", "Threshold", "Ratio"]))


def write_notes(path: str, notes: list[tuple], start: float = 0.0, end: float = EXPORT_TO) -> None:
    """Replace the track's arrangement with one MIDI clip (start..end) holding `notes` (Live keeps one note per
    pitch and start: the louder, then longer, stays)."""
    best: dict = {}
    for b, p, d, v in notes:
        key = (int(p), round(float(b), 4))
        if key not in best or (v, d) > (best[key][3], best[key][2]):
            best[key] = (b, p, d, v)
    notes = sorted(best.values())
    L.run(f"""t = {path}
for c in list(t.arrangement_clips):
    t.delete_clip(c)
t.create_midi_clip({float(start)}, {float(end - start)})
result = 'ok'""")
    for k in range(0, len(notes), 150):
        chunk = [(int(p), round(float(b) - start, 4), round(float(d), 4), float(v)) for b, p, d, v in notes[k:k + 150]]
        L.run(f"""import Live
c = {path}.arrangement_clips[0]
c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v) for p, s, d, v in {chunk!r}))
result = 'ok'""")
    n = L.run(f"c = {path}.arrangement_clips[0]\nresult = (len(c.get_notes_extended(0, 128, 0.0, {float(end - start)})), "
              "c.start_time, c.end_time)")
    if n[0] != len(notes) or n[1] != start or n[2] != end:
        sys.exit(f"STOP: {path}: clip has {n}, expected {len(notes)} notes over {start}-{end}")


def build_notes(only: str | None = None) -> None:
    for t in P.TRACKS:
        if "notes" not in t or only and only != t["name"]:
            continue
        guard(f"notes {t['name']}")
        write_notes(T(t["name"]), t["notes"]())
        print(f"{t['name']:10s} notes written")


def build_mix() -> None:
    for t in P.TRACKS:
        L.mixer(T(t["name"]), t["vol"], t["sends"])
    print(L.run("result = [(t.name, t.mixer_device.volume.str_for_value(t.mixer_device.volume.value), "
                "[s.str_for_value(s.value) for s in t.mixer_device.sends]) for t in song.tracks]"))


MASTER = {0: {"Threshold": "-8.0 dB", "Ratio": 0.0, "Attack": 5.0, "Release": 1.0, "Output": "2.0 dB"},
          1: {"Mode": "True Peak", "Input Gain": "2.5 dB", "Ceiling": "-1.0 dB"}}


def build_master() -> None:
    devs = L.devices("song.master_track")
    for name in ("Glue Compressor", "Limiter"):
        if name not in devs:
            L.load_item("song.master_track", "audio_effects", None, name)
            devs = L.devices("song.master_track")
    if devs != ["Glue Compressor", "Limiter"]:
        sys.exit(f"STOP: Main has {devs}")
    for k, values in MASTER.items():
        L.setp(f"song.master_track.devices[{k}]", values)
        print(f"main {k}:", L.params(f"song.master_track.devices[{k}]", list(values)))
    print("returns:", L.run("result = [(r.name, [d.name for d in r.devices]) for r in song.return_tracks]"))


def set_mutes(on: set[str] | None) -> None:
    """Un-mute the tracks in `on` (all when None), mute the rest; read back."""
    mutes = [on is not None and n not in on for n in NAMES]
    L.run(f"for i, m in enumerate({mutes!r}):\n    song.tracks[i].mute = m\nresult = 'ok'")
    if L.run(f"result = [song.tracks[i].mute for i in range({len(mutes)})]") != mutes:
        sys.exit("STOP: the mutes did not take")


# ---- render, trim, measure, mux ------------------------------------------------------------------------------------------
def _fresh(out: Path) -> Path:
    if out.exists():
        old = out.parent / "old"
        old.mkdir(parents=True, exist_ok=True)
        out.rename(old / f"{int(time.time())}-{out.name}")
    return out


def trim(raw: Path, out: Path) -> Path:
    """Cut the export (beats EXPORT_FROM..) at the files' 0 s (song beat ORIGIN), the video's length, 5 ms fades."""
    import numpy as np
    import soundfile as sf
    y, sr = sf.read(raw, always_2d=True)
    a = int(round((P.ORIGIN - EXPORT_FROM) * P.SPB * sr))
    n = int(round(P.VIDEO_S * sr))
    y = y[a:a + n].copy()
    if len(y) < n:
        y = np.vstack([y, np.zeros((n - len(y), y.shape[1]))])
    f = int(0.005 * sr)
    y[:f] *= np.linspace(0, 1, f)[:, None]
    y[-f:] *= np.linspace(1, 0, f)[:, None]
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, y, sr, subtype="PCM_24")
    return out


def sync_check(path: Path) -> float:
    """The lag (ms) between a render and the post's own audio, by cross-correlating 300-3000 Hz envelopes (the voice);
    0 means the voice is where the video expects it."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import butter, sosfiltfilt, correlate

    def env(p):
        y, sr = sf.read(p, always_2d=True)
        y = y.mean(1)
        sos = butter(4, [300, 3000], btype="band", fs=sr, output="sos")
        e = np.abs(sosfiltfilt(sos, y))
        hop = sr // 1000
        return e[: len(e) // hop * hop].reshape(-1, hop).mean(1)
    a, b = env(ops.SCRATCH / "audio" / "orig.wav"), env(path)
    n = min(len(a), len(b))
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    xc = correlate(b, a, mode="full", method="fft")[n - 1 - 200: n - 1 + 201]
    return float(np.argmax(xc) - 200)


def render(tag: str = "") -> Path:
    RENDERS.mkdir(parents=True, exist_ok=True)
    out = _fresh(RENDERS / f"proptest{'-' + tag if tag else ''}.wav")
    raw = _fresh(RENDERS / "raw" / out.name)
    guard("render")
    set_mutes(None)
    t0 = time.time()
    L.export(raw, EXPORT_FROM, EXPORT_TO - EXPORT_FROM)
    trim(raw, out)
    print(f"{out.name}  export {time.time() - t0:4.1f} s, voice lag {sync_check(out):+.0f} ms")
    measure([out])
    return out


def stems(names: list[str]) -> list[Path]:
    outs = []
    try:
        for name in names or NAMES:
            raw = _fresh(RENDERS / "raw" / f"stem-{name}.wav")
            guard(f"stem {name}")
            group = {"drums": {"hat", "open", "clap", "ride", "crash", "rev long", "rev short"},
                     "music": set(NAMES) - {"voice"}}.get(name, {name})
            set_mutes(group)
            L.export(raw, EXPORT_FROM, EXPORT_TO - EXPORT_FROM)
            outs.append(trim(raw, _fresh(RENDERS / "stems" / f"stem-{name}.wav")))
    finally:
        set_mutes(None)
    return outs


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
        s = loudness(p)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(p)], capture_output=True, text=True, check=True).stdout)
        s.update(file=p.name, seconds=dur)
        rows.append(s)
        print(f"{p.name:28s} {dur:.3f} s  tp {s.get('true_peak', 0):5.1f} dBTP  {s.get('lufs', float('nan')):6.1f} LUFS"
              f"  LRA {s.get('lra', 0):4.1f}")
    return rows


def mux(tag: str = "") -> tuple[Path, Path]:
    wav = RENDERS / f"proptest{'-' + tag if tag else ''}.wav"
    m4a, mp4 = wav.with_suffix(".m4a"), wav.with_suffix(".mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac_at", "-b:a", "256k", "-ar", "44100",
                    "-movflags", "+faststart", str(m4a)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(VIDEO), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac_at", "-b:a", "256k", "-ar", "44100", "-shortest",
                    "-movflags", "+faststart", str(mp4)], check=True)
    measure([wav, m4a, mp4])
    return m4a, mp4


def save() -> None:
    from hands.live import session
    print("saved" if session.save(ops.SET_NAME) else "nothing to save")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    steps = {"tracks": build_tracks, "audio": build_audio, "instruments": build_instruments,
             "sidechain": build_sidechain, "notes": build_notes, "mix": build_mix, "master": build_master,
             "params": build_params}
    if cmd == "build":
        for name in rest or ["tracks", "audio", "instruments", "sidechain", "notes", "mix", "master"]:
            if name.startswith("notes:"):
                build_notes(name.split(":", 1)[1])
                continue
            guard(f"build {name}")
            steps[name]()
    elif cmd == "render":
        render(rest[0] if rest else "")
    elif cmd == "stems":
        measure(stems(rest))
    elif cmd == "measure":
        measure([Path(p) for p in rest] or sorted(RENDERS.glob("proptest*.wav")))
    elif cmd == "mux":
        mux(rest[0] if rest else "")
    elif cmd == "save":
        save()
    else:
        print(__doc__)
