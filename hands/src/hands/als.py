"""Read and write an Ableton Live set file (.als) offline: knob values and arrangement automation.

Why: the LOM cannot write arrangement automation (Clip.automation_envelope refuses arrangement
clips, and devices on group tracks have no envelope object). A .als file is gzip-compressed XML,
so we edit the XML, load the set once and export once to render P parameter variants
(hands.probe_kit). Nothing here opens Live; `save` writes only the file it is given.

    hands als check FILE [--against SRC]     # self-checks, and what changed against the source
    hands als params FILE TRACK DEVICE       # automatable element names of a device

A knob is (track, device, param), named the way the .als names it (see `resolve`); values are in
the parameter's Manual units, which are not always the LOM's (hands.live.knobs converts).

What the .als holds (Live 12.4.6, schema "12.0_12402")
------------------------------------------------------
* stdlib ElementTree round-trips a Live set byte for byte (tabs, `<X Value="" />` empty tags) as
  long as we write Live's own `<?xml ...?>` line ourselves. Diffs therefore stay minimal.
* Tracks: LiveSet/Tracks/{AudioTrack,MidiTrack,GroupTrack,ReturnTrack} plus LiveSet/MainTrack.
  Name: Name/EffectiveName. Devices: <track>/DeviceChain/DeviceChain/Devices/<DeviceTag Id=..>.
* A parameter is one element inside the device (e.g. <MixDirect>). It holds <Manual Value=..>,
  the knob value in natural units, <MidiControllerRange> Min/Max for numeric params, an
  <AutomationTarget Id=..> and, when modulatable, a <ModulationTarget Id=..>.
* Arrangement automation lives on the TRACK whose device chain contains the device (group
  tracks too; also devices nested in racks):
      <track>/AutomationEnvelopes/Envelopes/AutomationEnvelope Id=..
          EnvelopeTarget/PointeeId Value = Id of the parameter's AutomationTarget
          Automation/Events/{Float|Bool|Enum}Event Id=.. Time=<beats> Value=<Manual units>
  The first event has Time="-63072000" and gives the value before any real event. After the last
  event the value holds.
* Event type (checked on 360 envelopes in local and factory sets): BoolEvent if Manual is
  true/false, FloatEvent if the parameter has a ModulationTarget, otherwise EnumEvent.
* A step (jump) is two events at the SAME Time: old value first, then new value. Live writes it
  this way in 234 of the 355 arrangement float envelopes in the factory sets.

Id rules (checked on every HW002_121_pp_*.als and 80 sets in the Live bundle)
----------------------------------------------------------------------------
* "Pointee" ids are global to the set. They are the Id of every AutomationTarget,
  ModulationTarget, *ModulationTarget (Simpler), Pointee and ControllerTargets.N element. They are
  unique across all of these tags and all lie below LiveSet/NextPointeeId. <PointeeId Value=..>
  (envelope targets) is the only reference to them. A device copied from another set keeps that
  set's ids, so we renumber them from max(NextPointeeId, max id + 1) and raise NextPointeeId.
* Every other Id attribute is a list index, unique only among its siblings: the device Id in its
  Devices list, the AutomationEnvelope Id in Envelopes, the event Id in Events, and so on.
"""
from __future__ import annotations

import collections
import copy
import gzip
import hashlib
import itertools
import os
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'  # exactly what Live writes
DEFAULT_TIME = -63072000  # time of the "default" event that holds the value before the first one
TRACK_TAGS = ("AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack", "MainTrack", "PreHearTrack")
PLUGIN_TAGS = ("PluginDevice", "AuPluginDevice")


# --------------------------------------------------------------------------- load / save

def load(path: str | os.PathLike) -> ET.ElementTree:
    """Read a .als (gzip XML). Comments/declaration are not kept; save() writes Live's declaration."""
    with gzip.open(path, "rb") as f:
        root = ET.fromstring(f.read())
    if root.tag != "Ableton" or root.find("LiveSet") is None:
        raise ValueError(f"{path}: not a Live set (root <{root.tag}>)")
    return ET.ElementTree(root)


def save(tree: ET.ElementTree, path: str | os.PathLike, overwrite: bool = False) -> str:
    """Write the tree as a .als. The root keeps its Creator/MajorVersion/MinorVersion attributes.
    Refuses to replace an existing file unless overwrite=True; writes via a temp file + rename."""
    path = os.fspath(path)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"{path} exists (pass overwrite=True)")
    xml = XML_DECL + ET.tostring(tree.getroot(), encoding="unicode") + "\n"
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(gzip.compress(xml.encode("utf-8"), mtime=0))
    os.replace(tmp, path)
    return path


