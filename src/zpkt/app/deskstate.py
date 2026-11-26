"""What the desk knows about Live, and the pure rules that change it: the server's functional core.

`reduce` folds one pager message into the state, `with_snapshot` folds in a whole snapshot (a pager start or a
reattach), and the other functions decide what the page and Live are sent: a control's history label, the loudness
match of A, B and the reference, and where a seek may land. Plain data in, new data out; server.py owns the one
mutable copy, its lock and the I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypedDict

from zpkt.app import protocol as P

SLOTS = ("A", "B", "W", "C")  # what is heard: the original render, the recipe's render, the working mix, the reference
LOOPS = ("off", "whole", "build", "drop")  # the transport's loop: none, the whole song, its beginning, its peak


class MonitorChoice(TypedDict):
    slot: str
    ref: str


class Touch(TypedDict):
    """The control last touched on the MiniLab, and when (seconds since the epoch)."""

    page: int
    slot: str
    at: float


class ControlValue(TypedDict, total=False):
    """One control as the pager reports it: n (0..1), s (what Live shows), r (raw), key (its state key), q, err."""

    n: float | None
    s: str
    r: float | bool | None
    key: str | None
    q: bool
    err: str | None


class DeskState(TypedDict):
    """The whole state the page is sent as {"t": "full", "state": ...}; "values" is keyed "page:slot". The server
    adds "gains" when it sends it (see matched_gains)."""

    page: int
    attached: bool
    values: dict[str, ControlValue]
    hw: dict[str, float]
    picked: dict[str, bool]
    live: str
    touch: Touch | None
    monitor: MonitorChoice
    match: bool
    pos: float
    playing: bool
    loop: str
    set: str  # the open set's name as the pager reads it ("" before it has, or from an older pager)
    tempo: float | None  # Live's tempo in BPM; None until the pager says
    sig: list[int] | None  # the time signature, [4, 4]
    length: float | None  # the arrangement's length in beats (its last event)
    loop_span: list[float] | None  # the loop brace, [start, length] in beats; None until the pager says
    loops: dict[str, list[float]]  # the spans the transport can loop, by name: [start, length] in beats
    solo: list[str]  # the tracks that are soloed, by their names in state keys
    mute: list[str]  # ... and muted (the monitor's own tracks are never listed)
    meter: bool | None  # whether the spectrum's device is on Main; None until the pager says


def initial() -> DeskState:
    return {
        "page": 0,
        "attached": False,
        "values": {},
        "hw": {},
        "picked": {},
        "live": "starting",
        "touch": None,
        "monitor": {"slot": "W", "ref": "C1"},
        "match": True,
        "pos": 0.0,
        "playing": False,
        "loop": "off",
        "set": "",
        "tempo": None,
        "sig": None,
        "length": None,
        "loop_span": None,
        "loops": {},
        "solo": [],
        "mute": [],
        "meter": None,
    }


# ---- one pager message ---------------------------------------------------------------------------------------------


def _value(state: DeskState, m: Any, now: float) -> DeskState:
    key = f"{m['page']}:{m['slot']}"
    value: ControlValue = {**state["values"].get(key, {})}
    value.update({k: m[k] for k in ("n", "s", "r", "key") if k in m})  # type: ignore[typeddict-item]
    return {**state, "values": {**state["values"], key: value}}


def _position(state: DeskState, m: Any, now: float) -> DeskState:
    new: DeskState = {**state, "pos": float(m["b"]), "playing": bool(m["p"])}
    if m.get("bpm"):  # the pager sends the tempo along with the playhead: no call of its own
        new["tempo"] = float(m["bpm"])
    return new


def _monitor(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "monitor": {"slot": m["slot"], "ref": m["ref"]}}


def _loop(state: DeskState, m: Any, now: float) -> DeskState:
    new: DeskState = {**state, "loop": m["loop"]}
    if "start" in m and "length" in m:
        new["loop_span"] = [float(m["start"]), float(m["length"])]
    return new


def _flags(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "solo": [str(x) for x in m["solo"]], "mute": [str(x) for x in m["mute"]]}


def _page(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "page": m["page"], "picked": {}}


def _hardware(state: DeskState, m: Any, now: float) -> DeskState:
    new: DeskState = {**state, "touch": {"page": m["page"], "slot": m["slot"], "at": now}}
    if m.get("hw") is not None and m["slot"].startswith("f"):  # only faders pick up, so only their place is kept
        new["hw"] = {**state["hw"], m["slot"]: m["hw"]}
        new["picked"] = {**state["picked"], m["slot"]: m.get("picked", False)}
    return new


def _pad(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "touch": {"page": m["page"], "slot": m["slot"], "at": now}}


_REDUCERS: dict[str, Callable[[DeskState, Any, float], DeskState]] = {
    "v": _value,
    "pos": _position,
    "mon": _monitor,
    "loop": _loop,
    "page": _page,
    "hw": _hardware,
    "pad": _pad,
    "flags": _flags,
    "arr": lambda state, m, now: state,  # nothing of the arrangement is in the state: the desk reads it when asked
}
assert set(_REDUCERS) == set(P.PAGER_KINDS), "every pager message kind has a reducer"


def reduce(state: DeskState, message: P.PagerMessage, now: float) -> DeskState:
    """The state after one pager message (`now` stamps a touch). The input state is not changed."""
    return _REDUCERS[message["t"]](state, message, now)


# ---- a whole snapshot ----------------------------------------------------------------------------------------------

SNAPSHOT_KEYS = (
    "page",
    "attached",
    "values",
    "hw",
    "picked",
    "monitor",
    "pos",
    "playing",
    "set",
    "tempo",
    "sig",
    "length",
    "loop_span",
    "loops",
    "meter",
)


def loop_from_snapshot(reported: Any, current: str) -> str:
    """The loop mode from a snapshot: a name, or (an older pager) a bool: off, or "on" unless a mode is known."""
    if isinstance(reported, str):
        return reported
    if not reported:
        return "off"
    return current if current != "off" else "on"


def with_snapshot(state: DeskState, snapshot: Mapping[str, Any] | None, status: str) -> DeskState:
    """The state after the pager's snapshot (None: nothing new from Live) with Live's status line."""
    new: DeskState = {**state, "live": status}
    if snapshot:
        new.update({k: snapshot[k] for k in SNAPSHOT_KEYS if k in snapshot})  # type: ignore[typeddict-item]
        if "loop" in snapshot:
            new["loop"] = loop_from_snapshot(snapshot["loop"], state["loop"])
        flags = snapshot.get("flags")
        if isinstance(flags, Mapping):
            new["solo"], new["mute"] = list(flags.get("solo", [])), list(flags.get("mute", []))
    return new


def flag_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[tuple[str, bool]]:
    """The solo and mute flags that differ between two states: [("Kick bus/solo", True), ...] as state keys."""
    out: list[tuple[str, bool]] = []
    for flag in ("solo", "mute"):
        was, now = set(before.get(flag) or []), set(after.get(flag) or [])
        out += [(f"{name}/{flag}", name in now) for name in sorted(was ^ now)]
    return out


def colour(value: Any) -> str:
    """Live's colour (0xRRGGBB as a number) as "#rrggbb"; "" when Live gave none."""
    try:
        return f"#{int(value) & 0xFFFFFF:06x}" if int(value) else ""
    except (TypeError, ValueError):
        return ""


