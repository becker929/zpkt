"""What the desk knows about Live, and the pure rules that change it: the server's functional core.

`reduce` folds one pager message into the state, `with_snapshot` folds in a whole snapshot (a pager start or a
reattach), and the other functions decide what the page and Live are sent: a control's history label, the loudness
match of A, B and the reference, and where a seek may land. Plain data in, new data out; server.py owns the one
mutable copy, its lock and the I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypedDict

import protocol as P

SLOTS = ("A", "B", "W", "C")  # what is heard: the original render, the recipe's render, the working mix, the reference
LOOPS = ("off", "build", "drop")


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
    """The whole state the page is sent as {"t": "full", "state": ...}; "values" is keyed "page:slot"."""

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
    }


# ---- one pager message ---------------------------------------------------------------------------------------------


def _value(state: DeskState, m: Any, now: float) -> DeskState:
    key = f"{m['page']}:{m['slot']}"
    value: ControlValue = {**state["values"].get(key, {})}
    value.update({k: m[k] for k in ("n", "s", "r", "key") if k in m})  # type: ignore[misc]
    return {**state, "values": {**state["values"], key: value}}


def _position(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "pos": float(m["b"]), "playing": bool(m["p"])}


def _monitor(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "monitor": {"slot": m["slot"], "ref": m["ref"]}}


def _loop(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "loop": m["loop"]}


def _page(state: DeskState, m: Any, now: float) -> DeskState:
    return {**state, "page": m["page"], "picked": {}}


def _hardware(state: DeskState, m: Any, now: float) -> DeskState:
    new: DeskState = {**state, "touch": {"page": m["page"], "slot": m["slot"], "at": now}}
    if m.get("hw") is not None and m["slot"].startswith("f"):  # only faders pick up, so only their place is kept
        new["hw"] = {**state["hw"], m["slot"]: m["hw"]}
        new["picked"] = {**state["picked"], m["slot"]: m.get("picked", False)}
    return new


_REDUCERS: dict[str, Callable[[DeskState, Any, float], DeskState]] = {
    "v": _value,
    "pos": _position,
    "mon": _monitor,
    "loop": _loop,
    "page": _page,
    "hw": _hardware,
}
assert set(_REDUCERS) == set(P.PAGER_KINDS), "every pager message kind has a reducer"


def reduce(state: DeskState, message: P.PagerMessage, now: float) -> DeskState:
    """The state after one pager message (`now` stamps a touch). The input state is not changed."""
    return _REDUCERS[message["t"]](state, message, now)


# ---- a whole snapshot ----------------------------------------------------------------------------------------------

SNAPSHOT_KEYS = ("page", "attached", "values", "hw", "picked", "monitor", "pos", "playing")


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
    return new


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


def seek_beat(beat: float, slot: str, align_beat: float) -> float:
    """Where a seek lands: the reference (slot C) only exists from the drop."""
    return max(beat, align_beat) if slot == "C" else beat
