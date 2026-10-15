"""Make the industrial short in Live: reshape the stripped HW002 set, write the notes, render, measure, encode.

  cd hands && uv run python scripts/industrial/strip.py               # once: the set, from HW002's, chains only
  open -a "Ableton Live 12 Suite" ~/_agent_scratch/industrial/set/"INDUS_short Project"/INDUS_short.als
  cd hands && uv run python scripts/industrial/make.py build [step]   # prune | tracks | instruments | chains | notes | mix | master
  cd hands && uv run python scripts/industrial/make.py render [tag]   # the mix, recorded through a Resampling track
  cd hands && uv run python scripts/industrial/make.py measure|encode [tag]

Each Live step: a read-back after it, short LOM calls, notes through add_new_notes. No step needs the menus or a
keystroke (this session's shell has no Accessibility grant): the set opens with `open`, renders are recorded by
hands' record_arrangement, and the set is saved by Anthony (Cmd+S) or the next session with menu access.
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
SECONDS = (P.BEATS + P.TAIL) * 60.0 / P.BPM

# HW002's tracks this set doesn't use; the chain donors go after their chains have moved (build chains)
# (matched without the "N-" Live puts on, and renumbers as tracks go)
UNUSED = ["01 - Lethal Storm", "2022-05-30-005", "Audio", "2023-11-14", "2023-10-07"]   # + the second ARC RAIDERS
DONORS = ["rumble", "ARC RAIDERS", "2022-06-02-001", "beatbox"]
NEW = ["rumble src", "acid", "stabs", "808", "riser"]   # MIDI tracks, made at the end of the list


def bare(name: str) -> str:
    """A track name without the number Live puts on an audio track's name ("12-2022-06-02-001" -> "2022-06-02-001")."""
    head, _, tail = name.partition("-")
    return tail if head.isdigit() and tail else name


def find(name: str) -> list[int]:
    ns = names()
    return [i for i, n in enumerate(ns) if n == name] or [i for i, n in enumerate(ns) if bare(n).startswith(name)]


def T(name: str) -> str:
    """The LOM path of the one track called `name` (or whose bare name starts with it)."""
    hits = find(name)
    if len(hits) != 1:
        sys.exit(f"STOP: track {name!r} matches {[names()[i] for i in hits]}")
    return f"song.tracks[{hits[0]}]"


def names() -> list[str]:
    return L.run("result = [t.name for t in song.tracks]")


def delete(prefixes: list[str]) -> None:
    """Delete every track matching each prefix (not group tracks), last first."""
    for pre in prefixes:
        for i in reversed(find(pre)):
            gone = names()[i]
            if L.run(f"result = song.tracks[{i}].is_foldable"):
                sys.exit(f"STOP: {gone} is a group")
            L.run(f"song.delete_track({i})\nresult = 'ok'")
            print("deleted", gone)
        if find(pre):
            sys.exit(f"STOP: {pre} is still there: {[names()[i] for i in find(pre)]}")


# ---- build ---------------------------------------------------------------------------------------------------------------
def build_prune() -> None:
    delete(UNUSED)
    arc = find("ARC RAIDERS")
    if len(arc) == 2:                                    # two copies of one chain: the Break group's goes
        L.run(f"song.delete_track({arc[1]})\nresult = 'ok'")
    if len(find("ARC RAIDERS")) != 1:
        sys.exit(f"STOP: ARC RAIDERS tracks: {find('ARC RAIDERS')}")
    print(names())


def build_tracks() -> None:
    L.run(f"song.tempo = {P.BPM}\nsong.signature_numerator = 4\nsong.signature_denominator = 4\nresult = 'ok'")
    for n in NEW:
        if n not in names():
            L.run("song.create_midi_track(-1)\nresult = 'ok'")
            L.run(f"song.tracks[len(song.tracks) - 1].name = {n!r}\nresult = 'ok'")
    got = L.run("result = (song.tempo, [(t.name, t.has_midi_input, t.is_grouped) for t in song.tracks])")
    if abs(got[0] - P.BPM) > 1e-6 or not all(n in [x[0] for x in got[1]] for n in NEW):
        sys.exit(f"STOP: {got}")
    print(got)