def xml_hash(path: str | os.PathLike) -> str:
    """SHA-256 of the set's XML (gunzipped), a cache key for "this version of the set".

    Hashing the XML rather than the file ignores the gzip header, so re-compressing the same
    set gives the same key; any change Live saves (including view state) gives a new one.
    """
    with gzip.open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --------------------------------------------------------------------------- navigation

def all_tracks(tree: ET.ElementTree) -> list[ET.Element]:
    ls = tree.getroot().find("LiveSet")
    out = list(ls.find("Tracks"))
    out += [t for t in (ls.find("MainTrack"), ls.find("PreHearTrack")) if t is not None]
    return out


def track_name(track: ET.Element) -> str:
    return track.find("Name/EffectiveName").get("Value")


def find_track(tree: ET.ElementTree, name: str) -> ET.Element:
    """The one audio/MIDI/group/return/main track whose Name/EffectiveName is `name`."""
    hits = [t for t in all_tracks(tree) if track_name(t) == name]
    if len(hits) != 1:
        raise LookupError(f"{len(hits)} tracks named {name!r}")
    return hits[0]


def devices(track: ET.Element) -> list[ET.Element]:
    """Top-level devices of a track, in chain order (rack contents are inside these elements)."""
    d = track.find("DeviceChain/DeviceChain/Devices")
    return list(d) if d is not None else []


def find_device(track: ET.Element, tag: str, index: int = 0) -> ET.Element:
    """The index-th top-level device with XML tag `tag` (e.g. "Reverb", "Eq8"); index=-1 = last."""
    hits = [d for d in devices(track) if d.tag == tag]
    if not hits:
        raise LookupError(f"no <{tag}> on track {track_name(track)!r}: {[d.tag for d in devices(track)]}")
    return hits[index]


def parent_map(root: ET.Element) -> dict:
    return {c: p for p in root.iter() for c in p}


def depth(root: ET.Element, elem: ET.Element) -> int:
    """Number of ancestors of elem, which is also its indentation in tabs in Live's format."""
    stack = [(root, 0)]
    while stack:
        e, d = stack.pop()
        if e is elem:
            return d
        stack.extend((c, d + 1) for c in e)
    raise ValueError("element not in tree")


def is_pointee_tag(tag: str) -> bool:
    """Tags whose Id is a set-global "pointee" id (see module docstring)."""
    return (tag in ("AutomationTarget", "ModulationTarget", "Pointee")
            or tag.endswith("ModulationTarget") or tag.startswith("ControllerTargets."))


def pointee_elements(elem: ET.Element) -> list[ET.Element]:
    return [e for e in elem.iter() if "Id" in e.attrib and is_pointee_tag(e.tag)]


def _append(parent: ET.Element, child: ET.Element, parent_depth: int) -> None:
    """Append child to parent using Live's tab indentation."""
    ET.indent(child, space="\t", level=parent_depth + 1)
    inner, outer = "\n" + "\t" * (parent_depth + 1), "\n" + "\t" * parent_depth
    if len(parent):
        parent[-1].tail = inner
    else:
        parent.text = inner
    child.tail = outer
    parent.append(child)


# --------------------------------------------------------------------------- knobs

def resolve(tree: ET.ElementTree, track: str, device, param: str) -> tuple[ET.Element, ET.Element, str]:
    """(track element, device element, parameter path inside the device) for a knob.

    device: "Mixer" (the track mixer: Volume, Pan, Speaker, Sends/TrackSendHolder/Send),
    ("plugin", PlugName) for a VST/AU device, or (device_tag, index) for a Live device (index
    among devices with that tag; -1 = last). A bare tag means the last device with it.
    param: an XML path for Live devices ("Bands.3/ParameterA/Gain"); a plugin parameter's
    display name ("Drive") for plugins, which resolves to its ParameterValue element.
    """
    tr = find_track(tree, track)
    if device == "Mixer":
        return tr, tr.find("./DeviceChain/Mixer"), param
    if isinstance(device, str):
        device = (device, -1)
    if device[0] == "plugin":
        plugs = [d for d in devices(tr) if d.tag in PLUGIN_TAGS
                 and any(e.get("Value") == device[1] for e in d.find("./PluginDesc").iter() if e.tag in ("PlugName", "Name"))]
        if len(plugs) != 1:
            raise KeyError(f"{track}: {len(plugs)} plugins named {device[1]!r}")
        params = plugs[0].findall("./ParameterList/PluginFloatParameter")
        idx = [i for i, p in enumerate(params, 1) if p.find("./ParameterName").get("Value") == param]
        if len(idx) != 1:
            raise KeyError(f"{track}/{device[1]}: {len(idx)} parameters named {param!r}")
        return tr, plugs[0], f"ParameterList/PluginFloatParameter[{idx[0]}]/ParameterValue"
    return tr, find_device(tr, device[0], device[1]), param


