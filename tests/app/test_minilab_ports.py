"""The MIDI port: the fake, mido's messages as Events, the choice of a port by name, and the missing extra."""

from __future__ import annotations

import sys
import types

import pytest

from zpkt.app.minilab import ports
from zpkt.app.minilab.ports import FakePort, PortUnavailable
from zpkt.app.minilab.profile import Event, load_profile


def mido_message(kind, **fields):
    return types.SimpleNamespace(type=kind, **fields)


def test_mido_messages_become_events_and_what_the_map_does_not_use_is_dropped():
    cc = ports.event_from_mido(mido_message("control_change", channel=0, control=86, value=64))
    assert cc == Event("cc", 1, 86, 64)
    on = ports.event_from_mido(mido_message("note_on", channel=9, note=36, velocity=100))
    off = ports.event_from_mido(mido_message("note_off", channel=9, note=36, velocity=64))
    assert on == Event("note", 10, 36, 100) and off == Event("note", 10, 36, 0)
    bend = ports.event_from_mido(mido_message("pitchwheel", channel=0, pitch=-8192))
    assert bend == Event("pitchbend", 1, 0, 0)
    assert ports.event_from_mido(mido_message("pitchwheel", channel=0, pitch=0)).value == 8192
    assert ports.event_from_mido(mido_message("clock")) is None
    assert ports.event_from_mido(mido_message("polytouch", channel=0, note=1, value=1)) is None


def test_a_port_is_chosen_by_name_and_one_that_says_midi_is_preferred():
    names = ["IAC Driver Bus 1", "MiniLab3 DIN THRU", "Arturia MiniLab3 MIDI", "MiniLab3 MCU"]
    assert ports.choose_name(names, ["MiniLab3"], ["MIDI"]) == "Arturia MiniLab3 MIDI"
    assert ports.choose_name(names, ["MiniLab3"], []) == "MiniLab3 DIN THRU"
    assert ports.choose_name(names, ["minilab 3"], []) is None
    assert ports.choose_name([], ["MiniLab3"], ["MIDI"]) is None


def test_the_fake_port_plays_messages_in_and_keeps_the_sysex_out():
    port, got = FakePort(), []
    with pytest.raises(RuntimeError, match="not started"):
        port.receive("cc", 1, 1)
    port.start(got.append)
    port.receive("note", 40, 99, channel=10)
    port.send_sysex([0xF0, 1, 0xF7])
    assert got == [Event("note", 10, 40, 99)] and port.sent() == [[0xF0, 1, 0xF7]]
    port.close()
    assert port.closed


def test_without_the_midi_extra_the_adapter_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "mido", None)  # an import of it fails
    with pytest.raises(PortUnavailable, match="uv sync --extra midi"):
        ports.open_port(load_profile())


class FakeMido:
    """mido with two ports and nothing behind them."""

    def __init__(self, inputs, outputs):
        self.inputs, self.outputs, self.opened, self.sent = inputs, outputs, [], []

    def get_input_names(self):
        return self.inputs

    def get_output_names(self):
        return self.outputs

    def open_output(self, name):
        self.opened.append(("out", name))
        mido = self

        class Out:
            def send(self, message):
                mido.sent.append(message)

            def close(self):
                pass

        return Out()

    def open_input(self, name, callback):
        self.opened.append(("in", name))
        self.callback = callback

        class In:
            def close(self):
                pass

        return In()

    class Message:
        def __init__(self, kind, data):
            self.kind, self.data = kind, data


def test_a_real_port_is_opened_by_the_profiles_name_or_the_environment_and_sysex_loses_f0_and_f7(monkeypatch):
    fake = FakeMido(["Arturia MiniLab3 MIDI", "Other"], ["Arturia MiniLab3 MIDI", "Other"])
    monkeypatch.setitem(sys.modules, "mido", fake)
    monkeypatch.setitem(sys.modules, "rtmidi", types.ModuleType("rtmidi"))
    port = ports.open_port(load_profile())
    got = []
    port.start(got.append)
    assert fake.opened == [("out", "Arturia MiniLab3 MIDI"), ("in", "Arturia MiniLab3 MIDI")]
    fake.callback(mido_message("control_change", channel=0, control=14, value=3))
    fake.callback(mido_message("clock"))
    assert got == [Event("cc", 1, 14, 3)]
    port.send_sysex([0xF0, 0, 32, 0xF7])
    assert fake.sent[0].kind == "sysex" and fake.sent[0].data == [0, 32]
    port.close()
    monkeypatch.setenv("ZPKT_MINILAB_PORT", "Other")
    assert ports.open_port(load_profile()).name == "Other"


def test_no_matching_port_says_what_to_check(monkeypatch):
    monkeypatch.setitem(sys.modules, "mido", FakeMido(["Other"], ["Other"]))
    monkeypatch.setitem(sys.modules, "rtmidi", types.ModuleType("rtmidi"))
    with pytest.raises(PortUnavailable, match="control surface set to None"):
        ports.open_port(load_profile())
