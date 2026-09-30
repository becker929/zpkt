"""Read an Ableton Live set (.als = gzipped XML) without opening Live.

Answers the Ch.14 signal-flow questions from the file itself:
- tempo, Live version, track list with groups, mute (Speaker) and freeze
- every device on every track, with its on/off state
- the Main (Master) track chain: is a limiter or clipper still on it?
- mixer volume of each track in dB

Read-only. Never writes an .als. Live 12 calls the master "MainTrack";
Live 11 and older call it "MasterTrack". Both are handled.
"""
from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET

import numpy as np

from .util import db, r

TRACK_TAGS = ("AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack")
LOUDNESS_DEVICES = {"Limiter", "Compressor2", "GlueCompressor", "MultibandDynamics", "Saturator",
                    "Roar", "Overdrive", "Redux2", "DrumBuss", "Amp", "Pedal"}
MASTERING_PLUGIN_HINTS = ("limit", "clip", "l2", "pro-l", "ozone", "maxim", "standardclip",
                          "decapitator", "comp", "glue", "saturat")


def _val(el, path, default=None):
    e = el.find(path)
    return e.get("Value") if e is not None else default


def _device_name(d):
    if d.tag == "PluginDevice":
        for p in ("PluginDesc/VstPluginInfo/PlugName", "PluginDesc/Vst3PluginInfo/Name",
                  "PluginDesc/AuPluginInfo/Name"):
            v = _val(d, p)
            if v:
                return v
        return "Plugin"
    return d.tag


def _devices(chain_el):
    out = []
    if chain_el is None:
        return out
    for d in chain_el:
        name = _device_name(d)
        on = _val(d, "On/Manual", "true") == "true"
        user = _val(d, "UserName", "") or ""
        item = {"device": name, "on": on}
        if user:
            item["label"] = user
        if d.tag in ("AudioEffectGroupDevice", "InstrumentGroupDevice", "DrumGroupDevice"):
            inner = []
            for br in d.iter("DeviceChain"):
                inner += _devices(br.find("Devices"))
            if inner:
                item["contains"] = inner
        out.append(item)
    return out


def _track(t):
    name = _val(t, "Name/EffectiveName", "?")
    mixer = t.find("DeviceChain/Mixer")
    vol = float(_val(mixer, "Volume/Manual", "1")) if mixer is not None else 1.0
    speaker = _val(mixer, "Speaker/Manual", "true") == "true" if mixer is not None else True
    return {"type": t.tag, "name": name, "id": t.get("Id"),
            "group_id": _val(t, "TrackGroupId", "-1"),
            "active": speaker, "frozen": _val(t, "Freeze", "false") == "true",
            "volume_db": r(db(vol)) if vol > 0 else -999.0,
            "devices": _devices(t.find("DeviceChain/DeviceChain/Devices"))}


def read(path: str) -> dict:
    with gzip.open(path) as f:
        root = ET.fromstring(f.read())
    ls = root.find("LiveSet")
    main = ls.find("MainTrack")
    if main is None:
        main = ls.find("MasterTrack")
    tracks = [_track(t) for t in ls.find("Tracks") if t.tag in TRACK_TAGS]
    mixer = main.find("DeviceChain/Mixer")
    out = {"creator": root.get("Creator"), "tempo": float(_val(mixer, "Tempo/Manual", "nan")),
           "main_volume_db": r(db(float(_val(mixer, "Volume/Manual", "1")))),
           "main_devices": _devices(main.find("DeviceChain/DeviceChain/Devices")),
           "tracks": tracks}
    out["findings"] = findings(out)
    return out


def _flat(devs):
    for d in devs:
        yield d
        yield from _flat(d.get("contains", []))


def findings(s: dict) -> list[str]:
    f = []
    live_main = [d for d in _flat(s["main_devices"]) if d["on"]]
    lim = [d["device"] for d in live_main
           if d["device"] in LOUDNESS_DEVICES or any(h in d["device"].lower() for h in MASTERING_PLUGIN_HINTS)]
    if lim:
        f.append("Main bus has active dynamics/saturation: " + ", ".join(lim) +
                 ". For a premaster, bypass them (or print two versions).")
    if s["main_volume_db"] and s["main_volume_db"] > 0:
        f.append(f"Main fader above 0 dB ({s['main_volume_db']} dB): gain stage on tracks instead.")
    off = [(t["name"], d["device"]) for t in s["tracks"] for d in _flat(t["devices"]) if not d["on"]]
    if off:
        f.append(f"{len(off)} device(s) are switched off, e.g. " +
                 ", ".join(f"{d} on '{n}'" for n, d in off[:5]) +
                 ". An agent sweeping them would move nothing.")
    muted = [t["name"] for t in s["tracks"] if not t["active"]]
    if muted:
        f.append(f"{len(muted)} track(s) deactivated: " + ", ".join(muted[:8]))
    hot = [t["name"] for t in s["tracks"] if t["volume_db"] > 3]
    if hot:
        f.append("Faders above +3 dB: " + ", ".join(hot[:8]))
    return f
