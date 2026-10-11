"""What a Live set shows about a track, read offline from its XML (hands.als.load). Read-only.

Facts, not judgments: tracks with their devices, clips, automation and samples; the Main chain;
tempo and locators. hands.library.score turns them into step percentages.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from hands import als

RACKS = ("AudioEffectGroupDevice", "InstrumentGroupDevice", "DrumGroupDevice", "MidiEffectGroupDevice")
INSTRUMENTS = ("DrumGroupDevice", "InstrumentGroupDevice", "OriginalSimpler", "MultiSampler", "InstrumentVector",
               "UltraAnalog", "Operator", "Drift", "Collision", "LoungeLizard", "StringStudio", "InstrumentImpulse",
               "DrumCell", "Meld", "Tension")
REF_NAME = re.compile(r"(^|[\s_\-(])ref(s|erence)?\b", re.I)
TRASH_NAME = re.compile(r"\b(trash|unused|old|bin)\b", re.I)


@dataclass
class Clip:
    start: float  # beats
    end: float
    kind: str     # "audio" | "midi"
    sample: str = ""   # audio clips: the file the clip plays
    notes: int = 0     # midi clips


@dataclass
class Track:
    name: str
    kind: str          # audio | midi | group | return | main
    id: str = ""
    group: str = "-1"  # Id of the enclosing group track, "-1" for none
    muted: bool = False
    devices: list[str] = field(default_factory=list)   # every device that is on, racks flattened
    clips: list[Clip] = field(default_factory=list)    # arrangement clips that are not disabled
    session_clips: int = 0
    envelopes: int = 0
    volume: float = 1.0
    sends: list[float] = field(default_factory=list)
    rack_samples: list[str] = field(default_factory=list)  # samples inside instruments (drum racks, Simpler)
    reference: bool = False  # set by read_set: a reference or parked track, not part of the music

    @property
    def effects(self) -> list[str]:
        """Processing devices: everything on except instruments and racks."""
        return [d for d in self.devices if d not in INSTRUMENTS and d not in RACKS]


@dataclass
class SetFacts:
    path: Path
    mtime: float
    tempo: float
    tracks: list[Track]
    main: Track
    locators: list[tuple[float, str]]
    creator: str = ""

    def by_id(self) -> dict[str, Track]:
        return {t.id: t for t in self.tracks}

    def groups_of(self, track: Track) -> list[Track]:
        """The group tracks around a track, innermost first."""
        out: list[Track] = []
        ids, g = self.by_id(), track.group
        while g != "-1" and g in ids and len(out) < 16:
            out.append(ids[g])
            g = ids[g].group
        return out

    def content_tracks(self) -> list[Track]:
        """Audio and MIDI tracks that are part of the music (not references or parked material)."""
        return [t for t in self.tracks if t.kind in ("audio", "midi") and not t.reference]

    def span(self) -> tuple[float, float]:
        """First and last beat of the music on the timeline."""
        clips = [c for t in self.content_tracks() for c in t.clips]
        if not clips:
            return 0.0, 0.0
        return min(c.start for c in clips), max(c.end for c in clips)

    def seconds(self, beats: float) -> float:
        return beats * 60.0 / self.tempo if self.tempo else 0.0


def _val(el: ET.Element | None, path: str, default: str = "") -> str:
    e = el.find(path) if el is not None else None
    return e.get("Value", default) if e is not None else default


def device_name(d: ET.Element) -> str:
    """A Live device's XML tag, or a plugin's own name ("Dist COLDFIRE", "Pro-L 2")."""
    if d.tag in als.PLUGIN_TAGS:
        desc = d.find("PluginDesc")
        for e in (desc.iter() if desc is not None else ()):
            if e.tag in ("PlugName", "Name") and e.get("Value"):
                return e.get("Value") or ""
        return "Plugin"
    return d.tag


def flat_devices(devices: ET.Element | None) -> list[ET.Element]:
    """The devices in a Devices list and in every rack inside it, in document order."""
    out: list[ET.Element] = []
    for d in list(devices) if devices is not None else []:
        out.append(d)
        for inner in d.iter("Devices"):
            out.extend(list(inner))
    return out


def _clip(c: ET.Element, kind: str) -> Clip | None:
    if _val(c, "Disabled") == "true":
        return None
    try:
        start = float(_val(c, "CurrentStart") or c.get("Time", "0"))
        end = float(_val(c, "CurrentEnd") or start)
    except ValueError:
        return None
    if kind == "audio":
        return Clip(start, end, kind, sample=_val(c, "SampleRef/FileRef/Path"))
    return Clip(start, end, kind, notes=len(c.findall("Notes/KeyTracks/KeyTrack/Notes/MidiNoteEvent")))


def read_track(t: ET.Element) -> Track:
    kind = {"AudioTrack": "audio", "MidiTrack": "midi", "GroupTrack": "group", "ReturnTrack": "return",
            "MainTrack": "main", "MasterTrack": "main"}.get(t.tag, t.tag)
    chain = t.find("DeviceChain")
    devs = flat_devices(t.find("DeviceChain/DeviceChain/Devices"))
    tr = Track(
        name=_val(t, "Name/EffectiveName") or _val(t, "Name/UserName") or t.tag,
        kind=kind, id=t.get("Id", ""), group=_val(t, "TrackGroupId", "-1"),
        muted=_val(chain, "Mixer/Speaker/Manual", "true") == "false",
        devices=[device_name(d) for d in devs if _val(d, "On/Manual", "true") != "false"],
        envelopes=len(t.findall("AutomationEnvelopes/Envelopes/AutomationEnvelope")),
        session_clips=len(t.findall("DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value/*")),
    )
    try:
        tr.volume = float(_val(chain, "Mixer/Volume/Manual", "1"))
        tr.sends = [float(s.get("Value", "0")) for s in t.findall("DeviceChain/Mixer/Sends/TrackSendHolder/Send/Manual")]
    except ValueError:
        pass
    for c in t.findall("DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip"):
        if (clip := _clip(c, "audio")) is not None:
            tr.clips.append(clip)
    for c in t.findall("DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events/MidiClip"):
        if (clip := _clip(c, "midi")) is not None:
            tr.clips.append(clip)
    for d in devs:
        tr.rack_samples += [p.get("Value", "") for p in d.findall(".//SampleRef/FileRef/Path") if p.get("Value")]
    return tr


def read_set(path: str | os.PathLike) -> SetFacts:
    """Read one .als into SetFacts. Raises ValueError for a file that is not a Live set."""
    root = als.load(path).getroot()
    assert root is not None
    ls = root.find("LiveSet")
    assert ls is not None  # als.load refuses a file without one
    main_el = ls.find("MainTrack")
    if main_el is None:
        main_el = ls.find("MasterTrack")  # Live 11 and older
    track_list = ls.find("Tracks")
    tracks = [read_track(t) for t in (list(track_list) if track_list is not None else [])]
    main = read_track(main_el) if main_el is not None else Track("Main", "main")
    try:
        tempo = float(_val(main_el, "DeviceChain/Mixer/Tempo/Manual", "0") or 0)
    except ValueError:
        tempo = 0.0
    locators: list[tuple[float, str]] = []
    for loc in ls.findall("Locators/Locators/Locator"):
        try:
            locators.append((float(_val(loc, "Time", "0")), _val(loc, "Name")))
        except ValueError:
            continue
    facts = SetFacts(Path(path), os.path.getmtime(path), tempo, tracks, main, sorted(locators),
                     root.get("Creator") or "")
    mark_references(facts)
    return facts


def mark_references(facts: SetFacts) -> None:
    """Mark reference and parked tracks: named "ref", inside a "Ref"/"Trash" group, or a muted audio track
    that plays one long file through no devices (an A/B reference dropped on the timeline)."""
    end = max((c.end for t in facts.tracks for c in t.clips), default=0.0)
    for t in facts.tracks:
        names = [t.name] + [g.name for g in facts.groups_of(t)]
        t.reference = any(REF_NAME.search(n) or TRASH_NAME.search(n) for n in names) or (
            t.kind == "audio" and t.muted and len(t.clips) == 1 and not t.devices
            and t.clips[0].end - t.clips[0].start >= 0.5 * max(end, 1.0))
