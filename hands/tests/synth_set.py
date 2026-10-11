"""Small synthetic Live sets for the library tests: only the elements hands.library reads, laid out the way
Live 12 writes them. No real project goes into the tests."""
from __future__ import annotations

import gzip
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

PLUGINS = {"Dist COLDFIRE", "Pro-L 2", "SPAN", "Decapitator", "ValhallaSupermassive", "StandardCLIP"}


@dataclass
class T:
    """A track: name, kind (audio|midi|group|return), devices (Live tags or plugin names; a list inside the list
    is a rack holding those devices), clips as (start_beat, end_beat, sample_path_or_None)."""
    name: str
    kind: str = "audio"
    devices: list = field(default_factory=list)
    clips: list = field(default_factory=list)
    group: int = -1
    muted: bool = False
    envelopes: int = 0
    volume: float = 1.0
    sends: list = field(default_factory=list)
    rack_samples: list = field(default_factory=list)
    session_clips: int = 0
    disabled: list = field(default_factory=list)  # clips (start, end) that are deactivated


def _v(parent: ET.Element, tag: str, value) -> ET.Element:
    e = ET.SubElement(parent, tag)
    e.set("Value", str(value).lower() if isinstance(value, bool) else str(value))
    return e


def _device(parent: ET.Element, spec) -> None:
    if isinstance(spec, list):
        rack = ET.SubElement(parent, "AudioEffectGroupDevice")
        on = ET.SubElement(rack, "On")
        _v(on, "Manual", True)
        chain = ET.SubElement(ET.SubElement(ET.SubElement(rack, "Branches"), "AudioEffectBranch"), "DeviceChain")
        inner = ET.SubElement(ET.SubElement(chain, "AudioToAudioDeviceChain"), "Devices")
        for s in spec:
            _device(inner, s)
        return
    off = spec.startswith("!")
    name = spec.lstrip("!")
    if name in PLUGINS:
        d = ET.SubElement(parent, "PluginDevice")
        _v(ET.SubElement(ET.SubElement(d, "PluginDesc"), "VstPluginInfo"), "PlugName", name)
    else:
        d = ET.SubElement(parent, name)
    _v(ET.SubElement(d, "On"), "Manual", not off)


def _clip(events: ET.Element, kind: str, start, end, sample, disabled=False) -> None:
    c = ET.SubElement(events, "AudioClip" if kind == "audio" else "MidiClip", Time=str(start))
    _v(c, "CurrentStart", start)
    _v(c, "CurrentEnd", end)
    _v(c, "Disabled", disabled)
    if kind == "audio":
        _v(ET.SubElement(ET.SubElement(c, "SampleRef"), "FileRef"), "Path", sample or "/lib/sound.wav")
    else:
        notes = ET.SubElement(ET.SubElement(ET.SubElement(ET.SubElement(c, "Notes"), "KeyTracks"), "KeyTrack"), "Notes")
        for i in range(4):
            ET.SubElement(notes, "MidiNoteEvent", Time=str(i))


def _track(parent: ET.Element, t: T, tid: int) -> None:
    tag = {"audio": "AudioTrack", "midi": "MidiTrack", "group": "GroupTrack", "return": "ReturnTrack",
           "main": "MainTrack"}[t.kind]
    el = ET.SubElement(parent, tag, Id=str(tid)) if t.kind != "main" else ET.SubElement(parent, tag)
    _v(ET.SubElement(el, "Name"), "EffectiveName", t.name)
    _v(el, "TrackGroupId", t.group)
    envs = ET.SubElement(ET.SubElement(el, "AutomationEnvelopes"), "Envelopes")
    for i in range(t.envelopes):
        ET.SubElement(envs, "AutomationEnvelope", Id=str(i))
    chain = ET.SubElement(el, "DeviceChain")
    mixer = ET.SubElement(chain, "Mixer")
    _v(ET.SubElement(mixer, "Volume"), "Manual", t.volume)
    _v(ET.SubElement(mixer, "Speaker"), "Manual", not t.muted)
    sends = ET.SubElement(mixer, "Sends")
    for s in t.sends:
        _v(ET.SubElement(ET.SubElement(sends, "TrackSendHolder"), "Send"), "Manual", s)
    devices = ET.SubElement(ET.SubElement(chain, "DeviceChain"), "Devices")
    for d in t.devices:
        _device(devices, d)
    if t.rack_samples:
        rack = ET.SubElement(devices, "DrumGroupDevice")
        _v(ET.SubElement(rack, "On"), "Manual", True)
        for p in t.rack_samples:
            sampler = ET.SubElement(ET.SubElement(ET.SubElement(rack, "Branches"), "DrumBranch"), "OriginalSimpler")
            _v(ET.SubElement(ET.SubElement(sampler, "SampleRef"), "FileRef"), "Path", p)
    seq = ET.SubElement(chain, "MainSequencer")
    holder = ET.SubElement(seq, "Sample" if t.kind == "audio" else "ClipTimeable")
    events = ET.SubElement(ET.SubElement(holder, "ArrangerAutomation"), "Events")
    for start, end, sample in t.clips:
        _clip(events, "audio" if t.kind == "audio" else "midi", start, end, sample)
    for start, end in t.disabled:
        _clip(events, "audio" if t.kind == "audio" else "midi", start, end, None, disabled=True)
    slots = ET.SubElement(seq, "ClipSlotList")
    for _ in range(t.session_clips):
        value = ET.SubElement(ET.SubElement(ET.SubElement(slots, "ClipSlot"), "ClipSlot"), "Value")
        ET.SubElement(value, "AudioClip" if t.kind == "audio" else "MidiClip")


