"""The MiniLab 3 controller profile: every control, its MIDI message, and where that came from.

The data is lib/contracts/minilab3-profile.json (its schema is minilab3-profile.schema.json). Every item in it is
marked unverified: some numbers were read from Live's installed MiniLab_3 script, some are the usual meaning of a MIDI
message, one or two are not known at all. Nothing was checked at the hardware. ZPKT_MINILAB_PROFILE names another file
(a profile you corrected at the MiniLab), and `parse_profile` rejects a bad one with a sentence that says what to fix.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from zpkt.app.adapters import AdapterError

PROFILE_FILE = "minilab3-profile.json"
EventKind = Literal["cc", "note", "pitchbend"]
KINDS: tuple[str, ...] = ("cc", "note", "pitchbend")


class ProfileError(AdapterError, ValueError):
    """The profile file is not usable; the message says what to fix."""


@dataclass(frozen=True)
class Event:
    """One MIDI message from the controller, in plain data. `channel` counts from 1.

    A note is "note" whatever its direction: `value` is its velocity, and 0 for a note off. A pitch bend's `value` is
    0..16383 with 8192 at rest, and its `number` is 0.
    """

    kind: EventKind
    channel: int
    number: int
    value: int


@dataclass(frozen=True)
class Message:
    type: EventKind
    channel: int
    number: int | None  # None: not known yet (learn it at the hardware)
    first: int | None = None  # keys: the lowest and highest note
    last: int | None = None


@dataclass(frozen=True)
class Control:
    name: str
    label: str
    kind: str
    message: Message
    basis: str
    source: str
    verified: bool
    encoding: str = "absolute"
    shifted_of: str | None = None  # the control this one is while Shift is held (the data knob sends its own numbers)
    realign_sysex_id: int | None = None  # the knob's id in the ring message
    led_sysex_id: int | None = None  # the pad's id in the LED message


@dataclass(frozen=True)
class DisplaySpec:
    prefix: tuple[int, ...]
    full_screen_options: tuple[int, ...]
    parameter_options: tuple[int, ...]
    line_1_width: int
    line_2_width: int


@dataclass(frozen=True)
class SysexSpec:
    header: tuple[int, ...]
    end: int
    led_prefix: tuple[int, ...]
    display: DisplaySpec
    realign_prefix: tuple[int, ...]


@dataclass(frozen=True)
class Hit:
    """A control that moved: its name (a Shift-only variant as the control it stands for), the new value, the number
    of the message (a key's note), and whether the controller itself said Shift was held."""

    name: str
    value: int
    number: int
    shifted: bool = False


@dataclass(frozen=True)
class Profile:
    device: str
    port_match: tuple[str, ...]
    port_prefer: tuple[str, ...]
    sysex: SysexSpec
    controls: tuple[Control, ...]
    _index: dict[tuple[str, int, int], Control] = field(default_factory=dict, repr=False, compare=False)
    _keys: list[Control] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        for c in self.controls:
            m = c.message
            if m.type == "pitchbend":
                self._index.setdefault((m.type, m.channel, 0), c)
            elif m.first is not None and m.last is not None:
                self._keys.append(c)
            elif m.number is not None:  # a control with no number yet cannot be matched
                self._index.setdefault((m.type, m.channel, m.number), c)

    def by_name(self, name: str) -> Control:
        for c in self.controls:
            if c.name == name:
                return c
        raise KeyError(f"the profile has no control {name!r}")

    def match(self, event: Event) -> Hit | None:
        """The control an event is, or None for a message the profile does not know."""
        control = self._index.get((event.kind, event.channel, event.number if event.kind != "pitchbend" else 0))
        if control is None and event.kind == "note":
            control = next(
                (
                    k
                    for k in self._keys
                    if k.message.channel == event.channel
                    and k.message.first is not None
                    and k.message.last is not None
                    and k.message.first <= event.number <= k.message.last
                ),
                None,
            )
        if control is None:
            return None
        if control.shifted_of:
            return Hit(control.shifted_of, event.value, event.number, shifted=True)
        return Hit(control.name, event.value, event.number)

    def key(self, event: Event) -> Hit | None:
        """A note on the keys' channel as a key, whatever its number: the octave buttons move the keys beyond the
        range the profile names. None for anything else (the pads' notes are on a channel of their own)."""
        if event.kind != "note" or self._index.get((event.kind, event.channel, event.number)) is not None:
            return None
        keys = next((k for k in self._keys if k.message.channel == event.channel), None)
        return None if keys is None else Hit(keys.name, event.value, event.number)

    def unlearned(self) -> list[str]:
        """The controls with no message yet: they are ignored until a profile gives them one."""
        return [c.name for c in self.controls if not self._matchable(c)]

    @staticmethod
    def _matchable(c: Control) -> bool:
        m = c.message
        return m.type == "pitchbend" or m.number is not None or m.first is not None

    def with_message(self, name: str, message: Message) -> Profile:
        """The profile with one control's message replaced (what `learn` proposes)."""
        control = replace(self.by_name(name), message=message, verified=False)
        return Profile(
            self.device,
            self.port_match,
            self.port_prefer,
            self.sysex,
            tuple(control if c.name == name else c for c in self.controls),
        )


# ---- reading the file ------------------------------------------------------------------------------------------------


def _need(data: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ProfileError(f"{where} needs {key!r}")
    return data[key]


def _bytes(value: Any, where: str) -> tuple[int, ...]:
    if not (
        isinstance(value, list) and all(isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 255 for b in value)
    ):
        raise ProfileError(f"{where} must be a list of bytes (0 to 255)")
    return tuple(value)


def _message(data: Any, where: str) -> Message:
    if not isinstance(data, dict):
        raise ProfileError(f"{where}: 'message' must be an object")
    kind = _need(data, "type", f"{where} message")
    if kind not in KINDS:
        raise ProfileError(f"{where}: the message type is one of {', '.join(KINDS)}, not {kind!r}")
    channel = _need(data, "channel", f"{where} message")
    if not (isinstance(channel, int) and 1 <= channel <= 16):
        raise ProfileError(f"{where}: the channel is a whole number from 1 to 16")
    number = _need(data, "number", f"{where} message")
    if number is not None and not (isinstance(number, int) and 0 <= number <= 127):
        raise ProfileError(f"{where}: the number is 0 to 127, or null when it is not known yet")
    return Message(kind, channel, number, data.get("first"), data.get("last"))


def _control(data: Any, index: int) -> Control:
    if not isinstance(data, dict):
        raise ProfileError(f"control {index} must be an object")
    name = _need(data, "name", f"control {index}")
    where = f"control {name!r}"
    return Control(
        name=str(name),
        label=str(_need(data, "label", where)),
        kind=str(_need(data, "kind", where)),
        message=_message(_need(data, "message", where), where),
        basis=str(_need(data, "basis", where)),
        source=str(_need(data, "source", where)),
        verified=bool(_need(data, "verified", where)),
        encoding=str(data.get("encoding", "absolute")),
        shifted_of=data.get("shifted_of"),
        realign_sysex_id=data.get("realign_sysex_id"),
        led_sysex_id=data.get("led_sysex_id"),
    )


def parse_profile(data: Any) -> Profile:
    """A Profile from the JSON file's content; ProfileError says what is wrong."""
    if not isinstance(data, dict):
        raise ProfileError("the profile must be a JSON object")
    sysex = _need(data, "sysex", "the profile")
    display = _need(sysex, "display", "sysex")
    names = [c.get("name") if isinstance(c, dict) else None for c in _need(data, "controls", "the profile")]
    if len(set(names)) != len(names):
        raise ProfileError("two controls have the same name; each control's name is its own")
    ports = _need(data, "ports", "the profile")
    controls = tuple(_control(c, i) for i, c in enumerate(data["controls"]))
    for c in controls:
        if c.shifted_of and c.shifted_of not in names:
            raise ProfileError(f"control {c.name!r} is the Shift variant of {c.shifted_of!r}, which the profile lacks")
    return Profile(
        device=str(_need(data, "device", "the profile")),
        port_match=tuple(_need(ports, "match", "ports")),
        port_prefer=tuple(ports.get("prefer", [])),
        sysex=SysexSpec(
            header=_bytes(_need(sysex, "header", "sysex"), "sysex header"),
            end=int(_need(sysex, "end", "sysex")),
            led_prefix=_bytes(_need(_need(sysex, "led", "sysex"), "prefix", "sysex led"), "sysex led prefix"),
            display=DisplaySpec(
                prefix=_bytes(_need(display, "prefix", "sysex display"), "display prefix"),
                full_screen_options=_bytes(_need(display, "full_screen_options", "sysex display"), "display options"),
                parameter_options=_bytes(_need(display, "parameter_options", "sysex display"), "display options"),
                line_1_width=int(_need(display, "line_1_width", "sysex display")),
                line_2_width=int(_need(display, "line_2_width", "sysex display")),
            ),
            realign_prefix=_bytes(
                _need(_need(sysex, "realign", "sysex"), "prefix", "sysex realign"), "sysex realign prefix"
            ),
        ),
        controls=controls,
    )


def profile_path() -> Path:
    """ZPKT_MINILAB_PROFILE, or lib/contracts/minilab3-profile.json of this checkout."""
    env = os.environ.get("ZPKT_MINILAB_PROFILE")
    return Path(env).expanduser() if env else Path(__file__).resolve().parents[4] / "lib" / "contracts" / PROFILE_FILE


def load_profile(path: Path | None = None) -> Profile:
    """Read and parse the profile file."""
    path = path or profile_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise ProfileError(f"there is no MiniLab profile at {path}; set ZPKT_MINILAB_PROFILE to one") from None
    except ValueError as exc:
        raise ProfileError(f"the MiniLab profile {path} is not valid JSON ({exc})") from None
    return parse_profile(data)
