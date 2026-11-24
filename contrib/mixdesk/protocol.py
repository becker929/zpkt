"""The messages between the pager (inside Live), the server and the page: one typed definition per kind.

The pager sends one JSON object per UDP datagram, {"t": KIND, ...}; the server streams those and its own kinds to the
page as server-sent events. The short field names (n, s, r, b, p) are the wire protocol: keep them.
lib/contracts/mixdesk-message.schema.json is the same shapes as JSON Schema (tests/test_protocol.py keeps them equal).

`parse_datagram` is the one parse of what arrives from the pager: it returns a typed message or raises BadMessage.
"""

from __future__ import annotations

import json
from typing import Any, Literal, NotRequired, TypedDict

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
    sys: NotRequired[bool]  # the desk itself moved it (a monitor switch), so it is not a mix change


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


class BadMessage(ValueError):
    """A datagram that is not one of the pager's messages."""


_NUMBER = (int, float)
_FIELDS: dict[str, dict[str, tuple[tuple[type, ...], bool]]] = {
    # kind -> field -> (accepted types, required)
    "v": {
        "page": ((int,), True),
        "slot": ((str,), True),
        "n": ((*_NUMBER, type(None)), False),
        "s": ((str,), False),
        "r": ((*_NUMBER, bool, type(None)), False),
        "key": ((str, type(None)), False),
        "sys": ((bool,), False),
    },
    "pos": {"b": (_NUMBER, True), "p": ((bool,), True)},
    "mon": {"slot": ((str,), True), "ref": ((str,), True), "err": ((str,), False)},
    "loop": {"loop": ((str,), True)},
    "page": {"page": ((int,), True), "picked": ((dict,), False)},
    "hw": {
        "page": ((int,), True),
        "slot": ((str,), True),
        "hw": ((*_NUMBER, type(None)), False),
        "picked": ((bool,), False),
    },
}
PAGER_KINDS = tuple(_FIELDS)


def parse_message(obj: Any) -> PagerMessage:
    """A decoded datagram as the pager message it is; BadMessage says what is wrong with it."""
    if not isinstance(obj, dict):
        raise BadMessage(f"a pager message is a JSON object, not {type(obj).__name__}")
    kind = obj.get("t")
    fields = _FIELDS.get(kind) if isinstance(kind, str) else None
    if fields is None:
        raise BadMessage(f"unknown message kind {kind!r}; the pager sends {', '.join(PAGER_KINDS)}")
    for name, (types, required) in fields.items():
        if name not in obj:
            if required:
                raise BadMessage(f"a {kind!r} message needs {name!r}")
            continue
        value = obj[name]
        bad_bool = isinstance(value, bool) and bool not in types  # bool is an int to Python, not to the protocol
        if bad_bool or not isinstance(value, types):
            raise BadMessage(f"{kind!r} field {name!r} is {type(value).__name__}")
    return obj  # type: ignore[return-value]  # checked field by field above


def parse_datagram(data: bytes) -> PagerMessage:
    """One UDP datagram from the pager -> its message; BadMessage for anything else."""
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise BadMessage(f"not JSON ({exc})") from None
    return parse_message(obj)
