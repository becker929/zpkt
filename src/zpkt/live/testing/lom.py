"""A fake Live Object Model: the parts of Live's Python API that zpkt's code strings use, offline.

FakeLive (zpkt.live.testing.fakelive) runs the Remote Script's own code over a Song built here. The objects keep the
rules of Live that zpkt depends on: `str(parameter)` is what Live shows (zpkt.live.testing.display); every listenable
property has add_/remove_/_has_listener, fired when its value changes; a write from inside a notification raises
as Live does; collections come back as snapshots (tuples, like Live's vectors, so a `tracks` alias goes stale);
each LOM call's writes are one undo step. Where Live's exact behaviour is not known, a comment says GUESS.
"""

from __future__ import annotations

import functools
import math
import re
import threading
import traceback
import types
from collections.abc import Callable, Iterable, Sequence
from typing import Any, ClassVar, cast

from zpkt.live.testing import display

NOTIFICATION_REFUSED = "Changes cannot be triggered by notifications. You will need to defer your response."
SCENES = 8  # session slots per track; zpkt works in the arrangement, so they stay empty
SURFACE_SLOTS = 7  # Live's preferences have seven control surface slots; empty ones read as None
_MISSING = object()
_LISTENER = re.compile(r"(add|remove)_(\w+)_listener|(\w+)_has_listener")

# Live runs LOM code, listeners and MIDI callbacks on its one main thread. Every fake Live in this process shares
# this lock for the same reason; hold it to change a fake set while a FakeLive is serving.
MAIN_THREAD = threading.RLock()


class DeviceType:
    """Live.Device.DeviceType."""

    undefined, instrument, audio_effect, midi_effect = 0, 1, 2, 4


# --------------------------------------------------------------------------- bookkeeping


class CallTrace:
    """What one LOM call did: its undo step, and the values it read back after writing them (ableton-guide rule 1)."""

    def __init__(self) -> None:
        self.written: set[tuple[int, str]] = set()
        self.readbacks: list[str] = []
        self.undo: list[Callable[[], None]] = []


class Events:
    """One set's notifications and history, which Live keeps on its main thread."""

    def __init__(self) -> None:
        self.notifying = 0
        self.call: CallTrace | None = None
        self.undo_steps: list[list[Callable[[], None]]] = []
        self.listener_errors: list[str] = []
        self.restoring = False

    def begin_call(self) -> CallTrace:
        self.call = CallTrace()
        return self.call

    def end_call(self) -> None:
        if self.call is not None and self.call.undo:
            self.undo_steps.append(self.call.undo)
        self.call = None

    def check_write(self) -> None:
        if self.notifying:
            raise RuntimeError(NOTIFICATION_REFUSED)

    def wrote(self, obj: LiveObject, key: str, undo: Callable[[], None], *, by_live: bool = False) -> None:
        """Note a write for undo; `by_live` marks a change Live made itself (it is not the code reading back)."""
        if self.call is None or self.restoring:
            return
        self.call.undo.append(undo)
        if not by_live:
            self.call.written.add((id(obj), key))

    def read(self, obj: LiveObject, key: str) -> None:
        call = self.call
        if call is not None and not self.notifying and (id(obj), key) in call.written:
            call.readbacks.append(f"{obj._label()}.{key}")

    def notify(self, callbacks: Iterable[Callable[[], Any]]) -> None:
        """Run listeners. An error in one goes to Live's log, not to the code that made the change (GUESS)."""
        self.notifying += 1
        try:
            for fn in callbacks:
                try:
                    fn()
                except Exception:
                    self.listener_errors.append(traceback.format_exc())
        finally:
            self.notifying -= 1

    def undo(self) -> bool:
        if not self.undo_steps:
            return False
        step = self.undo_steps.pop()
        self.restoring = True
        try:
            for fn in reversed(step):
                fn()
        finally:
            self.restoring = False
        return True


class Prop:
    """A LOM property. `listen` gives it add_/remove_/_has_listener; `check` converts or refuses a written value."""

    def __init__(
        self,
        default: Any = None,
        *,
        writable: bool = True,
        listen: bool = True,
        check: Callable[[Any, Any], Any] | None = None,
    ) -> None:
        self.default, self.writable, self.listen, self.check = default, writable, listen, check
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        return obj._get(self.name, self.default)

    def __set__(self, obj: Any, value: Any) -> None:
        if not self.writable:
            raise AttributeError(f"can't set attribute '{self.name}'")
        obj._set(self.name, self.check(obj, value) if self.check else value)


def _number(obj: Any, value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"expected a number, got {type(value).__name__} {value!r}")


def _flag(obj: Any, value: Any) -> bool:
    if isinstance(value, (bool, int, float)):
        return bool(value)
    raise TypeError(f"expected a bool, got {type(value).__name__} {value!r}")


def _text(obj: Any, value: Any) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"expected a str, got {type(value).__name__} {value!r}")


def _beats(obj: Any, value: Any) -> float:
    beats = _number(obj, value)
    if beats < 0:
        raise RuntimeError("Invalid value")  # GUESS: Live's text for a negative time
    return beats