def knob_param(tree: ET.ElementTree, track: str, device, param: str) -> ET.Element:
    """The parameter element of a knob (the one holding Manual and AutomationTarget)."""
    _, dev, path = resolve(tree, track, device, param)
    return param_element(dev, path)


def current_value(tree: ET.ElementTree, track: str, device, param: str) -> float | bool:
    """The knob's value as set (Manual: a float, or a bool for switches)."""
    v = knob_param(tree, track, device, param).find("Manual").get("Value")
    return v == "true" if v in ("true", "false") else float(v)


def param_range(tree: ET.ElementTree, track: str, device, param: str) -> tuple[float, float] | None:
    """(min, max) of a numeric knob in Manual units; None for switches."""
    rng = knob_param(tree, track, device, param).find("MidiControllerRange")
    return None if rng is None else (float(rng.find("Min").get("Value")), float(rng.find("Max").get("Value")))


def set_manual(tree: ET.ElementTree, track: str, device, param: str, value) -> None:
    """Set a knob's static value. Refuses an automated knob: its envelope would override it."""
    tr, dev, path = resolve(tree, track, device, param)
    p = param_element(dev, path)
    if _envelope(tr, p) is not None:
        raise ValueError(f"{track}/{param} is automated; write steps instead")
    p.find("Manual").set("Value", _value(event_kind(p), value, p))


def set_speaker(tree: ET.ElementTree, track: str, on: bool) -> None:
    """Switch a track's activator (Mixer Speaker): False mutes the track."""
    set_manual(tree, track, "Mixer", "Speaker", on)


def rename_track(tree: ET.ElementTree, old: str, new: str) -> ET.Element:
    """Rename a track (EffectiveName and UserName), keeping names unique."""
    if any(track_name(t) == new for t in all_tracks(tree)):
        raise ValueError(f"a track is already named {new!r}")
    tr = find_track(tree, old)
    for tag in ("EffectiveName", "UserName"):
        tr.find(f"./Name/{tag}").set("Value", new)
    return tr


# --------------------------------------------------------------------------- devices

def add_device_from_donor(tree: ET.ElementTree, track: ET.Element, donor) -> ET.Element:
    """Append a copy of `donor` (a device Element, e.g. a Reverb taken from another set, or its XML
    text) to the end of `track`'s device chain. Returns the new element.

    * Every pointee id inside the copy (AutomationTarget, ModulationTarget, Pointee, ...) gets a new
      id from max(NextPointeeId, max id in set + 1), in document order. That keeps the AT/MT
      pairing pattern. PointeeId refs inside the copy are remapped, and NextPointeeId is raised.
    * The device's own Id is a list index: max sibling Id + 1 (0 in an empty chain).
    """
    root = tree.getroot()
    dev = copy.deepcopy(donor if ET.iselement(donor) else ET.fromstring(donor))

    npi = root.find("LiveSet/NextPointeeId")
    used = [int(e.get("Id")) for e in pointee_elements(root)]
    start = max([int(npi.get("Value"))] + [i + 1 for i in used])
    remap = {}
    for k, e in enumerate(pointee_elements(dev)):
        if e.get("Id") in remap:
            raise ValueError(f"donor repeats pointee id {e.get('Id')}")
        remap[e.get("Id")] = str(start + k)
        e.set("Id", remap[e.get("Id")])
    for ref in dev.iter("PointeeId"):
        if ref.get("Value") not in remap:  # would point at something in the donor's set
            raise ValueError(f"donor references pointee {ref.get('Value')} outside itself")
        ref.set("Value", remap[ref.get("Value")])
    npi.set("Value", str(start + len(remap)))

    # Routings (e.g. a compressor sidechain) name tracks of the donor set by Id: not remappable.
    for e in dev.iter("Target"):
        if "Track." in e.get("Value", ""):
            warnings.warn(f"donor routing {e.get('Value')!r} refers to a track of the donor set", stacklevel=2)

    chain = track.find("DeviceChain/DeviceChain/Devices")
    sib = [int(c.get("Id")) for c in chain if "Id" in c.attrib]
    dev.set("Id", str(max(sib) + 1 if sib else 0))
    _append(chain, dev, depth(root, chain))
    return dev


