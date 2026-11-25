"""The MiniLab's MIDI port: what the adapter needs from one, a fake for tests, and the real one (mido over rtmidi).

A port gives the adapter `Event`s through a callback and takes SysEx back. The real one needs the `midi` extra
(`uv sync --extra midi`: mido and python-rtmidi); it is imported only when a real port is opened, so the app starts
without it. Nothing here opens a port until `open_port` is called, and no test does.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from zpkt.app.adapters import AdapterError
from zpkt.app.minilab.profile import Event, EventKind, Profile

PITCH_REST = 8192


class MidiPort(Protocol):
    """One MIDI input and output pair."""

    name: str

    def start(self, on_event: Callable[[Event], None]) -> None:
        """Begin delivering events (on the port's own thread)."""
        ...

    def send_sysex(self, data: Sequence[int]) -> None:
        """Send a SysEx message: bytes from F0 to F7."""
        ...

    def close(self) -> None: ...


class PortUnavailable(AdapterError):
    """No MIDI port could be opened; the message says what to do."""


class FakePort:
    """A port with no hardware. `receive` plays a message in as if the MiniLab sent it; `sysex` keeps what went out."""

    def __init__(self, name: str = "fake MiniLab 3") -> None:
        self.name = name
        self.sysex: list[list[int]] = []
        self.closed = False
        self._on_event: Callable[[Event], None] | None = None
        self._lock = threading.Lock()

    def start(self, on_event: Callable[[Event], None]) -> None:
        self._on_event = on_event

    def send_sysex(self, data: Sequence[int]) -> None:
        with self._lock:
            self.sysex.append(list(data))

    def close(self) -> None:
        self.closed = True
        self._on_event = None

    def receive(self, kind: EventKind, number: int, value: int, channel: int = 1) -> None:
        """A message from the controller (a note's value is its velocity, 0 for off; pitch bend's number is 0)."""
        if self._on_event is None:
            raise RuntimeError("the fake port has not started")
        self._on_event(Event(kind, channel, number, value))

    def sent(self) -> list[list[int]]:
        with self._lock:
            return list(self.sysex)


# ---- the real one -------------------------------------------------------------------------------------------------------


def event_from_mido(message: Any) -> Event | None:
    """A mido message as an Event; None for what the map does not use (clock, aftertouch, program change ...)."""
    kind = message.type
    if kind == "control_change":
        return Event("cc", message.channel + 1, message.control, message.value)
    if kind in ("note_on", "note_off"):
        return Event("note", message.channel + 1, message.note, message.velocity if kind == "note_on" else 0)
    if kind == "pitchwheel":
        return Event("pitchbend", message.channel + 1, 0, message.pitch + PITCH_REST)
    return None


def choose_name(names: Sequence[str], match: Sequence[str], prefer: Sequence[str]) -> str | None:
    """The port whose name has one of `match` in it, preferring one that also has a word of `prefer`."""
    found = [n for n in names if any(m.lower() in n.lower() for m in match)]
    for word in prefer:
        for n in found:
            if word.lower() in n.lower():
                return n
    return found[0] if found else None


class MidoPort:
    """The MiniLab's ports through mido (rtmidi). Opened by `open_port`."""

    def __init__(self, mido: Any, in_name: str, out_name: str) -> None:
        self.name = in_name
        self._mido, self._in_name, self._out_name = mido, in_name, out_name
        self._in: Any = None
        self._out: Any = None

    def start(self, on_event: Callable[[Event], None]) -> None:
        self._out = self._mido.open_output(self._out_name)

        def deliver(message: Any) -> None:
            event = event_from_mido(message)
            if event is not None:
                on_event(event)

        self._in = self._mido.open_input(self._in_name, callback=deliver)

    def send_sysex(self, data: Sequence[int]) -> None:
        if self._out is not None:
            self._out.send(self._mido.Message("sysex", data=list(data)[1:-1]))  # mido adds F0 and F7

    def close(self) -> None:
        for port in (self._in, self._out):
            if port is not None:
                port.close()
        self._in = self._out = None


def open_port(profile: Profile, name: str | None = None) -> MidoPort:
    """The real MiniLab port (by `name`, ZPKT_MINILAB_PORT, or the profile's match). Raises PortUnavailable with what
    to do when mido is missing or no port matches."""
    import os

    try:
        import mido  # type: ignore[import-not-found,unused-ignore]
        import rtmidi  # type: ignore[import-not-found,unused-ignore]  # noqa: F401
    except ImportError:
        raise PortUnavailable("the MIDI adapter needs the midi extra: run `uv sync --extra midi`") from None
    wanted = name or os.environ.get("ZPKT_MINILAB_PORT")
    match = [wanted] if wanted else list(profile.port_match)
    in_name = choose_name(mido.get_input_names(), match, profile.port_prefer)
    out_name = choose_name(mido.get_output_names(), match, profile.port_prefer)
    if in_name is None or out_name is None:
        raise PortUnavailable(
            f"no MIDI port matches {', '.join(match)}. Is the MiniLab plugged in, and is Live's MiniLab 3 control "
            "surface set to None so Live has let go of it? ZPKT_MINILAB_PORT names the port."
        )
    return MidoPort(mido, in_name, out_name)