class LiveObject:
    """Base of the fake LOM objects: properties with listeners, a parent, and Live's errors for unknown names."""

    _listenable: ClassVar[frozenset[str]] = frozenset()
    _extra_listeners: ClassVar[tuple[str, ...]] = ()  # listenable names that are not Props (collections, computed)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        names: set[str] = set()
        for klass in cls.__mro__:
            names.update(getattr(klass, "_extra_listeners", ()))
            names.update(k for k, v in vars(klass).items() if isinstance(v, Prop) and v.listen)
        cls._listenable = frozenset(names)

    def __init__(self, parent: LiveObject | None = None) -> None:
        self._parent = parent
        self._values: dict[str, Any] = {}
        self._listeners: dict[str, list[Callable[[], Any]]] = {}
        self._own_events: Events | None = None

    @property
    def canonical_parent(self) -> LiveObject | None:
        return self._parent

    def _label(self) -> str:
        name = self._values.get("name")
        return f"{type(self).__name__} {name!r}" if name is not None else type(self).__name__

    def _events(self) -> Events:
        node = self
        while node._parent is not None:
            node = node._parent
        if node._own_events is None:
            node._own_events = Events()
        return node._own_events

    def _get(self, key: str, default: Any = None) -> Any:
        self._events().read(self, key)
        return self._values.get(key, default)

    def _set(self, key: str, value: Any, *, by_live: bool = False) -> None:
        events = self._events()
        events.check_write()
        old = self._values.get(key, _MISSING)
        self._values[key] = value
        events.wrote(self, key, functools.partial(self._put_back, key, old), by_live=by_live)
        if old is _MISSING or old != value:
            self._changed(key)

    def _put_back(self, key: str, old: Any) -> None:
        if old is _MISSING:
            self._values.pop(key, None)
        else:
            self._values[key] = old
        self._changed(key)

    def _changed(self, key: str) -> None:
        callbacks = self._listeners.get(key)
        if callbacks:
            self._events().notify(list(callbacks))

    def _structure(self, key: str, undo: Callable[[], None]) -> None:
        """A collection changed (a track added, a device deleted): note its undo and tell its listeners."""
        events = self._events()
        events.wrote(self, key, undo, by_live=True)
        self._changed(key)

    def _listener(self, op: str, key: str, fn: Callable[[], Any]) -> Any:
        callbacks = self._listeners.setdefault(key, [])
        if op == "has":
            return fn in callbacks
        if op == "add":
            if fn in callbacks:
                raise RuntimeError("Listener already connected")  # GUESS: Live's text
            callbacks.append(fn)
        elif fn not in callbacks:
            raise RuntimeError("Listener not connected")  # GUESS: Live's text
        else:
            callbacks.remove(fn)
        return None

    def __getattr__(self, name: str) -> Any:
        if not name.startswith("_"):
            m = _LISTENER.fullmatch(name)
            if m is not None and (m[2] or m[3]) in type(self)._listenable:
                return functools.partial(self._listener, m[1] or "has", m[2] or m[3])
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


# --------------------------------------------------------------------------- parameters and devices


class DeviceParameter(LiveObject):
    """A device's or the mixer's parameter. `str()` and `str_for_value` give the text Live shows."""

    name = Prop("", writable=False)
    original_name = Prop("", writable=False, listen=False)
    min = Prop(0.0, writable=False, listen=False)
    max = Prop(1.0, writable=False, listen=False)
    is_quantized = Prop(False, writable=False, listen=False)
    value_items = Prop((), writable=False, listen=False)
    default_value = Prop(0.0, writable=False, listen=False)
    is_enabled = Prop(True, writable=False, listen=False)
    automation_state = Prop(0, writable=False)  # 0 none, 1 playing, 2 overridden by a manual change
    state = Prop(0, writable=False)  # 0 enabled, 1 irrelevant, 2 disabled

    def __init__(
        self,
        name: str,
        *,
        min: float = 0.0,
        max: float = 1.0,
        value: float | None = None,
        default: float | None = None,
        items: Sequence[str] = (),
        show: display.Show | None = None,
        quantized: bool | None = None,
        enabled: bool = True,
        automated: int = 0,
        parent: LiveObject | None = None,
    ) -> None:
        super().__init__(parent)
        if items:
            min, max = 0.0, float(len(items) - 1)
        default = min if default is None else float(default)
        self._show = show or (display.choice(items) if items else display.plain)
        self._also: Callable[[], None] | None = None  # a linked property's listeners (a track's activator: mute)
        self._values.update(
            name=name,
            original_name=name,
            min=float(min),
            max=float(max),
            default_value=default,
            is_quantized=bool(items) if quantized is None else quantized,
            value_items=tuple(items),
            is_enabled=enabled,
            state=0 if enabled else 2,
            automation_state=automated,
            value=default if value is None else float(value),
        )

    def _label(self) -> str:
        owner = self._parent._label() if self._parent is not None else ""
        return f"{owner}/{self._values['name']}" if owner else f"DeviceParameter {self._values['name']!r}"

    def _check(self, value: Any) -> float:
        v = _number(self, value)
        if not self._values["is_enabled"]:
            raise RuntimeError("Parameter is not enabled")  # GUESS: Live's text
        lo, hi = self._values["min"], self._values["max"]
        slack = 1e-7 * max(1.0, hi - lo)  # float noise from a clamp in the caller is let through
        if not lo - slack <= v <= hi + slack:
            raise RuntimeError("Invalid value")  # zpkt clamps to avoid this (agent.PRELUDE set_clamped)
        v = max(lo, min(hi, v))
        return float(round(v)) if self._values["is_quantized"] else v

    value = Prop(0.0, check=lambda p, v: p._check(v))

    def _set(self, key: str, value: Any, *, by_live: bool = False) -> None:
        super()._set(key, value, by_live=by_live)
        if key == "value" and self._values["automation_state"] == 1:
            self._values["automation_state"] = 2  # a manual write overrides the automation (GUESS)
            self._changed("automation_state")

    def _changed(self, key: str) -> None:
        super()._changed(key)
        if key == "value" and self._also is not None:
            self._also()

    def str_for_value(self, value: float) -> str:
        return self._show(float(value))

    def __str__(self) -> str:
        return self.str_for_value(self._get("value"))

    def re_enable_automation(self) -> None:
        if self._values["automation_state"] == 2:
            self._set("automation_state", 1, by_live=True)

    def begin_gesture(self) -> None:
        pass

    def end_gesture(self) -> None:
        pass


class DeviceView(LiveObject):
    is_collapsed = Prop(False, check=_flag)