def param_element(device: ET.Element, param_name: str) -> ET.Element:
    """The parameter element `param_name` (an ElementTree path relative to the device, usually
    just the tag, e.g. "MixDirect"; "Bands.3/ParameterA/IsOn" for an Eq8 band) that owns an
    AutomationTarget."""
    p = device.find(param_name)
    if p is None or p.find("AutomationTarget") is None:
        names = [c.tag for c in device if c.find("AutomationTarget") is not None]
        raise KeyError(f"<{device.tag}> has no automatable {param_name!r}; try one of {names}")
    return p


def event_kind(param: ET.Element) -> str:
    """'Bool', 'Float' or 'Enum': the *Event tag Live uses for this parameter (module docstring)."""
    manual = param.find("Manual")
    if manual is not None and manual.get("Value") in ("true", "false"):
        return "Bool"
    return "Float" if param.find("ModulationTarget") is not None else "Enum"


def _num(x: float) -> str:
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def _value(kind: str, v, param: ET.Element) -> str:
    if kind == "Bool":
        if not isinstance(v, bool):
            raise TypeError(f"{param.tag}: bool parameter needs True/False, got {v!r}")
        return "true" if v else "false"
    rng = param.find("MidiControllerRange")
    if rng is not None:
        lo, hi = float(rng.find("Min").get("Value")), float(rng.find("Max").get("Value"))
        if not lo - 1e-6 <= float(v) <= hi + 1e-6:
            raise ValueError(f"{param.tag}: {v} outside [{lo}, {hi}]")
    return str(int(v)) if kind == "Enum" else _num(v)


# --------------------------------------------------------------------------- automation

def _envelope(track: ET.Element, param: ET.Element) -> ET.Element | None:
    """The track's arrangement envelope that targets `param`, if any."""
    target = param.find("AutomationTarget").get("Id")
    envs = track.find("AutomationEnvelopes/Envelopes")
    return next((e for e in envs if e.find("EnvelopeTarget/PointeeId").get("Value") == target), None)


def set_steps(tree: ET.ElementTree, track: ET.Element, device: ET.Element, param_name: str,
              steps, kind: str | None = None) -> ET.Element:
    """Write (or replace) the arrangement envelope of one device parameter as a step function.

    steps: [(start_beat, value), ...], start beats strictly increasing. Each value holds until the
    next step and the last one holds forever. The value before the first step equals the first
    value (stored in the Time=-63072000 default event). Values use the parameter's Manual units.
    Each jump is written as Live writes it: two events at the same Time (old value, new value).
    """
    root = tree.getroot()
    if not any(e is device for e in track.iter()):
        raise ValueError(f"<{device.tag}> is not in track {track_name(track)!r}")
    param = param_element(device, param_name)
    target = param.find("AutomationTarget").get("Id")
    kind = kind or event_kind(param)

    steps = [(float(t), v) for t, v in steps]
    if not steps:
        raise ValueError("no steps")
    if any(t < 0 for t, _ in steps) or any(b[0] <= a[0] for a, b in itertools.pairwise(steps)):
        raise ValueError(f"step times must be >= 0 and strictly increasing: {steps}")
    events = [(DEFAULT_TIME, steps[0][1])]
    prev = None
    for t, v in steps:
        if prev is not None and prev != v:
            events.append((t, prev))  # end of the previous level ...
        events.append((t, v))  # ... and start of the new one, at the same time
        prev = v
    events = [(_num(t), _value(kind, v, param)) for t, v in events]  # validate before editing

    envs = track.find("AutomationEnvelopes/Envelopes")
    env = _envelope(track, param)
    if env is None:
        ids = [int(e.get("Id")) for e in envs]
        env = ET.Element("AutomationEnvelope", Id=str(max(ids) + 1 if ids else 0))
        ET.SubElement(ET.SubElement(env, "EnvelopeTarget"), "PointeeId", Value=target)
        auto = ET.SubElement(env, "Automation")
        ET.SubElement(auto, "Events")
        view = ET.SubElement(auto, "AutomationTransformViewState")
        ET.SubElement(view, "IsTransformPending", Value="false")
        ET.SubElement(view, "TimeAndValueTransforms")
        _append(envs, env, depth(root, envs))
    evs = env.find("Automation/Events")
    for e in list(evs):
        evs.remove(e)
    for i, (t, v) in enumerate(events):
        ET.SubElement(evs, f"{kind}Event", Id=str(i), Time=t, Value=v)
    ET.indent(env, space="\t", level=depth(root, env))
    return env


