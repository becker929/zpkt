"""The self-checks a .als must pass before Live loads it, and what changed against the set it was made from.

hands als check FILE [--against SRC]
"""

from __future__ import annotations

import collections
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from zpkt.live.als.file import (
    DEFAULT_TIME,
    TRACK_TAGS,
    _num,
    all_tracks,
    devices,
    event_kind,
    find_device,
    find_track,
    is_pointee_tag,
    load,
    parent_map,
    pointee_elements,
    track_name,
)


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
    return track, " > ".join([track_name(track) if track is not None else "?", *parts])


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
    tree = load(path)  # 1. gzip + XML parse
    root = tree.getroot()
    rep.lines.append(
        f"{os.path.basename(path)}: parses; Creator={root.get('Creator')!r} MinorVersion={root.get('MinorVersion')!r}"
    )
    npi = int(root.find("LiveSet/NextPointeeId").get("Value"))
    pts = pointee_elements(root)
    _check_pointee_ids(rep, pts, npi)
    _check_list_ids(rep, root)
    targets = {e.get("Id"): e for e in pts}
    _check_references(rep, root, targets)
    envs = envelopes(tree)
    _check_envelopes(rep, envs, targets, parent_map(root))
    if against:
        _diff_against(rep, tree, envs, npi, against)
    return rep


def _check_pointee_ids(rep: Report, pts: list[ET.Element], npi: int) -> None:
    """2a. Pointee ids: unique across all pointee tags, all below NextPointeeId."""
    count = collections.Counter(e.get("Id") for e in pts)
    dup = [i for i, n in count.items() if n > 1]
    high = [e.get("Id") for e in pts if int(e.get("Id")) >= npi]
    if dup:
        rep.problems.append(f"{len(dup)} duplicated pointee ids, e.g. {dup[:5]}")
    if high:
        rep.problems.append(f"{len(high)} pointee ids >= NextPointeeId {npi}, e.g. {high[:5]}")
    rep.lines.append(
        f"  pointee ids: {len(pts)} unique={not dup}, max={max(int(i) for i in count)} "
        f"< NextPointeeId={npi}: {not high}"
    )


def _check_list_ids(rep: Report, root: ET.Element) -> None:
    """2b. List ids: unique among siblings."""
    bad = [
        (p.tag, i)
        for p in root.iter()
        for i, n in collections.Counter(
            c.get("Id") for c in p if "Id" in c.attrib and not is_pointee_tag(c.tag)
        ).items()
        if n > 1
    ]
    if bad:
        rep.problems.append(f"{len(bad)} sibling Id clashes, e.g. {bad[:5]}")
    rep.lines.append(f"  sibling (list) ids unique: {not bad}")


def _check_references(rep: Report, root: ET.Element, targets: dict) -> None:
    """3. Every PointeeId resolves."""
    refs = list(root.iter("PointeeId"))
    dangling = [r.get("Value") for r in refs if r.get("Value") not in targets]
    if dangling:
        rep.problems.append(f"PointeeId without target: {dangling}")
    rep.lines.append(f"  PointeeId refs: {len(refs)}, all resolve: {not dangling}")


def _check_envelopes(rep: Report, envs: dict, targets: dict, pm: dict) -> None:
    """4. Track envelopes: they target an AutomationTarget in their own track, events sorted with one default
    first, the event type the parameter takes, values in range."""
    problem = rep.problems.append
    for desc, (tr, env, evs) in envs.items():
        tgt = targets.get(env.find("EnvelopeTarget/PointeeId").get("Value"))
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
    rep.lines.append(f"  track envelopes checked: {len(envs)}")


def _diff_against(rep: Report, tree: ET.ElementTree, envs: dict, npi: int, against: str | os.PathLike) -> None:
    """5. What changed compared with the source set: element counts, devices per track, envelopes."""
    say = rep.lines.append
    src = load(against)
    sroot, root = src.getroot(), tree.getroot()
    say(f"  diff against {os.path.basename(against)}:")
    say(f"    NextPointeeId {sroot.find('LiveSet/NextPointeeId').get('Value')} -> {npi}")
    a = collections.Counter(e.tag for e in sroot.iter())
    b = collections.Counter(e.tag for e in root.iter())
    delta = {t: b[t] - a[t] for t in set(a) | set(b) if b[t] != a[t]}
    keep = [
        t for t in sorted(delta) if is_pointee_tag(t) or t.endswith("Event") or t in ("AutomationEnvelope", "PointeeId")
    ]
    say(f"    elements {sum(b.values()) - sum(a.values()):+d} in all; " + ", ".join(f"{t} {delta[t]:+d}" for t in keep))
    sd = {track_name(t): [d.tag for d in devices(t)] for t in all_tracks(src)}
    for t in all_tracks(tree):
        before, now = sd.get(track_name(t)), [d.tag for d in devices(t)]
        if before != now:
            say(f"    devices on {track_name(t)!r}: {before} -> {now}")
    old = envelopes(src)
    for desc, (_, _, evs) in envs.items():
        new_steps = _steps_of(evs)
        shown = ", ".join(("default" if t == DEFAULT_TIME else _num(t)) + f"={v}" for t, v in new_steps)
        if desc not in old:
            kind = evs[0].tag if evs else "no event"
            say(f"    + envelope {desc}: {len(evs)} x {kind}; beat=value from then on: {shown}")
        elif _steps_of(old[desc][2]) != new_steps:
            say(f"    ~ envelope {desc}: now {shown}")
    for desc in old.keys() - envs.keys():
        say(f"    - envelope {desc}")


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