def load_sample(track: str, sample: str) -> None:
    """A project sample (Samples/Imported) onto `track`: an empty MIDI track gets a Simpler holding it."""
    L.select_track(track)
    L.run(f"""c = [x for x in browser.current_project.children if x.name == 'Samples'][0]
c = [x for x in c.children if x.name == 'Imported'][0]
it = [x for x in c.children if x.name == {sample!r}]
if not it: raise ValueError('no ' + {sample!r})
browser.load_item(it[0])
time.sleep(0.3)
result = 'requested'""")
    time.sleep(1.0)


def load_pad(track: str, note: int, sample: str) -> None:
    """A project sample onto a Drum Rack pad of `track` (devices[0])."""
    dr = f"{track}.devices[0]"
    L.select_track(track)
    L.run(f"""{dr}.view.selected_drum_pad = {dr}.drum_pads[{note}]
time.sleep(0.1)
c = [x for x in browser.current_project.children if x.name == 'Samples'][0]
c = [x for x in c.children if x.name == 'Imported'][0]
browser.load_item([x for x in c.children if x.name == {sample!r}][0])
time.sleep(0.3)
result = 'requested'""")
    time.sleep(1.0)
    got = L.run(f"p = {dr}.drum_pads[{note}]\nresult = (p.chains[0].devices[0].name if p.chains else None, len(p.chains))")
    if got[0] != sample.rsplit(".", 1)[0] or not got[1]:
        sys.exit(f"STOP: pad {note} holds {got}, not {sample}")


def build_instruments() -> None:
    for track, sample in (("rumble src", P.RUMBLE_SAMPLE), ("acid", P.ACID_SAMPLE), ("stabs", P.STAB_SAMPLE),
                          ("riser", P.RISER_SAMPLE)):
        path = T(track)
        if not L.devices(path):
            load_sample(path, sample)
        devs = L.devices(path)
        if not devs or devs[0] != "Simpler" and devs[0] != sample.rsplit(".", 1)[0]:
            sys.exit(f"STOP: {track} has {devs}")
        print(f"{track:10s} {devs}")
    path = T("808")
    if not L.devices(path):
        L.load_item(path, "drums", None, "808 Core Kit.adg")
    print("808       ", L.devices(path))
    kick = T("kick")
    if not L.run(f"result = len({kick}.devices[0].drum_pads[{P.KICK_TOP_PAD}].chains)"):
        load_pad(kick, P.KICK_TOP_PAD, P.KICK_TOP_SAMPLE)
    print("kick pads ", L.run(f"result = [(p.note, p.name) for p in {kick}.devices[0].drum_pads if p.chains]"))


def route(src: str, dst: str) -> None:
    """`src`'s sound through `dst`'s chain (an HW002 audio track): dst's input is src, monitored; src only feeds it."""
    s, d = T(src), T(dst)
    L.run(f"""s = {s}
d = {d}
d.input_routing_type = [x for x in d.available_input_routing_types if x.display_name == s.name][0]
d.current_monitoring_state = 0
s.output_routing_type = [x for x in s.available_output_routing_types if x.display_name == 'Sends Only'][0]
result = 'ok'""")
    got = L.run(f"d = {d}\ns = {s}\nresult = (d.input_routing_type.display_name, d.current_monitoring_state, "
                f"s.output_routing_type.display_name)")
    if got != [L.run(f"result = {s}.name"), 0, "Sends Only"]:
        sys.exit(f"STOP: {src} -> {dst}: {got}")
    print(f"{src} -> {dst}")


def to_main(track: str) -> None:
    L.run(f"t = {T(track)}\nt.output_routing_type = [x for x in t.available_output_routing_types "
          f"if x.display_name == 'Main'][0]\nresult = 'ok'")