def arrangement_view(read: Mapping[str, Any], set_name: str, per_bar: float) -> dict[str, Any]:
    """The song in Live as the page draws it, from the pager's read: one lane per track, its arrangement clips as
    regions in beats, the locators, and how many bars it all spans. A region has an id that holds while it stays
    where it is ("t3@16": track 3, starting at beat 16), so it can be edited by id later."""
    tracks = []
    end = float(read.get("length") or 0.0)
    for t in read.get("tracks", []):
        regions = []
        for start, stop, name, color, muted in t.get("clips", []):
            regions.append(
                {
                    "id": f"t{t['i']}@{float(start):g}",
                    "start": float(start),
                    "end": float(stop),
                    "name": str(name),
                    "color": colour(color) or colour(t.get("color")),
                    "muted": bool(muted),
                }
            )
            end = max(end, float(stop))
        tracks.append(
            {
                "id": f"t{t['i']}",
                "name": str(t.get("name", "")),
                "color": colour(t.get("color")),
                "muted": bool(t.get("mute")),
                "regions": regions,
            }
        )
    locators = [{"beat": float(b), "name": str(n)} for b, n in read.get("cues", [])]
    per = per_bar or 4.0
    return {
        "set": set_name,
        "beats_per_bar": per,
        "bars": max(1, -int(-end // per)) if end else 0,
        "tracks": tracks,
        "locators": locators,
    }


def song_facts(state: Mapping[str, Any]) -> dict[str, Any]:
    """What the page's identity line says of the song: tempo, time signature, the bar the playhead is in and how many
    bars the arrangement has. A fact Live has not given is None."""
    sig = state.get("sig") or None
    per_bar = sig[0] * 4.0 / sig[1] if sig and sig[1] else 4.0
    length = state.get("length")
    return {
        "tempo": state.get("tempo"),
        "sig": list(sig) if sig else None,
        "beats_per_bar": per_bar,
        "bars": max(1, -int(-float(length) // per_bar)) if length else None,
    }


# ---- what the server decides ---------------------------------------------------------------------------------------


def control_label(spec: Mapping[str, Any]) -> str:
    """How the history names a desk control ("Kick bus volume", "Hats bus: desk EQ 7 Gain A", "Kick bus: Sub")."""
    param, track = spec["param"], spec["track"]
    if spec.get("label"):
        return f"{track}: {spec['label']}"
    if param in ("volume", "pan", "mute", "solo"):
        return f"{track} {param}"
    if param.startswith("send:"):
        return f"{track} send {param[5:]}"
    return f"{track}: {spec.get('device', '')} {param}"


def labels(pages: list[dict[str, Any]], values: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """{state key: label} for the snapshot's controls ("page:slot" -> its spec in `pages`). Macro parts and slots no
    page names have no label."""
    out: dict[str, str] = {}
    for page_slot, v in values.items():
        page, slot = page_slot.split(":", 1)
        index = int(page)
        spec = pages[index]["controls"].get(slot) if 0 <= index < len(pages) else None
        if v.get("key") and spec and "param" in spec:
            out.setdefault(v["key"], control_label(spec))
    return out


def matched_gain_db(sources: Mapping[str, Any], slot: str, ref: str, match: bool) -> float:
    """Loudness match: bring A, B and the reference to the level of the quietest drop of the three. W (the working
    mix, live) is never changed, nor anything when the match is off or a source has not been analysed."""
    if not match or slot == "W":
        return 0.0
    ids = ["A", "B", ref]
    if not all(i in sources for i in ids):
        return 0.0
    lufs = {i: float(sources[i]["sections"]["drop"]["lufs"]) for i in ids}
    return min(lufs.values()) - lufs[ref if slot == "C" else slot]


def matched_gains(sources: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """For each reference: the gain in dB that matches A, B and C (that reference) when the match is on. The page
    shows and draws these; the pager plays them (matched_gain_db)."""
    refs = [i for i in sources if i not in ("A", "B")]
    return {
        ref: {slot: round(matched_gain_db(sources, slot, ref, True), 3) for slot in ("A", "B", "C")} for ref in refs
    }


def seek_beat(beat: float, slot: str, align_beat: float) -> float:
    """Where a seek lands: the reference (slot C) only exists from the drop."""
    return max(beat, align_beat) if slot == "C" else beat
