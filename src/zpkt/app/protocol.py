"""The messages between the pager (inside Live), the server and the page: one typed definition per kind.

The pager sends one JSON object per UDP datagram, {"t": KIND, ...}; the server streams those and its own kinds to the
page as server-sent events. The short field names (n, s, r, b, p) are the wire protocol: keep them.
lib/contracts/mixdesk-message.schema.json is these shapes as JSON Schema, written by gen_schema.py
(tests/test_protocol.py fails when the two drift).

`parse_datagram` is the one parse of what arrives from the pager: it returns a typed message or raises BadMessage.
"""

# no "from __future__ import annotations": TypedDict reads NotRequired from the evaluated annotations

import json
from typing import Any, Literal, NotRequired, TypedDict, get_args

# Who moved a control: Anthony (on the page or in Live), the MiniLab, an agent, or the desk itself ("sys": a monitor
# switch bypassing Main's devices, which is not a mix change). The history records it on each entry.
Who = Literal["you", "minilab", "agent", "sys"]
WHO: tuple[str, ...] = get_args(Who)
DEFAULT_WHO: Who = "you"  # a move that says nothing about who made it (every move before the field existed)

# ---- from the pager ------------------------------------------------------------------------------------------------


class ValueMessage(TypedDict):
    """A control's value moved in Live (by anything): page:slot, its 0..1 position, what Live shows, the raw value."""

    t: Literal["v"]
    page: int
    slot: str
    n: float | None
    s: str
    r: float | bool | None
    key: str | None
    sys: NotRequired[bool]  # the desk itself moved it (a monitor switch), so it is not a mix change: who "sys"
    who: NotRequired[Who]  # who moved it; a pager that sends only "sys" is read by who_moved


class PositionMessage(TypedDict):
    """The playhead: beat and whether Live plays."""

    t: Literal["pos"]
    b: float
    p: bool


class MonitorMessage(TypedDict):
    """What is heard: slot A, B, W or C, and the reference C plays."""

    t: Literal["mon"]
    slot: str
    ref: str
    err: NotRequired[str]


class LoopMessage(TypedDict):
    t: Literal["loop"]
    loop: str  # off, build, drop (or "on": a loop the desk did not set)


class PageMessage(TypedDict):
    """A page armed on the MiniLab."""

    t: Literal["page"]
    page: int
    picked: dict[str, bool]


class HardwareMessage(TypedDict):
    """A MiniLab control touched: where it physically is (None for a pad) and whether a fader has picked up."""

    t: Literal["hw"]
    page: int
    slot: str
    hw: float | None
    picked: bool


PagerMessage = ValueMessage | PositionMessage | MonitorMessage | LoopMessage | PageMessage | HardwareMessage


# ---- from the server to the page (server-sent events), besides the pager's own, passed on as they came -------------


class FullMessage(TypedDict):
    """Everything at once (deskstate.DeskState): on connect, after a pager start, after a monitor change."""

    t: Literal["full"]
    state: dict[str, Any]


class HistoryMessage(TypedDict):
    """The history's last entries (history.History.view): moves, reverts and checkpoints, and where undo stands."""

    t: Literal["hist"]
    entries: list[dict[str, Any]]
    pos: int
    can_undo: bool
    can_redo: bool
    checkpoints: list[dict[str, Any]]


class MeterMessage(TypedDict):
    """The live meter on Main: third-octave band centres and their levels in dB."""

    t: Literal["meter"]
    hz: list[float]
    db: list[float]


class SurfaceMessage(TypedDict):
    """How the "Make a surface" job is going."""

    t: Literal["surface"]
    status: Literal["working", "done", "error"]
    msg: str


class DeskMessage(TypedDict):
    """The pages changed (a surface made or removed): load /api/desk again and open page `open`."""

    t: Literal["desk"]
    open: int


PageEvent = PagerMessage | FullMessage | HistoryMessage | MeterMessage | SurfaceMessage | DeskMessage


class BadMessage(ValueError):
    """A datagram that is not one of the pager's messages."""


_NUMBER = (int, float)
_NONE = type(None)
# kind -> (its type, the JSON types each field may hold); which fields are required comes from the type itself
_KINDS: dict[str, tuple[type, dict[str, tuple[type, ...]]]] = {
    "v": (
        ValueMessage,
        {
            "page": (int,),
            "slot": (str,),
            "n": (*_NUMBER, _NONE),
            "s": (str,),
            "r": (*_NUMBER, bool, _NONE),
            "key": (str, _NONE),
            "sys": (bool,),
            "who": (str,),
        },
    ),
    "pos": (PositionMessage, {"b": _NUMBER, "p": (bool,)}),
    "mon": (MonitorMessage, {"slot": (str,), "ref": (str,), "err": (str,)}),
    "loop": (LoopMessage, {"loop": (str,)}),
    "page": (PageMessage, {"page": (int,), "picked": (dict,)}),
    "hw": (HardwareMessage, {"page": (int,), "slot": (str,), "hw": (*_NUMBER, _NONE), "picked": (bool,)}),
}
PAGER_KINDS = tuple(_KINDS)


def parse_message(obj: Any) -> PagerMessage:
    """A decoded datagram as the pager message it is; BadMessage says what is wrong with it."""
    if not isinstance(obj, dict):
        raise BadMessage(f"a pager message is a JSON object, not {type(obj).__name__}")
    kind = obj.get("t")
    known = _KINDS.get(kind) if isinstance(kind, str) else None
    if known is None:
        raise BadMessage(f"unknown message kind {kind!r}; the pager sends {', '.join(PAGER_KINDS)}")
    message_type, fields = known
    for name in message_type.__required_keys__:  # type: ignore[attr-defined]
        if name not in obj:
            raise BadMessage(f"a {kind!r} message needs {name!r}")
    for name, types in fields.items():
        if name not in obj:
            continue
        value = obj[name]
        bad_bool = isinstance(value, bool) and bool not in types  # bool is an int to Python, not to the protocol
        if bad_bool or not isinstance(value, types):
            raise BadMessage(f"{kind!r} field {name!r} is {type(value).__name__}")
    if kind == "v" and "who" in obj and obj["who"] not in WHO:
        raise BadMessage(f"'v' field 'who' is {obj['who']!r}; it is one of {', '.join(WHO)}")
    return obj  # type: ignore[return-value]  # checked field by field above


def who_moved(message: ValueMessage) -> Who:
    """Who moved a control: the message's "who", else "sys" for a desk move ("sys": true), else DEFAULT_WHO."""
    if "who" in message:
        return message["who"]
    return "sys" if message.get("sys") else DEFAULT_WHO


def parse_datagram(data: bytes) -> PagerMessage:
    """One UDP datagram from the pager -> its message; BadMessage for anything else."""
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise BadMessage(f"not JSON ({exc})") from None
    return parse_message(obj)