def load_plugin(track: str, name: str) -> None:
    """A VST plugin (by its browser name) onto the end of `track`'s chain."""
    path = T(track)
    n0 = len(L.devices(path))
    L.select_track(path)
    L.run(f"""song.view.select_device({path}.devices[-1]) if len({path}.devices) else None
def walk(item, depth=0):
    for c in item.children:
        if c.name.rsplit('.', 1)[0] == {name!r} and c.is_loadable:
            return c
        if c.is_folder and depth < 3:
            hit = walk(c, depth + 1)
            if hit: return hit
it = walk(browser.plugins)
if it is None: raise ValueError('no plugin ' + {name!r})
browser.load_item(it)
time.sleep(0.3)
result = 'requested'""")
    time.sleep(1.5)
    devs = L.devices(path)
    if len(devs) != n0 + 1 or devs[-1] != name:
        sys.exit(f"STOP: {name} on {track}: {devs}")


def build_chains() -> None:
    # the rumble: the kick into a long, fully wet reverb, then HW002's rumble chain (Decapitator, LFOTool's duck)
    src = T("rumble src")
    if "Reverb" not in L.devices(src):
        L.load_item(src, "audio_effects", None, "Reverb")
    L.setp(f"{src}.devices[1]", P.RUMBLE_REVERB)
    route("rumble src", "rumble")
    # the stabs: HW002's chord chain, its Supermassive and COLDFIRE back on (off since batch 4.3), into the SFX bus
    chord = T("2022-06-02-001")
    L.run(f"for d in {chord}.devices:\n    d.parameters[0].value = 1.0\nresult = 'ok'")
    route("stabs", "2022-06-02-001")
    # the 808: through the beatbox chain (EQ, COLDFIRE, EQ, Supermassive, Compressor), straight to Main: the Break
    # group's high-pass at 194 Hz would take the boom
    route("808", "beatbox")
    to_main("beatbox")
    L.setp(f"{T('beatbox')}.devices[3]", {"Mix": P.EIGHT_VERB_MIX})
    # the acid: its own Decapitator, EQ and Supermassive, dry and in front
    acid = T("acid")
    if "Decapitator" not in L.devices(acid):
        load_plugin("acid", "Decapitator")
    if "EQ Eight" not in L.devices(acid):
        L.load_item(acid, "audio_effects", None, "EQ Eight")
    if "ValhallaSupermassive" not in L.devices(acid):
        load_plugin("acid", "ValhallaSupermassive")
    print("acid", L.devices(acid))
    delete(["ARC RAIDERS"])
    print(L.run("result = [(t.name, [d.name for d in t.devices], t.output_routing_type.display_name) "
                "for t in song.tracks]"))


def build_layers() -> None:
    """The harsh kick layers: VEC2 hard kicks swapped onto HW002's driven pads (their chains stay), high-passed."""
    kick = T("kick")
    for name, (pad, sample, transpose) in P.KICK_LAYERS.items():
        have = L.run(f"result = {kick}.devices[0].drum_pads[{pad}].chains[0].devices[0].name")
        if have != sample.rsplit(".", 1)[0]:
            load_pad(kick, pad, sample)
        L.setp(f"{kick}.devices[0].drum_pads[{pad}].chains[0].devices[0]", {**P.LAYER_SIMPLER, "Transpose": transpose})
        L.mixer(f"{kick}.devices[0].drum_pads[{pad}].chains[0]", P.LAYER_GAIN.get(pad, 0.0))
        for k, values in P.LAYER_FX.get(pad, {}).items():
            L.setp(f"{kick}.devices[0].drum_pads[{pad}].chains[0].devices[{k}]", values)
        print(name, pad, L.run(f"result = [d.name for d in {kick}.devices[0].drum_pads[{pad}].chains[0].devices]"),
              L.params(f"{kick}.devices[0].drum_pads[{pad}].chains[0].devices[0]", [*P.LAYER_SIMPLER, "Transpose"]))


def build_sounds() -> None:
    for track in P.MONO:
        L.run(f"{T(track)}.devices[0].voices = 1\nresult = 'ok'")
        print(track, "voices", L.run(f"result = {T(track)}.devices[0].voices"))
    for track, devs in P.SOUNDS.items():
        for k, values in devs.items():
            L.setp(f"{T(track)}.devices[{k}]", values)
            print(f"{track:6s} {k}", L.params(f"{T(track)}.devices[{k}]", list(values)))