# --------------------------------------------------------------------------- self-checks

def _describe(pm: dict, target: ET.Element) -> tuple[ET.Element | None, str]:
    """(owning track, 'Track > Device > param') for an AutomationTarget/ModulationTarget element."""
    param = pm[target]
    parts, e, track = [param.tag], pm.get(param), None
    while e is not None:
        if e.tag in TRACK_TAGS:
            track = e
            break
        if pm.get(e) is not None and pm[e].tag == "Devices":
            parts.insert(0, e.tag)
        e = pm.get(e)
    return track, " > ".join([track_name(track) if track is not None else "?"] + parts)


def _steps_of(events: list[ET.Element]) -> list[tuple[float, str]]:
    """Collapse events to (time, value-from-then-on)."""
    out: dict = {}
    for e in events:
        out[float(e.get("Time"))] = e.get("Value")
    return sorted(out.items())


def envelopes(tree: ET.ElementTree) -> dict:
    """{description: (track, envelope element, events)} for every track-level envelope.
    Tracks that share a name (e.g. "kick" in every submix) get "#2", "#3"... after the name."""
    root = tree.getroot()
    pm = parent_map(root)
    targets = {e.get("Id"): e for e in pointee_elements(root)}
    seen: collections.Counter = collections.Counter()
    out = {}
    for tr in all_tracks(tree):
        name = track_name(tr)
        seen[name] += 1
        label = name if seen[name] == 1 else f"{name}#{seen[name]}"
        for env in tr.findall("AutomationEnvelopes/Envelopes/AutomationEnvelope"):
            pid = env.find("EnvelopeTarget/PointeeId").get("Value")
            path = _describe(pm, targets[pid])[1].split(" > ", 1)[1] if pid in targets else f"?{pid}"
            out[f"{label} > {path}"] = (tr, env, list(env.find("Automation/Events")))
    return out


@dataclass
class Report:
    """What `check` looked at (and, with a source, what changed), and what is wrong."""
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        tail = ["OK"] if not self.problems else ["PROBLEMS:", *("  " + p for p in self.problems)]
        return "\n".join(self.lines + tail)


