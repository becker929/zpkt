"""Small fake sets for tests: `fake_set(spec)` builds a Song from a dict, `hw002_like()` has the mix desk's shape.

    fake_set({"tempo": 160,
              "returns": [{"name": "Space", "devices": ["Reverb"]}],
              "tracks": [{"name": "kick", "volume": 0.7, "sends": [0.2], "output": "Kick bus",
                          "devices": [{"device": "EQ Eight", "name": "desk EQ", "params": {"2 Gain A": -3.0}}],
                          "clips": [{"start": 0, "length": 64}]},
                         {"name": "Kick bus"}],
              "main": {"devices": [{"device": "Utility", "name": "desk headroom", "params": {"Output": -6 / 35}}]}})

Values are raw LOM values (volume 0.85 shows 0.0 dB). A track's "type" is "audio" (the default), "midi" or "group";
"group": "Drums" puts it in that group track. A device is a built-in's browser name, a dict naming one (with "name",
"on", "params", rack "chains"), or a dict with "class_name" and "params" for anything else (a plug-in, see
devices.custom). A Drum Rack's chain may say its pad's "note" (36 is C1; left out, pads fill upward from 36). A
track's "color" is 0xRRGGBB; a MIDI clip's "notes" are [pitch, start, duration, velocity]. Returns are named without
their letter: Live puts "A-" in front.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from zpkt.live.testing import devices
from zpkt.live.testing.lom import Chain, Clip, Device, MidiNoteSpecification, ReturnTrack, RoutingType, Song, Track

SET_KEYS = {"tempo", "tracks", "returns", "main", "loop", "loop_start", "loop_length", "start_time"}
TRACK_KEYS = {
    "name",
    "type",
    "color",
    "volume",
    "pan",
    "sends",
    "mute",
    "solo",
    "arm",
    "output",
    "group",
    "monitoring",
    "devices",
    "clips",
    "fold",
}


def _refuse_unknown(what: str, given: Mapping[str, Any], known: set[str]) -> None:
    unknown = set(given) - known
    if unknown:
        raise ValueError(f"{what}: unknown keys {sorted(unknown)}; known: {sorted(known)}")


def fake_set(spec: Mapping[str, Any]) -> Song:
    """A Song from a dict (the module docstring has the shape)."""
    _refuse_unknown("the set", spec, SET_KEYS)
    song = Song(tempo=float(spec.get("tempo", 120.0)))
    for key in ("loop", "loop_start", "loop_length", "start_time"):
        if key in spec:
            setattr(song, key, spec[key])
    returns = list(spec.get("returns", ()))
    for r in returns:
        song._returns.append(ReturnTrack(song, str(r["name"]), len(returns)))
    for t in spec.get("tracks", ()):
        kind = t.get("type", "audio")
        if kind not in ("audio", "midi", "group"):
            raise ValueError(f"track {t.get('name')!r}: type is audio, midi or group, not {kind!r}")
        song._tracks.append(Track(song, kind, str(t["name"]), len(returns)))
    by_name = {tr._values["name"]: tr for tr in song._tracks}
    for t, track in zip(spec.get("tracks", ()), song._tracks, strict=True):
        _refuse_unknown(f"track {t['name']!r}", t, TRACK_KEYS)
        _place(track, t, by_name)
        _fill(track, t)
    for r, track in zip(returns, song._returns, strict=True):
        _refuse_unknown(
            f"return {r['name']!r}", r, TRACK_KEYS - {"type", "arm", "output", "group", "monitoring", "clips"}
        )
        _fill(track, r)
    main = dict(spec.get("main", {}))
    _refuse_unknown("main", main, {"volume", "pan", "devices"})
    _fill(song._main, main)
    return song


def _place(track: Track, t: Mapping[str, Any], by_name: dict[str, Track]) -> None:
    """Group membership, output routing, monitoring, arm, fold: what needs the other tracks to exist."""
    if "group" in t:
        group = by_name.get(t["group"])
        if group is None or group._kind != "group":
            raise ValueError(f"track {t['name']!r}: no group track {t['group']!r}")
        track._group = group
    if "output" in t and t["output"] != "Main":
        target = by_name.get(t["output"])
        if target is None or target._kind not in ("audio", "group") or target is track:
            raise ValueError(f"track {t['name']!r}: output {t['output']!r} is not another audio or group track")
        track._output = RoutingType(target.name, target)
    for key, attr in (("monitoring", "current_monitoring_state"), ("arm", "arm"), ("fold", "fold_state")):
        if key in t:
            setattr(track, attr, t[key])
    for c in t.get("clips", ()):
        track._clips.append(_clip(track, c))


def _fill(track: Track, t: Mapping[str, Any]) -> None:
    """Mixer values and devices, as raw LOM values."""
    mixer = track.mixer_device
    if "volume" in t:
        mixer.volume.value = t["volume"]
    if "pan" in t:
        mixer.panning.value = t["pan"]
    sends = list(t.get("sends", ()))
    if len(sends) > len(mixer.sends):
        raise ValueError(f"{track.name!r}: {len(sends)} sends, but the set has {len(mixer.sends)} returns")
    for send, value in zip(mixer.sends, sends, strict=False):
        send.value = value
    for flag in ("mute", "solo", "color"):
        if flag in t:
            setattr(track, flag, t[flag])
    for d in t.get("devices", ()):
        track._add_device(device(d))


def device(d: str | Mapping[str, Any]) -> Device:
    """One device from its description (the module docstring)."""
    if isinstance(d, str):
        return devices.make(d)
    if "class_name" in d:
        return devices.custom(str(d["name"]), str(d["class_name"]), list(d.get("params", ())))
    made = devices.make(str(d["device"]), name=d.get("name"), on=bool(d.get("on", True)))
    by = {p.name: p for p in made.parameters}
    for name, value in dict(d.get("params", {})).items():
        if name not in by:
            raise ValueError(f"{made.name!r} has no parameter {name!r}; it has: {', '.join(by)}")
        by[name].value = value
    for k, c in enumerate(d.get("chains", ())):
        if not made.can_have_chains:
            raise ValueError(f"{made.name!r} is not a rack: it has no chains")
        chain = Chain(str(c["name"]), [device(x) for x in c.get("devices", ())], parent=made)
        if made.can_have_drum_pads:
            # GUESS: a Drum Rack filled in order starts at C1 (36), as the pads a new rack shows first
            chain._pad_note = int(c.get("note", 36 + k))
        elif "note" in c:
            raise ValueError(f"{made.name!r} is not a Drum Rack: its chain {c['name']!r} is on no pad")
        made._chains.append(chain)
    return made


def _clip(track: Track, c: Mapping[str, Any]) -> Clip:
    audio = track._kind == "audio"
    clip = Clip(
        float(c.get("start", 0.0)),
        float(c["length"]),
        audio=audio,
        file_path=str(c.get("file", "")),
        name=str(c.get("name", "")),
        parent=track,
    )
    clip.muted = bool(c.get("muted", False))
    notes: Sequence[Sequence[float]] = c.get("notes", ())
    if notes:
        clip.add_new_notes([MidiNoteSpecification(int(n[0]), n[1], n[2], n[3] if len(n) > 3 else 100) for n in notes])
    return clip


# --------------------------------------------------------------------------- the mix desk's shape

HW002_BUSES = {  # bus -> its channels, as contrib/mixdesk/desk.json names them
    "Kick bus": ("kick",),
    "Hats bus": ("p2-ch1", "p2-ch27", "p2-oh", "p2-rd1", "p2-rd2"),
    "Perc bus": ("p1-oh66", "p1-rd"),
    "Break bus": ("break-beatbox", "break-chop", "break-horn", "break-stab"),
    "Chord and splash bus": ("chord", "crash", "splash"),
    "Transitions bus": ("fx-downlifter", "fx-fill", "fx-reverse", "fx-riser"),
}
HW002_DESK = {  # bus -> the desk devices on it (contrib/mixdesk/workspace.py adds them)
    "Kick bus": ("desk EQ", "desk Sat", "desk Glue"),
    "Hats bus": ("desk EQ", "desk Sat"),
    "Perc bus": ("desk EQ",),
    "Break bus": ("desk EQ", "desk Sat", "desk Glue"),
    "Chord and splash bus": ("desk EQ", "desk Sat"),
    "Transitions bus": ("desk EQ",),
}
MONITORS = ("mon A", "mon B", "mon C1", "mon C2", "mon C3", "mon C4")
END_BEAT = 160.0  # 40 bars at 160 BPM, as pager.py's END_BEAT


def _desk_device(name: str) -> dict[str, Any]:
    """The desk's devices start where they change nothing: Saturator and Glue at 0 % wet."""
    kind = {"desk EQ": "EQ Eight", "desk Sat": "Saturator", "desk Glue": "Glue Compressor"}[name]
    params = {"Dry/Wet": 0.0} if kind != "EQ Eight" else {}
    return {"device": kind, "name": name, "params": params}