def write_set(path: Path, tracks: list[T], *, tempo: float = 160.0, main: list | None = None,
              locators: list[tuple[float, str]] = (), mtime: float | None = None) -> Path:
    """Write a gzipped .als. Track Ids are 10, 11, ... in order, so a group's Id is 10 + its index."""
    root = ET.Element("Ableton", Creator="Ableton Live 12.4.6", MajorVersion="5")
    ls = ET.SubElement(root, "LiveSet")
    tr = ET.SubElement(ls, "Tracks")
    for i, t in enumerate(tracks):
        _track(tr, t, 10 + i)
    _track(ls, T("Main", "main", devices=main or []), 0)
    ls.find("MainTrack/DeviceChain/Mixer").append(ET.fromstring(f'<Tempo><Manual Value="{tempo}" /></Tempo>'))
    locs = ET.SubElement(ET.SubElement(ls, "Locators"), "Locators")
    for time, name in locators:
        loc = ET.SubElement(locs, "Locator")
        _v(loc, "Time", time)
        _v(loc, "Name", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(ET.tostring(root)))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def finished_short(folder: Path, name: str = "HW900", mtime: float | None = None) -> Path:
    """A project whose set has everything the heuristics look for: collage, drums, a 36 s Short in three
    sections (160 BPM, 24 bars), a kick chain, groups, a return, levels, and a limiter on Main."""
    lib = "/lib/sounds"
    proc = f"/x/{name}/Samples/Processed/Consolidate"
    tracks = [
        T("kick group", "group", devices=["Eq8", "Roar", "Dist COLDFIRE", "Compressor2"], envelopes=1),   # 10
        T("kick", "midi", devices=["Eq8"], clips=[(0, 96, None)], group=10, rack_samples=[f"{lib}/Kicks/k1.wav"]),
        T("rumble", "audio", devices=["Decapitator", "StereoGain"], clips=[(0, 96, f"{lib}/rumble.wav")], group=10),
        T("hats", "midi", devices=["Eq8"], clips=[(32, 96, None)], rack_samples=[f"{lib}/Cymbals/ch1.wav"],
          sends=[0.3]),
        T("perc", "midi", devices=["StereoGain"], clips=[(32, 96, None)], rack_samples=[f"{lib}/Perc/clap.wav"]),
        T("FX group", "group", devices=["Eq8", "Compressor2"]),                                            # 15
        T("drone", "audio", devices=["StereoGain"], group=15, envelopes=2,
          clips=[(0, 32, f"{lib}/field/drone.wav"), (64, 96, f"{proc}/drone-resampled.wav")]),
        T("voice", "audio", group=15, volume=0.7, clips=[(64, 72, f"{lib}/spoken/voice.wav"),
                                                       (80, 88, f"{lib}/spoken/voice.wav")]),
        T("metal", "audio", group=15, envelopes=2, clips=[(16, 24, f"{lib}/foley/metal.wav"),
                                                        (40, 48, f"{lib}/foley/metal2.wav")]),
        T("game", "audio", group=15, clips=[(0, 8, f"{lib}/game/robot.wav"), (88, 96, f"{lib}/game/robot.wav")]),
        T("ref", "audio", muted=True, clips=[(0, 400, f"{lib}/refs/reference.wav")]),
        T("A-Return", "return", devices=["Reverb"]),
    ]
    return write_set(folder / f"{name}_kick-final.als", tracks, main=["Eq8", ["GlueCompressor", "Limiter"], "SPAN"],
                     mtime=mtime)