def build_mix() -> None:
    for track, db in P.VOLUMES.items():
        L.mixer(T(track), db)
    for track, devs in P.CHAINS.items():
        for k, values in devs.items():
            L.setp(f"{T(track)}.devices[{k}]", values)
            print(f"{track} {k}", L.params(f"{T(track)}.devices[{k}]", list(values)))
    print(L.run("result = [(t.name[:12], t.mixer_device.volume.str_for_value(t.mixer_device.volume.value)) "
                "for t in song.tracks]"))


def build_master() -> None:
    main = "song.master_track"
    for fx in P.MASTER_FX:
        if fx not in L.devices(main):
            if fx == "StandardCLIP":
                L.select_track(main)
                L.run(f"""song.view.select_device({main}.devices[-1])
def walk(item, depth=0):
    for c in item.children:
        if c.name.rsplit('.', 1)[0] == 'StandardCLIP' and c.is_loadable:
            return c
        if c.is_folder and depth < 3:
            hit = walk(c, depth + 1)
            if hit: return hit
browser.load_item(walk(browser.plugins))
time.sleep(0.3)
result = 'requested'""")
                time.sleep(1.5)
            else:
                L.load_item(main, "audio_effects", None, fx)
    devs = L.devices(main)
    if devs[2:] != P.MASTER_FX:
        sys.exit(f"STOP: Main has {devs}")
    for k, values in P.MASTER.items():
        L.setp(f"{main}.devices[{k}]", values)
        print(f"main {k}", L.params(f"{main}.devices[{k}]", list(values)))
    L.mixer(main, 0.0)                                   # HW002 left Main's fader at -6 dB
    print("main fader", L.run(f"v = {main}.mixer_device.volume\nresult = v.str_for_value(v.value)"))


NOTES = {   # track: (notes, pad names or None)
    "kick": (P.kick, "kick"), "rumble src": (P.rumble, None), "perc 1": (lambda: P.humanize(P.hats(), 1), "perc 1"),
    "perc 2": (lambda: P.humanize(P.ride(), 2), "perc 2"), "acid": (P.acid, None), "stabs": (P.stabs, None),
    "808": (lambda: P.humanize(P.eight(), 3), "808"), "riser": (P.riser, None),
}


def write_notes(path: str, notes: list[tuple], beats: float = P.BEATS + P.LEAD) -> None:
    """Replace the track's arrangement with one MIDI clip over the whole short holding `notes` (Live keeps one note
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
    for track, (make, pads) in NOTES.items():
        if only and only != track:
            continue
        notes = make()
        if pads:
            notes = [(b, P.PADS[pads][p], d, v) for b, p, d, v in notes]
        write_notes(T(track), [(b + P.LEAD, p, d, v) for b, p, d, v in notes])
        print(f"{track:10s} {len(notes)} notes")


# ---- render, measure, encode ---------------------------------------------------------------------------------------------
def render(tag: str = "") -> Path:
    """The mix, recorded in real time through a Resampling track (no Export dialog: no menus here), then trimmed to
    the short at the take's own beat 0 plus the lead-in."""
    import soundfile as sf
    from hands import audio
    from hands.live.record import record_arrangement
    out = RENDERS / f"indus{'-' + tag if tag else ''}.wav"
    if out.exists():
        sys.exit(f"STOP: {out} exists")
    take = record_arrangement(L.LIVE, f"take-{out.name}", P.LEAD + P.BEATS, RENDERS / "takes", tail_beats=P.TAIL + 2.0)
    if not take:
        sys.exit("STOP: no take")
    y, sr = audio.trim_take(take, lead_beats=P.LEAD, length_beats=P.BEATS + P.TAIL, fade_in_s=0.002, fade_out_s=1.5)
    sf.write(out, y, sr, subtype="PCM_24")
    measure([out])
    return out


STEMS = {"kick": ["kick"], "kickbus": ["kick", "rumble src", "rumble"], "rumble": ["rumble src", "rumble"], "hats": ["perc 1", "perc 2"], "acid": ["acid"],
         "stabs": ["stabs", "2022-06-02-001"], "808": ["808", "beatbox"]}


