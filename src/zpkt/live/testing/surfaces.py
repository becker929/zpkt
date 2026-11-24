"""A fake MiniLab 3 control surface, shaped as Live's factory script shows it to contrib/mixdesk/pager.py.

The pager finds the surface by its class name, grabs each control's StackingResource above the factory script's
layers, and listens to MIDI values. A test plays a control with `receive(value)` (a knob turned, a pad hit) and
runs what the pager deferred with FakeLive.tick().

    minilab = MiniLab_3()
    live = FakeLive(hw002_like(), surfaces=[minilab])
    minilab.elements.pad_bank_a_raw[1].receive(127)     # pad A2 arms its page
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from hands.testing.lom import MAIN_THREAD


class Resource:
    """A StackingResource: of the clients that grabbed it, the one with the highest priority holds the control."""

    def __init__(self, control: Control) -> None:
        self._control = control
        self._clients: list[tuple[int, Any]] = []

    @property
    def owner(self) -> Any:
        return max(self._clients, key=lambda pc: pc[0])[1] if self._clients else None

    def grab(self, client: Any, priority: int | None = None) -> None:
        self._clients.append((priority or 0, client))
        self._tell()

    def release(self, client: Any) -> None:
        if not any(c is client for _, c in self._clients):
            return
        self._clients = [(p, c) for p, c in self._clients if c is not client]
        client.set_control_element(self._control, False)
        self._tell()

    def _tell(self) -> None:
        top = self.owner
        for _, client in self._clients:
            client.set_control_element(self._control, client is top)


class Control:
    """One knob, fader or pad: listeners get its MIDI value (0-127)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.resource = Resource(self)
        self.sent: list[int] = []  # what the script sent back to the hardware (LEDs, realigns)
        self._listeners: list[Callable[[int], Any]] = []

    def add_value_listener(self, fn: Callable[[int], Any]) -> None:
        self._listeners.append(fn)

    def remove_value_listener(self, fn: Callable[[int], Any]) -> None:
        self._listeners.remove(fn)

    def value_has_listener(self, fn: Callable[[int], Any]) -> bool:
        return fn in self._listeners

    def realign_value(self, value: int) -> None:
        self.sent.append(int(value))

    def send_value(self, value: int, force: bool = False) -> None:
        self.sent.append(int(value))

    def receive(self, value: int) -> None:
        """MIDI in: what the hardware sends when it is played. Runs on Live's main thread, as in Live."""
        with MAIN_THREAD:
            for fn in list(self._listeners):
                fn(int(value))


class MiniLab_3:  # the factory script's class name, which pager.py looks for
    """The MiniLab 3's controls: 8 encoders, 4 faders, two banks of 8 pads, the big encoder."""

    def __init__(self) -> None:
        self.elements = SimpleNamespace(
            encoders_raw=tuple(Control(f"Encoder {k + 1}") for k in range(8)),
            volume_fader=Control("Fader 1"),
            send_a_fader=Control("Fader 2"),
            send_b_fader=Control("Fader 3"),
            pan_fader=Control("Fader 4"),
            pad_bank_a_raw=tuple(Control(f"Pad A{k + 1}") for k in range(8)),
            pad_bank_b_raw=tuple(Control(f"Pad B{k + 1}") for k in range(8)),
            display_encoder=Control("Display Encoder"),
        )
        self.rebuilds = 0
        self._scheduled: list[tuple[int, Callable[[], Any]]] = []

    def request_rebuild_midi_map(self) -> None:
        self.rebuilds += 1

    def schedule_message(self, delay_in_ticks: int, callback: Callable[[], Any]) -> None:
        self._scheduled.append((int(delay_in_ticks), callback))

    def tick(self) -> int:
        """One of Live's 100 ms ticks: run what is due. Returns how many callbacks ran."""
        due = [cb for delay, cb in self._scheduled if delay <= 1]
        self._scheduled = [(delay - 1, cb) for delay, cb in self._scheduled if delay > 1]
        for cb in due:
            cb()
        return len(due)