def check(path: str | os.PathLike, against: str | os.PathLike | None = None) -> Report:
    """Self-checks on a .als that Live must load cleanly, plus a diff against its source."""
    rep = Report()
    say, problem = rep.lines.append, rep.problems.append
    tree = load(path)  # 1. gzip + XML parse
    root = tree.getroot()
    pm = parent_map(root)
    say(f"{os.path.basename(path)}: parses; Creator={root.get('Creator')!r} MinorVersion={root.get('MinorVersion')!r}")

    # 2a. pointee ids: unique across all pointee tags, all below NextPointeeId
    npi = int(root.find("LiveSet/NextPointeeId").get("Value"))
    pts = pointee_elements(root)
    count = collections.Counter(e.get("Id") for e in pts)
    dup = [i for i, n in count.items() if n > 1]
    high = [e.get("Id") for e in pts if int(e.get("Id")) >= npi]
    if dup:
        problem(f"{len(dup)} duplicated pointee ids, e.g. {dup[:5]}")
    if high:
        problem(f"{len(high)} pointee ids >= NextPointeeId {npi}, e.g. {high[:5]}")
    say(f"  pointee ids: {len(pts)} unique={not dup}, max={max(int(i) for i in count)} "
        f"< NextPointeeId={npi}: {not high}")

    # 2b. list ids: unique among siblings
    bad = [(p.tag, i) for p in root.iter()
           for i, n in collections.Counter(c.get("Id") for c in p
                                           if "Id" in c.attrib and not is_pointee_tag(c.tag)).items()
           if n > 1]
    if bad:
        problem(f"{len(bad)} sibling Id clashes, e.g. {bad[:5]}")
    say(f"  sibling (list) ids unique: {not bad}")

    # 3. every PointeeId resolves; track envelopes must target an AutomationTarget in that track
    targets = {e.get("Id"): e for e in pts}
    refs = list(root.iter("PointeeId"))
    dangling = [r.get("Value") for r in refs if r.get("Value") not in targets]
    if dangling:
        problem(f"PointeeId without target: {dangling}")
    say(f"  PointeeId refs: {len(refs)}, all resolve: {not dangling}")

    # 4. track envelopes: target kind/track, events sorted, default first, event type, value range
    envs = envelopes(tree)
    for desc, (tr, env, evs) in envs.items():
        pid = env.find("EnvelopeTarget/PointeeId").get("Value")
        tgt = targets.get(pid)
        if tgt is None:
            continue
        if tgt.tag != "AutomationTarget":
            problem(f"{desc}: envelope targets a <{tgt.tag}>")
        if _describe(pm, tgt)[0] is not tr:
            problem(f"{desc}: target is not inside track {track_name(tr)!r}")
        times = [float(e.get("Time")) for e in evs]
        if times != sorted(times):
            problem(f"{desc}: events not sorted by Time")
        if not times or times[0] != DEFAULT_TIME or times.count(DEFAULT_TIME) != 1:
            problem(f"{desc}: needs exactly one default event first (Time={DEFAULT_TIME})")
        if max(collections.Counter(times).values(), default=0) > 2:
            problem(f"{desc}: more than 2 events at one Time")
        kind = event_kind(pm[tgt]) + "Event"
        if any(e.tag != kind for e in evs):
            problem(f"{desc}: expected {kind}, found {sorted({e.tag for e in evs})}")
        if kind == "FloatEvent" and pm[tgt].find("MidiControllerRange") is not None:
            r = pm[tgt].find("MidiControllerRange")
            lo, hi = float(r.find("Min").get("Value")), float(r.find("Max").get("Value"))
            if any(not lo - 1e-6 <= float(e.get("Value")) <= hi + 1e-6 for e in evs):
                problem(f"{desc}: value outside [{lo}, {hi}]")
    say(f"  track envelopes checked: {len(envs)}")

    # 5. what changed compared with the source set
    if against:
        src = load(against)
        sroot = src.getroot()
        say(f"  diff against {os.path.basename(against)}:")
        say(f"    NextPointeeId {sroot.find('LiveSet/NextPointeeId').get('Value')} -> {npi}")
        a = collections.Counter(e.tag for e in sroot.iter())
        b = collections.Counter(e.tag for e in root.iter())
        delta = {t: b[t] - a[t] for t in set(a) | set(b) if b[t] != a[t]}
        keep = [t for t in sorted(delta) if is_pointee_tag(t) or t.endswith("Event")
                or t in ("AutomationEnvelope", "PointeeId")]
        say(f"    elements {sum(b.values()) - sum(a.values()):+d} in all; "
            + ", ".join(f"{t} {delta[t]:+d}" for t in keep))
        sd = {track_name(t): [d.tag for d in devices(t)] for t in all_tracks(src)}
        for t in all_tracks(tree):
            before, now = sd.get(track_name(t)), [d.tag for d in devices(t)]
            if before != now:
                say(f"    devices on {track_name(t)!r}: {before} -> {now}")
        old = envelopes(src)
        for desc, (_, _, evs) in envs.items():
            new_steps = _steps_of(evs)
            shown = ", ".join(("default" if t == DEFAULT_TIME else _num(t)) + f"={v}"
                              for t, v in new_steps)
            if desc not in old:
                kind = evs[0].tag if evs else "no event"
                say(f"    + envelope {desc}: {len(evs)} x {kind}; beat=value from then on: {shown}")
            elif _steps_of(old[desc][2]) != new_steps:
                say(f"    ~ envelope {desc}: now {shown}")
        for desc in old.keys() - envs.keys():
            say(f"    - envelope {desc}")
    return rep


def list_params(path: str | os.PathLike, track: str, device: str, index: int = 0) -> list[str]:
    """One line per automatable parameter of a device: tag, event kind, Manual value, range."""
    dev = find_device(find_track(load(path), track), device, index)
    lines = []
    for p in dev:
        if p.find("AutomationTarget") is None:
            continue
        rng = p.find("MidiControllerRange")
        r = f"[{rng.find('Min').get('Value')}, {rng.find('Max').get('Value')}]" if rng is not None else ""
        lines.append(f"{p.tag:32s} {event_kind(p):6s} Manual={p.find('Manual').get('Value'):14s} {r}")
    return lines