def set_mutes(on: list[str] | None) -> None:
    """Un-mute the (non-group) tracks named in `on` (all when None), mute the rest; read back."""
    ns = names()
    keep = None if on is None else {i for n in on for i in find(n)}
    folds = L.run("result = [t.is_foldable for t in song.tracks]")
    mutes = [False if folds[i] or keep is None else i not in keep for i in range(len(ns))]
    L.run(f"for i, m in enumerate({mutes!r}):\n    song.tracks[i].mute = m\nresult = 'ok'")
    if L.run(f"result = [song.tracks[i].mute for i in range({len(mutes)})]") != mutes:
        sys.exit("STOP: the mutes did not take")


def stems(which: list[str], tag: str = "") -> None:
    try:
        for name in which or list(STEMS):
            set_mutes(STEMS[name])
            render(f"{tag}stem-{name}")
    finally:
        set_mutes(None)


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


def measure(paths) -> None:
    for p in paths:
        v = loudness(p)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(p)], capture_output=True, text=True, check=True).stdout)
        print(f"{p.name:24s} {dur:.3f} s  {v.get('lufs', float('nan')):6.1f} LUFS  tp {v.get('true_peak', 0):5.1f} dBTP"
              f"  LRA {v.get('lra', 0):4.1f}")


def encode(tag: str = "") -> Path:
    wav = RENDERS / f"indus{'-' + tag if tag else ''}.wav"
    out = wav.with_suffix(".m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac_at", "-b:a", "256k", "-ar", "44100",
                    "-movflags", "+faststart", str(out)], check=True)
    measure([wav, out])
    return out


def snapshot(out: Path) -> None:
    """The set as built, read from Live: every track (routing, fader, sends, mute) and every device, inside racks and
    drum pads too, with each parameter's displayed value (COLDFIRE's shown knobs included). Notes are parts.py's."""
    import json
    tracks = L.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks) + [song.master_track]]")
    data = {"tempo": L.run("result = song.tempo"), "tracks": []}
    for k in range(len(tracks)):
        data["tracks"].append(L.run(f"""allt = list(song.tracks) + list(song.return_tracks) + [song.master_track]
t = allt[{k}]
def dev(d):
    o = {{'name': d.name, 'class': d.class_name, 'on': bool(d.parameters[0].value) if len(d.parameters) else None,
         'params': [[p.name, p.str_for_value(p.value)] for p in list(d.parameters)[1:]]}}
    if d.can_have_drum_pads:
        o['pads'] = [{{'note': p.note, 'name': p.name, 'mute': p.mute,
                      'chains': [{{'name': c.name, 'volume': c.mixer_device.volume.str_for_value(c.mixer_device.volume.value),
                                  'devices': [dev(x) for x in c.devices]}} for c in p.chains]}} for p in d.drum_pads if p.chains]
    elif d.can_have_chains:
        o['chains'] = [{{'name': c.name, 'devices': [dev(x) for x in c.devices]}} for c in d.chains]
    return o
m = t.mixer_device
r = {{'name': t.name, 'volume': m.volume.str_for_value(m.volume.value), 'pan': m.panning.str_for_value(m.panning.value),
     'sends': [s.str_for_value(s.value) for s in m.sends], 'devices': [dev(d) for d in t.devices]}}
if t in song.tracks:
    r.update({{'mute': t.mute, 'group': t.group_track.name if t.is_grouped else None,
              'input': t.input_routing_type.display_name if t.has_audio_input else None,
              'output': t.output_routing_type.display_name}})
result = r"""))
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(out, len(data["tracks"]), "tracks")


STEPS = {"prune": build_prune, "tracks": build_tracks, "instruments": build_instruments, "chains": build_chains, "layers": build_layers, "sounds": build_sounds, "notes": build_notes, "mix": build_mix, "master": build_master}

if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    if cmd == "build":
        for name in rest or list(STEPS):
            if name.startswith("notes:"):
                build_notes(name.split(":", 1)[1])
                continue
            STEPS[name]()
    elif cmd == "render":
        render(rest[0] if rest else "")
    elif cmd == "stems":
        stems(rest)
    elif cmd == "measure":
        measure([Path(p) for p in rest] or sorted(RENDERS.glob("indus*.wav")))
    elif cmd == "snapshot":
        snapshot(Path(rest[0]))
    elif cmd == "encode":
        encode(rest[0] if rest else "")
    else:
        print(__doc__)
