"""Watching parameters in Live: ask the Remote Script to push a parameter's changes instead of polling for them.

The wire shapes (lib/contracts/live-watch.schema.json) are:

    -> {"watch": [{"id": "k1", "code": "find_value(song, 'Kick bus/volume')"}, ...]}   replaces this connection's watches
    <- {"status": "ok", "watching": ["k1", ...], "failed": {"k2": "why"}}
    -> {"unwatch": true}
    <- {"status": "ok", "watching": [], "failed": {}}
    <- {"push": "watch", "changes": [{"id": "k1", "value": 0.4}], "at": 1700000000.5}     whenever a change settles

This module is the library side: it builds the messages for a set of state keys, reads the reply and the pushes. The
app owns the connection and gives it in (an object with `send`, as LiveClient and FakeLive have). The watches live as
long as the connection, and the Remote Script takes them off when it closes. Nothing here knows what a page is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from zpkt.live import inlive
from zpkt.live.transport import LiveError


class Sender(Protocol):
    """A connection that can carry a raw message (LiveClient.send, FakeLive.send)."""

    def send(self, message: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Watching:
    """What the Remote Script says it watches now, and why it could not watch the rest."""

    ids: tuple[str, ...]
    failed: Mapping[str, str]


@dataclass(frozen=True)
class Change:
    """One watched value that changed: its id (what the client named it) and its raw value now."""

    id: str
    value: Any


@dataclass(frozen=True)
class Push:
    changes: tuple[Change, ...]
    at: float  # seconds since the epoch, on Live's side


def _code_for(key: str) -> str:
    """Code that gives the parameter (or (object, attribute) pair) a state key names, with the resolver defined."""
    return inlive.with_source(f"result = find_value(song, {key!r})", "find")


def watch_message(keys: Mapping[str, str]) -> dict[str, Any]:
    """The request to watch `keys` ({id: state key}); it replaces what was watched before."""
    return {"watch": [{"id": wid, "code": _code_for(key)} for wid, key in keys.items()]}


def unwatch_message() -> dict[str, Any]:
    return {"unwatch": True}


def parse_watching(reply: Mapping[str, Any]) -> Watching:
    """The ids watched and the failures from a reply; LiveError with the server's words if it was an error."""
    if reply.get("status") != "ok":
        raise LiveError(f"Live would not watch: {reply.get('error') or reply}")
    return Watching(tuple(reply.get("watching", ())), dict(reply.get("failed", {})))


def parse_push(message: Any) -> Push | None:
    """A push line as data; None for anything that is not a watch push (so a stray line is ignored, never a crash)."""
    if not (
        isinstance(message, Mapping) and message.get("push") == "watch" and isinstance(message.get("changes"), list)
    ):
        return None
    changes = tuple(
        Change(str(c["id"]), c.get("value")) for c in message["changes"] if isinstance(c, Mapping) and "id" in c
    )
    try:
        at = float(message.get("at", 0.0))
    except (TypeError, ValueError):
        at = 0.0
    return Push(changes, at)


def watch(live: Sender, keys: Mapping[str, str]) -> Watching:
    """Ask Live to watch `keys` ({id: state key}) from now on; the old watches of this connection are dropped."""
    return parse_watching(live.send(watch_message(keys)))


def unwatch(live: Sender) -> Watching:
    return parse_watching(live.send(unwatch_message()))
