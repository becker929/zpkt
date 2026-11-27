"""A fake MiniLab 3 control surface, shaped as Live's factory script shows it to contrib/mixdesk/pager.py.

The pager finds the surface by its class name, grabs each control's StackingResource above the factory script's
layers, and listens to MIDI values. A test plays a control with `receive(value)` (a knob turned, a pad hit) and
runs what the pager deferred with FakeLive.tick().

    minilab = MiniLab_3()
    live = FakeLive(hw002_like(), surfaces=[minilab])
    minilab.elements.pad_bank_a_raw[1].receive(127)     # pad A2 arms its page

What a pad and a knob take back from a script is shaped as Live 12's own MiniLab_3 script has it (its elements.py,
encoder.py and midi.py, and ableton.v3's SysexSendingButtonElement, read from the installed bytecode, read only): a
pad's `send_value(red, green, blue)` is its LED's SysEx message, and a knob's `realign_value()` takes no value. What
the hardware then does with those messages is not known here.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from zpkt.live.testing.lom import MAIN_THREAD

# Live's MiniLab_3/midi.py
SYSEX_HEADER = (240, 0, 32, 107, 127, 66)
LED_HEADER = (*SYSEX_HEADER, 2, 2, 22)
ENCODER_VALUE_HEADER = (*SYSEX_HEADER, 33, 16, 0)
SYSEX_END = 247
PAD_SYSEX_IDS = (*range(52, 60), *range(68, 76))  # PAD_ID_TO_SYSEX_ID: pads A1-A8 are 52-59, B1-B8 are 68-75
FIRST_ENCODER_SYSEX_ID = 7  # ENCODER_ID_TO_SYSEX_ID: knobs 1-8 are 7-14


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
    """One fader or the big encoder (and the base of a pad and a knob): listeners get its MIDI value (0-127)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.resource = Resource(self)
        self.sent: list[Any] = []  # what the script sent back to the hardware: a value, or a pad's colour
        self.messages: list[tuple[int, ...]] = []  # ... and the SysEx messages among it, whole
        self._listeners: list[Callable[[int], Any]] = []

    def add_value_listener(self, fn: Callable[[int], Any]) -> None:
        self._listeners.append(fn)

    def remove_value_listener(self, fn: Callable[[int], Any]) -> None:
        self._listeners.remove(fn)

    def value_has_listener(self, fn: Callable[[int], Any]) -> bool:
        return fn in self._listeners

    def send_value(self, value: int, force: bool = False) -> None:
        self.sent.append(int(value))

    def send_midi(self, message: tuple[int, ...]) -> bool:
        self.messages.append(tuple(int(b) for b in message))
        return True

    def receive(self, value: int) -> None:
        """MIDI in: what the hardware sends when it is played. Runs on Live's main thread, as in Live."""
        with MAIN_THREAD:
            for fn in list(self._listeners):
                fn(int(value))


class Pad(Control):
    """A pad, as the factory script's create_rgb_pad makes it: a button that sends its LED's SysEx message.
    `send_value(*values)` sends LED_HEADER, the pad's id, the values and the end byte, and (the element is
    "optimized") not again while the message is the same; `clear_send_cache()` forgets the last one. Extra keywords
    are swallowed, as in Live.

    `colour` is the light: the last message with three values, each 0-127. GUESS: the hardware ignores a message
    with another number of values, so the fake does (a single 127 is not a colour)."""

    def __init__(self, name: str, sysex_id: int) -> None:
        super().__init__(name)
        self._sysex_identifier = (*LED_HEADER, sysex_id)
        self._last_sent_message: tuple[int, ...] | None = None
        self.colour: tuple[int, int, int] | None = None  # None: never told

    def send_value(self, *value: int, **_: Any) -> None:  # the signature Live's own element has
        message = (*self._sysex_identifier, *(int(v) for v in value), SYSEX_END)
        if message == self._last_sent_message:
            return
        self._last_sent_message = message
        self.send_midi(message)
        self.sent.append(tuple(int(v) for v in value) if len(value) != 1 else int(value[0]))
        if len(value) == 3 and all(0 <= int(v) <= 127 for v in value):
            self.colour = (int(value[0]), int(value[1]), int(value[2]))

    def clear_send_cache(self) -> None:
        self._last_sent_message = None

    @property
    def lit(self) -> bool:
        """Is the pad's light on (any colour but black)?"""
        return self.colour is not None and any(self.colour)


class Encoder(Control):
    """A knob, as the factory script's RealigningEncoderElement: `realign_value()` takes no value. It sends the
    value the script last mapped to it (else the one the knob last sent, else 0) as SysEx, under `_sysex_header`,
    so the hardware counts on from there. `sent` gets each value so sent."""

    def __init__(self, name: str, sysex_id: int) -> None:
        super().__init__(name)
        self._sysex_header = (*ENCODER_VALUE_HEADER, sysex_id, 0)
        self._last_mapped_value: int | None = None
        self._last_received_value: int | None = None

    def realign_value(self) -> None:
        value = self._last_mapped_value or self._last_received_value or 0
        self.send_midi((*self._sysex_header, value, SYSEX_END))

    def send_midi(self, message: tuple[int, ...]) -> bool:
        if tuple(message[: len(self._sysex_header)]) == self._sysex_header:
            self.sent.append(int(message[len(self._sysex_header)]))
        return super().send_midi(message)

    def receive(self, value: int) -> None:
        self._last_received_value, self._last_mapped_value = int(value), None
        super().receive(value)


class MiniLab_3:  # the factory script's class name, which pager.py looks for
    """The MiniLab 3's controls: 8 encoders, 4 faders, two banks of 8 pads, the big encoder."""

    def __init__(self) -> None:
        self.elements = SimpleNamespace(
            encoders_raw=tuple(Encoder(f"Encoder {k + 1}", FIRST_ENCODER_SYSEX_ID + k) for k in range(8)),
            volume_fader=Control("Fader 1"),
            send_a_fader=Control("Fader 2"),
            send_b_fader=Control("Fader 3"),
            pan_fader=Control("Fader 4"),
            pad_bank_a_raw=tuple(Pad(f"Pad A{k + 1}", PAD_SYSEX_IDS[k]) for k in range(8)),
            pad_bank_b_raw=tuple(Pad(f"Pad B{k + 1}", PAD_SYSEX_IDS[8 + k]) for k in range(8)),
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