class Device(LiveObject):
    """A device on a track or chain; parameters[0] is "Device On", as in Live."""

    _extra_listeners: ClassVar[tuple[str, ...]] = ("parameters",)
    name = Prop("", check=_text)
    is_active = Prop(True, writable=False)

    def __init__(
        self,
        name: str,
        class_name: str,
        parameters: Iterable[DeviceParameter],
        *,
        class_display_name: str | None = None,
        kind: int = DeviceType.audio_effect,
        parent: LiveObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._values["name"] = name
        self._class_name, self._class_display_name, self._type = class_name, class_display_name or name, kind
        self._parameters = list(parameters)
        for p in self._parameters:
            p._parent = self
        self._view = DeviceView(self)

    class_name = property(lambda self: self._class_name)
    class_display_name = property(lambda self: self._class_display_name)
    type = property(lambda self: self._type)
    parameters = property(lambda self: tuple(self._parameters))
    view = property(lambda self: self._view)
    can_have_chains = property(lambda self: False)
    can_have_drum_pads = property(lambda self: False)


class ChainMixerDevice(LiveObject):
    def __init__(self, parent: LiveObject) -> None:
        super().__init__(parent)
        self._volume = DeviceParameter("Chain Volume", value=0.85, default=0.85, show=display.volume, parent=self)
        self._panning = DeviceParameter("Chain Panning", min=-1.0, max=1.0, value=0.0, show=display.pan, parent=self)
        self._activator = DeviceParameter("Chain Activator", items=("Off", "On"), value=1.0, parent=self)

    volume = property(lambda self: self._volume)
    panning = property(lambda self: self._panning)
    chain_activator = property(lambda self: self._activator)
    sends = property(lambda self: ())


class Chain(LiveObject):
    """A rack's chain: devices and its own small mixer."""

    _extra_listeners: ClassVar[tuple[str, ...]] = ("devices",)
    name = Prop("", check=_text)
    mute = Prop(False, check=_flag)
    solo = Prop(False, check=_flag)
    color = Prop(0, check=lambda o, v: int(_number(o, v)))

    def __init__(self, name: str, devices: Iterable[Device] = (), parent: LiveObject | None = None) -> None:
        super().__init__(parent)
        self._values["name"] = name
        self._devices = list(devices)
        for d in self._devices:
            d._parent = self
        self._mixer = ChainMixerDevice(self)
        self._pad_note: int | None = None  # in a Drum Rack: the note of the pad this chain is on

    devices = property(lambda self: tuple(self._devices))
    mixer_device = property(lambda self: self._mixer)


class DrumPad(LiveObject):
    """One of a Drum Rack's 128 pads, one per MIDI note (ableton-guide 6). A pad holds something when it has
    chains; the fake keeps the note on the chain and the pad looks its chains up."""

    mute = Prop(False, check=_flag)
    solo = Prop(False, check=_flag)

    def __init__(self, rack: RackDevice, note: int) -> None:
        super().__init__(rack)
        self._note = note

    note = property(lambda self: self._note)

    @property
    def chains(self) -> tuple[Chain, ...]:
        return tuple(c for c in cast(RackDevice, self._parent)._chains if c._pad_note == self._note)

    @property
    def name(self) -> str:
        """GUESS: a filled pad is named after its first chain, an empty one after its note ("C1")."""
        chains = self.chains
        if chains:
            return str(chains[0]._values["name"])
        return f"{('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')[self._note % 12]}{self._note // 12 - 2}"

    def _label(self) -> str:
        return f"DrumPad {self._note}"


class RackDevice(Device):
    """A rack (Audio Effect, Instrument or Drum Rack): chains of devices."""

    _extra_listeners: ClassVar[tuple[str, ...]] = ("chains", "return_chains")

    def __init__(
        self,
        name: str,
        class_name: str,
        parameters: Iterable[DeviceParameter],
        chains: Iterable[Chain] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(name, class_name, parameters, **kwargs)
        self._chains = list(chains)
        for c in self._chains:
            c._parent = self
        self._pads: tuple[DrumPad, ...] = ()

    chains = property(lambda self: tuple(self._chains))
    return_chains = property(lambda self: ())

    @property
    def drum_pads(self) -> tuple[DrumPad, ...]:
        """A Drum Rack's 128 pads, indexed by MIDI note; no pads on another rack."""
        if not self.can_have_drum_pads:
            return ()
        if not self._pads:
            self._pads = tuple(DrumPad(self, note) for note in range(128))
        return self._pads

    can_have_chains = property(lambda self: True)
    can_have_drum_pads = property(lambda self: self._class_name == "DrumGroupDevice")


class Sample(LiveObject):
    """The sample a Simpler plays."""

    warping = Prop(False, check=_flag)
    slicing_style = Prop(0, check=lambda o, v: int(_number(o, v)))
    gain = Prop(1.0, check=_number)

    def __init__(self, file_path: str, parent: LiveObject | None = None) -> None:
        super().__init__(parent)
        self._values["file_path"] = file_path
        self._slices: list[int] = []

    file_path = property(lambda self: self._values["file_path"])
    slices = property(lambda self: tuple(self._slices))

    def insert_slice(self, frame: int) -> None:
        self._slices = sorted({*self._slices, int(frame)})

    def clear_slices(self) -> None:
        self._slices = []


class SimplerDevice(Device):
    playback_mode = Prop(0, check=lambda o, v: int(_number(o, v)))

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sample: Sample | None = None

    sample = property(lambda self: self._sample)

    def replace_sample(self, file_path: str) -> None:
        self._sample = Sample(str(file_path), parent=self)


# --------------------------------------------------------------------------- tracks


class RoutingType:
    """One routing choice (Live.Track.RoutingType): what `display_name` shows, and the track it points at. A choice
    named after a track follows the track's name."""

    def __init__(self, display_name: str, attached_object: Any = None, category: int = 0) -> None:
        self._name, self.attached_object, self.category = display_name, attached_object, category
        self._follows = isinstance(attached_object, Track) and display_name == attached_object.name

    @property
    def display_name(self) -> str:
        return self.attached_object.name if self._follows else self._name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RoutingType) and (self.display_name, self.attached_object) == (
            other.display_name,
            other.attached_object,
        )

    def __hash__(self) -> int:
        return hash(self._name)

    def __repr__(self) -> str:
        return f"RoutingType({self.display_name!r})"


class MixerDevice(LiveObject):
    """A track's mixer. Main has no sends and no activator, but a cue volume and the crossfader."""

    _extra_listeners: ClassVar[tuple[str, ...]] = ("sends",)

    def __init__(self, track: Track, sends: int) -> None:
        super().__init__(track)
        self._volume = DeviceParameter("Track Volume", value=0.85, default=0.85, show=display.volume, parent=self)
        self._panning = DeviceParameter("Track Panning", min=-1.0, max=1.0, value=0.0, show=display.pan, parent=self)
        self._sends = [self._new_send(k) for k in range(sends)]
        self._activator: DeviceParameter | None = None
        if track._kind != "main":
            self._activator = DeviceParameter("Track Activator", items=("Off", "On"), value=1.0, parent=self)
            self._activator._also = functools.partial(track._changed, "mute")
        self._cue = DeviceParameter("Cue Volume", value=0.85, show=display.volume, parent=self)
        self._crossfader = DeviceParameter("Crossfade", min=-1.0, max=1.0, value=0.0, parent=self)

    def _new_send(self, k: int) -> DeviceParameter:
        # GUESS: Live's name for a send parameter; zpkt reads sends by position
        return DeviceParameter(f"{chr(65 + k)}-Send", value=0.0, show=display.send, parent=self)

    def _label(self) -> str:
        return self._parent._label() if self._parent is not None else "MixerDevice"

    def activator(self) -> DeviceParameter:
        if self._activator is None:
            raise RuntimeError("Main has no track activator")
        return self._activator

    volume = property(lambda self: self._volume)
    panning = property(lambda self: self._panning)
    sends = property(lambda self: tuple(self._sends))

    def __getattr__(self, name: str) -> Any:
        main = isinstance(self._parent, Track) and self._parent._kind == "main"
        if name == "track_activator" and not main:
            return self._activator
        if name in ("cue_volume", "crossfader") and main:
            return self._cue if name == "cue_volume" else self._crossfader
        return super().__getattr__(name)


class TrackView(LiveObject):
    selected_device = Prop(None)
    is_collapsed = Prop(False, check=_flag)
    device_insert_mode = Prop(0, check=lambda o, v: int(_number(o, v)))

    def select_instrument(self) -> bool:
        track = cast(Track, self._parent)
        found = next((d for d in track._devices if d.type == DeviceType.instrument), None)
        if found is not None:
            self.selected_device = found
        return found is not None


class Clip(LiveObject):
    """An arrangement clip (or a session clip in a slot)."""

    _extra_listeners: ClassVar[tuple[str, ...]] = ("notes", "warp_markers")
    name = Prop("", check=_text)
    color = Prop(0, check=lambda o, v: int(_number(o, v)))
    muted = Prop(False, check=_flag)
    looping = Prop(True, check=_flag)
    loop_start = Prop(0.0, check=_number)
    loop_end = Prop(4.0, check=_number)
    start_marker = Prop(0.0, check=_number)
    end_marker = Prop(4.0, check=_number)
    warping = Prop(True, check=_flag)
    warp_mode = Prop(0, check=lambda o, v: int(_number(o, v)))
    gain = Prop(0.4, check=_number)  # GUESS: 0 dB on Live's clip gain scale
    pitch_coarse = Prop(0, check=lambda o, v: int(_number(o, v)))
    pitch_fine = Prop(0.0, check=_number)

    def __init__(
        self,
        start: float,
        length: float,
        *,
        audio: bool = False,
        file_path: str = "",
        name: str = "",
        arrangement: bool = True,
        parent: LiveObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._start, self._length, self._audio, self._arrangement = float(start), float(length), audio, arrangement
        self._values.update(
            name=name, loop_end=float(length), end_marker=float(length), looping=not audio, file_path=file_path
        )
        self._notes: list[MidiNote] = []
        self._next_id = 1
        self._warp_markers: list[WarpMarker] = []

    start_time = property(lambda self: self._start)
    end_time = property(lambda self: self._start + self._length)
    length = property(lambda self: self._length)
    position = property(lambda self: self._start)
    is_audio_clip = property(lambda self: self._audio)
    is_midi_clip = property(lambda self: not self._audio)
    is_arrangement_clip = property(lambda self: self._arrangement)
    file_path = property(lambda self: self._values["file_path"])
    warp_markers = property(lambda self: tuple(self._warp_markers))

    @property
    def gain_display_string(self) -> str:
        """The clip gain as Live shows it. GUESS: dB against the 0.4 that Live shows as 0 dB; only the order matters."""
        g = float(self._values.get("gain", 0.4))
        return "-inf dB" if g <= 0 else f"{20 * math.log10(g / 0.4):.2f} dB"

    def _midi_only(self) -> None:
        if self._audio:
            raise RuntimeError("Not a MIDI clip")  # GUESS: Live's text

    def add_new_notes(self, specs: Iterable[MidiNoteSpecification]) -> tuple[int, ...]:
        self._midi_only()
        ids = []
        for s in specs:
            note = MidiNote(
                self._next_id,
                s.pitch,
                s.start_time,
                s.duration,
                s.velocity,
                s.mute,
                s.probability,
                s.velocity_deviation,
                s.release_velocity,
            )
            self._next_id += 1
            self._notes.append(note)
            ids.append(note.note_id)
        self._structure("notes", functools.partial(self._drop_notes, set(ids)))
        return tuple(ids)

    def _drop_notes(self, ids: set[int]) -> None:
        self._notes = [n for n in self._notes if n.note_id not in ids]

    def get_notes_extended(
        self, from_pitch: int, pitch_span: int, from_time: float, time_span: float
    ) -> tuple[MidiNote, ...]:
        self._midi_only()
        return tuple(
            n.copy()
            for n in sorted(self._notes, key=lambda n: (n.start_time, n.pitch))
            if from_pitch <= n.pitch < from_pitch + pitch_span and from_time <= n.start_time < from_time + time_span
        )

    def get_all_notes_extended(self) -> tuple[MidiNote, ...]:
        return self.get_notes_extended(0, 128, -1e9, 2e9)

    def remove_notes_extended(self, from_pitch: int, pitch_span: int, from_time: float, time_span: float) -> None:
        gone = {n.note_id for n in self.get_notes_extended(from_pitch, pitch_span, from_time, time_span)}
        kept = list(self._notes)
        self._drop_notes(gone)
        self._structure("notes", functools.partial(setattr, self, "_notes", kept))

    def apply_note_modifications(self, notes: Iterable[MidiNote]) -> None:
        self._midi_only()
        by_id = {n.note_id: n for n in notes}
        self._notes = [by_id[n.note_id].copy() if n.note_id in by_id else n for n in self._notes]

    def add_warp_marker(self, marker: WarpMarker) -> None:
        self._warp_markers = sorted([*self._warp_markers, marker], key=lambda m: m.beat_time)

    def remove_warp_marker(self, beat_time: float) -> None:
        self._warp_markers = [m for m in self._warp_markers if abs(m.beat_time - beat_time) > 1e-9]

    def move_warp_marker(self, beat_time: float, distance: float) -> None:
        self._warp_markers = [
            WarpMarker(m.sample_time, m.beat_time + distance) if abs(m.beat_time - beat_time) <= 1e-9 else m
            for m in self._warp_markers
        ]


class MidiNoteSpecification:
    """Live.Clip.MidiNoteSpecification: a note to add."""

    def __init__(
        self,
        pitch: int,
        start_time: float,
        duration: float,
        velocity: float = 100.0,
        mute: bool = False,
        probability: float = 1.0,
        velocity_deviation: float = 0.0,
        release_velocity: float = 64.0,
    ) -> None:
        self.pitch, self.start_time, self.duration, self.velocity = (
            int(pitch),
            float(start_time),
            float(duration),
            velocity,
        )
        self.mute, self.probability = bool(mute), probability
        self.velocity_deviation, self.release_velocity = velocity_deviation, release_velocity


class MidiNote(MidiNoteSpecification):
    """Live.Clip.MidiNote: a note in a clip, with its id."""

    def __init__(self, note_id: int, *args: Any) -> None:
        super().__init__(*args)
        self.note_id = note_id

    def copy(self) -> MidiNote:
        return MidiNote(
            self.note_id,
            self.pitch,
            self.start_time,
            self.duration,
            self.velocity,
            self.mute,
            self.probability,
            self.velocity_deviation,
            self.release_velocity,
        )


class WarpMarker:
    """Live.Clip.WarpMarker."""

    def __init__(self, sample_time: float, beat_time: float) -> None:
        self.sample_time, self.beat_time = float(sample_time), float(beat_time)


class ClipSlot(LiveObject):
    """A session slot. zpkt works in the arrangement, so these stay empty."""

    def __init__(self, parent: LiveObject) -> None:
        super().__init__(parent)

    has_clip = property(lambda self: False)
    clip = property(lambda self: None)
    is_playing = property(lambda self: False)
    is_triggered = property(lambda self: False)

    def fire(self) -> None:
        pass

    def stop(self) -> None:
        pass


class Track(LiveObject):
    """A MIDI, audio or group track, a return track, or Main (kind "midi", "audio", "group", "return", "main")."""

    _extra_listeners: ClassVar[tuple[str, ...]] = (
        "mute",
        "devices",
        "arrangement_clips",
        "clip_slots",
        "input_routing_type",
        "output_routing_type",
        "available_input_routing_types",
        "available_output_routing_types",
    )
    name = Prop("", check=_text)
    color = Prop(0, check=lambda o, v: int(_number(o, v)))
    color_index = Prop(0, check=lambda o, v: int(_number(o, v)))
    solo = Prop(False, check=lambda t, v: t._may("solo") and _flag(t, v))
    arm = Prop(False, check=lambda t, v: t._may("arm") and _flag(t, v))
    fold_state = Prop(0, check=lambda t, v: t._may("fold_state") and int(_flag(t, v)))
    current_monitoring_state = Prop(1, check=lambda t, v: t._may("current_monitoring_state") and t._monitoring(v))
    output_meter_left = Prop(0.0, writable=False)
    output_meter_right = Prop(0.0, writable=False)
    output_meter_level = Prop(0.0, writable=False)

    def __init__(self, song: Song, kind: str, name: str, sends: int = 0) -> None:
        super().__init__(song)
        self._kind = kind
        self._values["name"] = name
        self._devices: list[Device] = []
        self._clips: list[Clip] = []
        self._slots = [ClipSlot(self) for _ in range(SCENES)] if kind in ("midi", "audio", "group") else []
        self._group: Track | None = None
        self._output = RoutingType("Main") if kind != "main" else RoutingType("Ext. Out")
        self._input = RoutingType({"midi": "All Ins", "audio": "Ext. In"}.get(kind, "No Input"))
        self._auto_armed = False
        self._view = TrackView(self)
        self._mixer = MixerDevice(self, sends if kind != "main" else 0)

    def _label(self) -> str:
        return f"Track {self._values['name']!r}"

    def _song(self) -> Song:
        return cast(Song, self._parent)

    def _may(self, what: str) -> bool:
        """Refuse what this kind of track does not have. GUESS: Live's exact text."""
        refused = {
            "main": ("solo", "arm", "fold_state", "current_monitoring_state", "mute"),
            "return": ("arm", "fold_state", "current_monitoring_state"),
            "group": ("arm", "current_monitoring_state"),
            "midi": ("fold_state",),
            "audio": ("fold_state",),
        }[self._kind]
        if what in refused:
            raise RuntimeError(f"{self._label()} has no {what}")
        return True

    def _monitoring(self, value: Any) -> int:
        v = int(_number(self, value))
        if v not in (0, 1, 2):
            raise RuntimeError("Invalid value")
        return v

    # mute is the activator's value turned around, as in Live: one changes the other
    @property
    def mute(self) -> bool:
        self._may("mute")
        return bool(self._mixer.activator()._get("value") < 0.5)

    @mute.setter
    def mute(self, value: Any) -> None:
        self._may("mute")
        self._mixer.activator().value = 0.0 if _flag(self, value) else 1.0

    mixer_device = property(lambda self: self._mixer)
    devices = property(lambda self: tuple(self._devices))
    arrangement_clips = property(lambda self: tuple(sorted(self._clips, key=lambda c: c.start_time)))
    clip_slots = property(lambda self: tuple(self._slots))
    view = property(lambda self: self._view)
    can_be_armed = property(lambda self: self._kind in ("midi", "audio"))
    has_midi_input = property(lambda self: self._kind == "midi")
    has_audio_input = property(lambda self: self._kind == "audio")
    has_midi_output = property(
        lambda self: self._kind == "midi" and not any(d.type == DeviceType.instrument for d in self._devices)
    )
    has_audio_output = property(
        lambda self: self._kind != "midi" or any(d.type == DeviceType.instrument for d in self._devices)
    )
    is_foldable = property(lambda self: self._kind == "group")
    is_grouped = property(lambda self: self._group is not None)
    group_track = property(lambda self: self._group)
    is_part_of_selection = property(lambda self: False)
    input_routing_type = property(lambda self: self._input, lambda self, v: self._route("input", v))
    output_routing_type = property(lambda self: self._output, lambda self, v: self._route("output", v))

    @property
    def is_visible(self) -> bool:
        group = self._group
        while group is not None:
            if group._values.get("fold_state"):
                return False
            group = group._group
        return True

    @property
    def available_output_routing_types(self) -> tuple[RoutingType, ...]:
        """GUESS: Main, every group and audio track but this one, Sends Only."""
        song = self._song()
        if self._kind == "main":
            return (RoutingType("Ext. Out"),)
        out = [RoutingType("Main")]
        if self._group is not None:
            out.append(RoutingType("Group", self._group))
        out += [RoutingType(t.name, t) for t in song._tracks if t is not self and t._kind in ("audio", "group")]
        return (*out, RoutingType("Sends Only"))

    @property
    def available_input_routing_types(self) -> tuple[RoutingType, ...]:
        """GUESS: the external input, Resampling, every other track, No Input."""
        if self._kind == "midi":
            return RoutingType("All Ins"), RoutingType("Computer Keyboard"), RoutingType("No Input")
        if self._kind != "audio":
            return ()
        song = self._song()
        others = [RoutingType(t.name, t) for t in song._tracks if t is not self]
        return (RoutingType("Ext. In"), RoutingType("Resampling"), *others, RoutingType("No Input"))

    def _route(self, which: str, value: Any) -> None:
        self._events().check_write()
        choices = self.available_input_routing_types if which == "input" else self.available_output_routing_types
        if value not in choices:
            raise RuntimeError(f"{value!r} is not an available {which} routing type")  # GUESS: Live's text
        attr = f"_{which}"
        old = getattr(self, attr)
        setattr(self, attr, value)
        self._structure(f"{which}_routing_type", functools.partial(setattr, self, attr, old))

    def _add_device(self, device: Device, index: int | None = None) -> Device:
        device._parent = self
        at = len(self._devices) if index is None or index < 0 or index > len(self._devices) else index
        self._devices.insert(at, device)
        self._structure("devices", functools.partial(self._devices.remove, device))
        return device

    def delete_device(self, index: int) -> None:
        self._events().check_write()
        device = self._devices.pop(index)
        self._structure("devices", functools.partial(self._devices.insert, index, device))

    def insert_device(self, device_name: str, target_index: int = -1) -> Device:
        """Live 12's insert_device: a built-in device by the name the browser shows."""
        from zpkt.live.testing import devices

        self._events().check_write()
        return self._add_device(devices.make(device_name), target_index)

    def create_midi_clip(self, start_time: float, length: float) -> Clip:
        self._events().check_write()
        if self._kind != "midi":
            raise RuntimeError("MIDI clips can only be created on MIDI tracks")  # GUESS: Live's text
        if length <= 0:
            raise RuntimeError("Invalid clip length")
        return self._add_clip(Clip(start_time, length, parent=self))

    def create_audio_clip(self, file_path: str, position: float) -> Clip:
        """GUESS: the clip is as long as the file at the song's tempo; Live reads the file's own tempo when warping."""
        self._events().check_write()
        if self._kind != "audio":
            raise RuntimeError("Audio clips can only be created on audio tracks")
        try:
            import soundfile

            seconds = soundfile.info(str(file_path)).duration
        except Exception as exc:
            raise RuntimeError(f"Invalid audio file: {file_path}") from exc
        beats = seconds * self._song()._values["tempo"] / 60.0
        return self._add_clip(Clip(position, beats, audio=True, file_path=str(file_path), parent=self))

    def _add_clip(self, clip: Clip) -> Clip:
        self._clips.append(clip)
        self._structure("arrangement_clips", functools.partial(self._clips.remove, clip))
        return clip

    def delete_clip(self, clip: Clip) -> None:
        self._events().check_write()
        if clip not in self._clips:
            raise RuntimeError("Clip is not on this track")
        self._clips.remove(clip)
        self._structure("arrangement_clips", functools.partial(self._clips.append, clip))

    def duplicate_clip_to_arrangement(self, clip: Clip, destination_time: float) -> Clip:
        self._events().check_write()
        copy = Clip(
            destination_time,
            clip.length,
            audio=clip.is_audio_clip,
            file_path=clip.file_path,
            name=clip._values["name"],
            parent=self,
        )
        copy._values.update(clip._values)  # GUESS: the whole clip, its markers, loop, colour and mute too
        copy._notes = [n.copy() for n in clip._notes]
        copy._next_id = clip._next_id
        return self._add_clip(copy)

    def stop_all_clips(self, quantized: bool = True) -> None:
        """Stopping session clips takes the track off the arrangement: Back to Arrangement lights (ableton-guide)."""
        self._song()._set("back_to_arranger", True, by_live=True)


class ReturnTrack(Track):
    """A return: Live shows its letter in its name ("A-Space"), and the letter follows its place."""

    def __init__(self, song: Song, name: str, sends: int) -> None:
        super().__init__(song, "return", name, sends)

    def _letter(self) -> str:
        returns = self._song()._returns
        return chr(65 + returns.index(self)) if self in returns else "?"

    @property
    def name(self) -> str:
        return f"{self._letter()}-{self._get('name', '')}"

    @name.setter
    def name(self, value: Any) -> None:
        text = _text(self, value)
        prefix = f"{self._letter()}-"
        self._set("name", text[2:] if text.startswith(prefix) else text)  # GUESS: Live keeps one letter

    def _label(self) -> str:
        return f"Track {self._letter()}-{self._values['name']!r}"


# --------------------------------------------------------------------------- the song


class SongView(LiveObject):
    selected_scene = Prop(None)
    selected_chain = Prop(None)
    selected_parameter = Prop(None)  # the parameter last clicked in Live; None when it is not a device's
    detail_clip = Prop(None)
    follow_song = Prop(False, check=_flag)

    def _select(self, track: Any) -> Any:
        song = cast(Song, self._parent)
        if track is not None and track not in song._all_tracks():
            raise RuntimeError("Track is not in this set")
        return track

    selected_track = Prop(None, check=lambda v, t: v._select(t))

    def _set(self, key: str, value: Any, *, by_live: bool = False) -> None:
        super()._set(key, value, by_live=by_live)
        if key == "selected_track" and not by_live:
            cast(Song, self._parent)._auto_arm(value)

    def select_device(self, device: Device, should_appoint: bool = True) -> None:
        owner = device._parent
        while owner is not None and not isinstance(owner, Track):
            owner = owner._parent
        if owner is None:
            raise RuntimeError("Device is not in this set")
        self.selected_track = owner
        owner.view.selected_device = device


class CuePoint(LiveObject):
    name = Prop("", check=_text)

    def __init__(self, time: float, name: str = "", parent: LiveObject | None = None) -> None:
        super().__init__(parent)
        self._time = float(time)
        self._values["name"] = name

    time = property(lambda self: self._time)

    def jump(self) -> None:
        cast(Song, self._parent).current_song_time = self._time


class Scene(LiveObject):
    name = Prop("", check=_text)

    def fire(self) -> None:
        pass


class Song(LiveObject):
    """The open set: tracks, returns, Main, the transport and the arrangement's loop."""

    _extra_listeners: ClassVar[tuple[str, ...]] = (
        "tracks",
        "return_tracks",
        "visible_tracks",
        "cue_points",
        "scenes",
        "can_undo",
    )
    tempo = Prop(120.0, check=lambda s, v: s._tempo(v))
    signature_numerator = Prop(4, check=lambda s, v: int(_number(s, v)))
    signature_denominator = Prop(4, check=lambda s, v: int(_number(s, v)))
    current_song_time = Prop(0.0, check=_beats)
    start_time = Prop(0.0, check=_beats)
    loop = Prop(False, check=_flag)
    loop_start = Prop(0.0, check=_beats)
    loop_length = Prop(16.0, check=_beats)
    record_mode = Prop(False, check=_flag)
    session_record = Prop(False, check=_flag)
    arrangement_overdub = Prop(False, check=_flag)
    overdub = Prop(False, check=_flag)
    back_to_arranger = Prop(False, check=_flag)
    metronome = Prop(False, check=_flag)
    is_playing = Prop(False, check=_flag)

    def __init__(self, tempo: float = 120.0) -> None:
        super().__init__(None)
        self._own_events = Events()
        self._values["tempo"] = float(tempo)
        self._tracks: list[Track] = []
        self._returns: list[ReturnTrack] = []
        self._main = Track(self, "main", "Main")
        self._view = SongView(self)
        self._scenes = [Scene(self) for _ in range(SCENES)]
        self._cue_points: list[CuePoint] = []
        self._data: dict[str, Any] = {}

    def _label(self) -> str:
        return "Song"

    def _tempo(self, value: Any) -> float:
        v = _number(self, value)
        if not 20.0 <= v <= 999.0:
            raise RuntimeError("Invalid value")
        return v

    def _all_tracks(self) -> list[Track]:
        return [*self._tracks, *self._returns, self._main]

    tracks = property(lambda self: tuple(self._tracks))
    return_tracks = property(lambda self: tuple(self._returns))
    master_track = property(lambda self: self._main)
    visible_tracks = property(lambda self: tuple(t for t in self._tracks if t.is_visible))
    scenes = property(lambda self: tuple(self._scenes))
    cue_points = property(lambda self: tuple(self._cue_points))
    view = property(lambda self: self._view)
    can_undo = property(lambda self: bool(self._own_events and self._own_events.undo_steps))
    can_redo = property(lambda self: False)

    @property
    def last_event_time(self) -> float:
        """The end of the last clip in the arrangement."""
        return max((c.end_time for t in self._tracks for c in t._clips), default=0.0)

    @property
    def song_length(self) -> float:
        return max(self.last_event_time, self._values.get("loop_start", 0.0) + self._values.get("loop_length", 16.0))

    # --- transport

    def start_playing(self) -> None:
        """Play from the start marker (song.start_time), not from the playhead."""
        self._events().check_write()
        self._set("current_song_time", self._values.get("start_time", 0.0), by_live=True)
        self._set("is_playing", True, by_live=True)

    def continue_playing(self) -> None:
        self._events().check_write()
        self._set("is_playing", True, by_live=True)

    def stop_playing(self) -> None:
        self._events().check_write()
        self._set("is_playing", False, by_live=True)  # GUESS: the playhead stays where it stopped

    def stop_all_clips(self, quantized: bool = True) -> None:
        for t in self._tracks:
            t.stop_all_clips()

    def trigger_session_record(self, record_length: float | None = None) -> None:
        self._set("session_record", True, by_live=True)
        if not self._values.get("is_playing"):
            self.start_playing()

    def _advance(self, beats: float) -> None:
        """Move the playhead as playback would (the loop wraps it); fires current_song_time listeners."""
        if not self._values.get("is_playing"):
            return
        now = self._values.get("current_song_time", 0.0)
        to = now + beats
        start, length = self._values.get("loop_start", 0.0), self._values.get("loop_length", 16.0)
        if self._values.get("loop") and length > 0 and now < start + length <= to:
            to = start + (to - start) % length
        self._set("current_song_time", to, by_live=True)

    # --- tracks

    def _new_track(self, kind: str, index: int) -> Track:
        self._events().check_write()
        if not -1 <= index <= len(self._tracks):
            raise RuntimeError("Invalid track index")
        at = len(self._tracks) if index == -1 else index
        label = {"midi": "MIDI", "audio": "Audio"}[kind]
        track = Track(self, kind, f"{at + 1}-{label}", len(self._returns))  # GUESS: the name Live gives it
        self._tracks.insert(at, track)
        self._structure("tracks", functools.partial(self._tracks.remove, track))
        return track

    def create_midi_track(self, index: int = -1) -> Track:
        return self._new_track("midi", index)

    def move_device(self, device: Device, target: Any, target_position: int) -> int:
        """Live's Song.move_device: put `device` in `target` (a track) before the device now at `target_position`,
        and return the index it ends at. GUESS: the position counts the chain as it is before the move, so the end
        is len(devices); a position past the end is the end."""
        self._events().check_write()
        source = device._parent
        if source is None or device not in source._devices or not hasattr(target, "_devices"):
            raise RuntimeError("the device cannot be moved there")  # GUESS: Live's text
        was = source._devices.index(device)
        position = max(0, min(len(target._devices), int(target_position)))
        if target is source and position > was:
            position -= 1
        source._devices.remove(device)
        target._devices.insert(position, device)
        device._parent = target

        def undo() -> None:
            target._devices.remove(device)
            source._devices.insert(was, device)
            device._parent = source

        source._structure("devices", undo)
        if target is not source:
            target._changed("devices")
        return position

    def create_audio_track(self, index: int = -1) -> Track:
        return self._new_track("audio", index)

    def delete_track(self, index: int) -> None:
        self._events().check_write()
        if len(self._tracks) <= 1:
            raise RuntimeError("Cannot delete the last track")  # GUESS: Live's text (ableton-guide: loop to 1)
        track = self._tracks.pop(index)
        if self._view._values.get("selected_track") is track:
            self._view._set("selected_track", self._tracks[min(index, len(self._tracks) - 1)], by_live=True)
        self._structure("tracks", functools.partial(self._tracks.insert, index, track))

    def create_return_track(self) -> ReturnTrack:
        self._events().check_write()
        track = ReturnTrack(self, "Return", len(self._returns))
        self._returns.append(track)
        self._each_mixer(lambda m: m._sends.append(m._new_send(len(m._sends))))  # the new return's own send too
        self._structure("return_tracks", functools.partial(self._drop_return, track))
        return track

    def _drop_return(self, track: ReturnTrack) -> None:
        k = self._returns.index(track)
        self._returns.pop(k)
        self._each_mixer(lambda m: m._sends.pop(k))

    def delete_return_track(self, index: int) -> None:
        self._events().check_write()
        track = self._returns[index]
        sends = {id(t): t._mixer._sends[index] for t in [*self._tracks, *self._returns]}
        self._drop_return(track)

        def put_back() -> None:
            self._returns.insert(index, track)
            for t in [*self._tracks, *self._returns]:
                if id(t) in sends and t is not track:
                    t._mixer._sends.insert(index, sends[id(t)])

        self._structure("return_tracks", put_back)

    def _each_mixer(self, fn: Callable[[MixerDevice], Any]) -> None:
        for t in [*self._tracks, *self._returns]:
            fn(t._mixer)

    def _auto_arm(self, track: Track | None) -> None:
        """Selecting a MIDI track arms it and lets go of the one armed that way before (agent.PRELUDE puts arms back)."""
        for t in self._tracks:
            if t._auto_armed and t is not track:
                t._auto_armed = False
                t._set("arm", False, by_live=True)
        if track is not None and track._kind == "midi" and not track._values.get("arm"):
            track._auto_armed = True
            track._set("arm", True, by_live=True)

    # --- the rest

    def undo(self) -> None:
        self._events().undo()

    def redo(self) -> None:
        pass  # the fake keeps no redo history

    def get_data(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self._data[key] = value


# --------------------------------------------------------------------------- the application and the browser


class BrowserItem(LiveObject):
    """One entry in Live's browser: a folder, a device, a preset."""

    def __init__(
        self,
        name: str,
        children: Iterable[BrowserItem] = (),
        *,
        loadable: bool = False,
        device: str | None = None,
        folder: bool | None = None,
    ) -> None:
        super().__init__(None)
        self._name, self._children, self._loadable, self._device = name, list(children), loadable, device
        self._folder = bool(self._children) if folder is None else folder

    name = property(lambda self: self._name)
    children = property(lambda self: tuple(self._children))
    is_folder = property(lambda self: self._folder)
    is_loadable = property(lambda self: self._loadable)
    is_device = property(lambda self: self._device is not None and self._loadable)
    is_selected = property(lambda self: False)
    uri = property(lambda self: f"query:Fake#{self._name}")
    source = property(lambda self: "Live")


class Browser(LiveObject):
    """Live's browser: the category roots, and load_item onto the selected track."""

    ROOTS = (
        "instruments",
        "audio_effects",
        "midi_effects",
        "drums",
        "sounds",
        "plugins",
        "packs",
        "samples",
        "clips",
        "user_library",
        "current_project",
        "max_for_live",
    )

    def __init__(self, song: Song, roots: dict[str, BrowserItem]) -> None:
        super().__init__(None)
        self._song, self._roots = song, roots
        self.loaded: list[tuple[str, str]] = []  # (item, track): what load_item put where, for tests

    def __getattr__(self, name: str) -> Any:
        if name in Browser.ROOTS:
            return self._roots.setdefault(name, BrowserItem(name.replace("_", " ").title(), folder=True))
        return super().__getattr__(name)

    user_folders = property(lambda self: ())

    def load_item(self, item: BrowserItem) -> None:
        """Load onto the selected track. GUESS: an instrument goes first (replacing one there), an effect last."""
        from zpkt.live.testing import devices

        self._song._events().check_write()
        track = self._song._view._values.get("selected_track")
        if track is None:
            raise RuntimeError("No track is selected")
        if not item.is_loadable or item._device is None:
            raise RuntimeError(f"{item.name!r} cannot be loaded")
        name = item.name.rsplit(".", 1)[0] if item.name.lower().endswith((".adv", ".adg")) else None
        device = devices.make(item._device, name=name)
        if device.type == DeviceType.instrument:
            if track._kind != "midi":
                raise RuntimeError("the fake loads instruments onto MIDI tracks only")
            if track._devices and track._devices[0].type == DeviceType.instrument:
                track.delete_device(0)
            track._add_device(device, 0)
        else:
            track._add_device(device)
        self.loaded.append((item.name, track.name))

    def preview_item(self, item: BrowserItem) -> None:
        pass

    def stop_preview(self) -> None:
        pass


class ApplicationView(LiveObject):
    """Which of Live's views show: zpkt shows and hides Detail/DeviceChain and focuses the Arranger."""

    def __init__(self, parent: LiveObject) -> None:
        super().__init__(parent)
        self._visible = {"Arranger", "Detail", "Detail/DeviceChain", "Browser"}
        self._focused = "Arranger"

    focused_document_view = property(lambda self: self._focused)

    def is_view_visible(self, name: str, main_window_only: bool = True) -> bool:
        return name in self._visible

    def show_view(self, name: str) -> None:
        self._visible.add(name)
        if name.startswith("Detail/"):
            self._visible.add("Detail")

    def hide_view(self, name: str) -> None:
        self._visible = {v for v in self._visible if v != name and not v.startswith(f"{name}/")}

    def focus_view(self, name: str) -> None:
        self.show_view(name)
        self._focused = name


class Application(LiveObject):
    """Live.Application.get_application(): the browser, the control surfaces, the version."""

    VERSION = (12, 3, 0)  # GUESS: a Live 12.3; zpkt does not read it

    def __init__(self, song: Song, browser: Browser, surfaces: Sequence[Any] = ()) -> None:
        super().__init__(None)
        self._song, self._browser, self._view = song, browser, ApplicationView(self)
        self._surfaces = list(surfaces)

    browser = property(lambda self: self._browser)
    view = property(lambda self: self._view)
    control_surfaces = property(
        lambda self: tuple(self._surfaces[:SURFACE_SLOTS]) + (None,) * (SURFACE_SLOTS - len(self._surfaces))
    )

    def get_document(self) -> Song:
        return self._song

    def get_major_version(self) -> int:
        return self.VERSION[0]

    def get_minor_version(self) -> int:
        return self.VERSION[1]

    def get_bugfix_version(self) -> int:
        return self.VERSION[2]


def live_module(app: Application) -> types.ModuleType:
    """A `Live` module whose get_application() is this fake's: what the Remote Script and pager.py import."""
    live = types.ModuleType("Live", "The fake Live module (zpkt.live.testing.lom).")
    names: dict[str, dict[str, Any]] = {
        "Application": {"get_application": lambda: app, "Application": Application},
        "Clip": {
            "MidiNoteSpecification": MidiNoteSpecification,
            "MidiNote": MidiNote,
            "WarpMarker": WarpMarker,
            "Clip": Clip,
        },
        "Song": {"Song": Song, "CuePoint": CuePoint},
        "Track": {"Track": Track, "RoutingType": RoutingType},
        "Device": {"Device": Device, "DeviceType": DeviceType},
        "DeviceParameter": {"DeviceParameter": DeviceParameter},
        "Browser": {"Browser": Browser, "BrowserItem": BrowserItem},
        "Chain": {"Chain": Chain},
        "MixerDevice": {"MixerDevice": MixerDevice},
    }
    for sub, attrs in names.items():
        module = types.ModuleType(f"Live.{sub}")
        module.__dict__.update(attrs)
        setattr(live, sub, module)
    return live