def hw002_like_spec() -> dict[str, Any]:
    """The dict hw002_like() builds: neutral made-up values in the shape the mix desk expects."""
    tracks: list[dict[str, Any]] = []
    for bus, channels in HW002_BUSES.items():
        for ch in channels:
            tracks.append(
                {
                    "name": ch,
                    "output": bus,
                    "clips": [{"start": 0.0, "length": END_BEAT, "file": f"/fake/{ch}.wav"}],
                    "devices": ["EQ Eight"] if ch == "kick" else [],
                }
            )
        tracks.append({"name": bus, "monitoring": 0, "devices": [_desk_device(d) for d in HW002_DESK[bus]]})
    for mon in MONITORS:
        start = 0.0 if mon in ("mon A", "mon B") else 64.0
        tracks.append(
            {
                "name": mon,
                "mute": True,
                "clips": [{"start": start, "length": END_BEAT - start, "file": f"/fake/{mon}.wav"}],
            }
        )
    return {
        "tempo": 160.0,
        "loop_start": 0.0,
        "loop_length": 64.0,
        "returns": [
            {"name": "Space", "devices": [{"device": "Reverb", "name": "Reverb"}]},
            {"name": "Echo", "devices": [{"device": "Echo", "name": "Echo"}]},
        ],
        "tracks": tracks,
        "main": {
            "devices": [
                _desk_device("desk Glue"),
                {"device": "Utility", "name": "desk Utility"},
                {"device": "Utility", "name": "desk headroom", "params": {"Output": -6.0 / 35.0}},
            ]
        },
    }


def hw002_like() -> Song:
    """A set shaped like the HW002 finishing workspace: channels routed to six buses with the desk's devices, the
    returns A-Space (Reverb) and B-Echo (Echo), Main with desk Glue, desk Utility and desk headroom (-6 dB), and
    the muted monitor tracks mon A, mon B, mon C1-C4. Every value is neutral and made up."""
    return fake_set(hw002_like_spec())
