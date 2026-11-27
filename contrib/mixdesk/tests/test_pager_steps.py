"""The pager's steps layer on the fake MiniLab: while the app says the step sequencer has a pattern in hand, the
pads are its steps (bank A 1-8, bank B 9-16), knobs 1-3 its values and the big encoder its sounds; when it says
otherwise, every control is the armed page's again.

The pager is loaded into FakeLive alone, the way the app loads it, and its datagrams go to a socket the test owns
(never the running desk's 8986). What the fake controller takes back is shaped as Live's own MiniLab_3 script has
it; what the hardware does with it is not tested here.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import pagercore as C
from zpkt.live import desk_pager
from zpkt.live import steps as live_steps
from zpkt.live.testing import FakeLive, MiniLab_3, hw002_like, lom

MIXDESK = Path(__file__).resolve().parents[1]
KICK_VOLUME = 0.85  # hw002_like's Kick bus
COMPARE = {
    "name": "Kick?",
    "controls": {"f1": {"track": "Kick bus", "param": "volume"}},
    "compare": {
        "name": "Kick",
        "pads": {"b7": 0, "b8": 1},
        "states": [
            {"name": "as it is", "writes": [["Kick bus/volume", KICK_VOLUME]]},
            {"name": "hotter", "writes": [["Kick bus/volume", 0.95]]},
        ],
        "targets": {"Kick bus/volume": {"track": "Kick bus", "param": "volume"}},
    },
}


def layer(lit=(), velocity=100, length=1.0, swing=0.0, total=16, track="Drums"):
    """What the app tells the pager (pagercore.steps_layer of a focus): `lit` are the step pads that are on."""
    return {
        "lit": [k in lit for k in range(16)],
        "velocity": velocity,
        "length": length,
        "swing": swing,
        "total": total,
        "track": track,
    }


class Pager:
    """A started pager: the fake Live, its MiniLab, and the datagrams it sent."""

    def __init__(self, live: FakeLive, minilab: MiniLab_3, udp: socket.socket) -> None:
        self.live, self.minilab, self.udp = live, minilab, udp
        self.e = minilab.elements

    def call(self, expr: str):
        return self.live.run(desk_pager.call_code(expr))

    def steps(self, state, force=False):
        return self.call(f"m.DESK.steps_layer({state!r}, {force!r})")

    def sent(self) -> list[dict]:
        out = []
        try:
            while True:
                out.append(json.loads(self.udp.recv(65536)))
        except (TimeoutError, BlockingIOError):
            return out

    def pads(self):
        return [*self.e.pad_bank_a_raw, *self.e.pad_bank_b_raw]

    def lit(self) -> list[int]:
        """The step pads (0-15) whose light is on."""
        return [k for k, pad in enumerate(self.pads()) if pad.lit]

    def messages(self) -> int:
        return sum(len(pad.messages) for pad in self.pads())


@pytest.fixture
def pager(monkeypatch):
    monkeypatch.setattr(live_steps.time, "sleep", lambda s: None)
    cfg = json.loads((MIXDESK / "desk.json").read_text())
    cfg["pages"].append(COMPARE)
    minilab = MiniLab_3()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(0.2)
    live = FakeLive(hw002_like(), surfaces=[minilab])
    try:
        live_steps.new_drum_track(live, "Drums", "909 Core Kit")
        live.run(desk_pager.start_code(MIXDESK / "pager.py", cfg, udp.getsockname()[1]))
        made = Pager(live, minilab, udp)
        made.sent()
        yield made
        made.call("m.DESK.stop()")
        assert live.listener_errors == []
    finally:
        live.close()
        udp.close()


# ---- on and off -----------------------------------------------------------------------------------------------------


def test_the_layer_is_on_exactly_while_the_app_says_so_and_the_pads_arm_pages_again_after(pager):
    pad_a2 = pager.e.pad_bank_a_raw[1]
    pad_a2.receive(127)
    armed = pager.call("m.DESK.page")
    assert [m["t"] for m in pager.sent()] == ["page"] and armed != 0
    assert pager.steps(layer()) is True
    pad_a2.receive(127)
    pad_a2.receive(0)
    assert pager.sent() == [{"t": "step", "pad": 1}] and pager.call("m.DESK.page") == armed  # a step, not a page
    assert pager.steps(None) is False
    pager.e.pad_bank_b_raw[0].receive(127)
    assert [m["t"] for m in pager.sent()] == ["page"] and pager.call("m.DESK.page") == 0
    assert pager.steps(None) is False  # off twice is off


def test_a_pad_press_in_each_bank_is_its_step_bank_a_1_to_8_bank_b_9_to_16(pager):
    pager.steps(layer())
    for bank, first in ((pager.e.pad_bank_a_raw, 0), (pager.e.pad_bank_b_raw, 8)):
        for k in (0, 3, 7):
            bank[k].receive(100)
            bank[k].receive(0)  # letting go is no second press
            assert pager.sent() == [{"t": "step", "pad": first + k}]


# ---- the lights -----------------------------------------------------------------------------------------------------


def test_lit_pads_are_the_steps_that_are_on_and_a_light_is_sent_only_when_it_changes(pager):
    pager.steps(layer(lit=(0, 4, 8, 12, 15)))
    assert pager.lit() == [0, 4, 8, 12, 15]  # both banks: 8, 12 and 15 are pads B1, B5 and B8
    assert all(pad.colour in (C.PAD_LIT, C.PAD_DARK) for pad in pager.pads())  # a colour, as the script sends one
    before = pager.messages()
    pager.steps(layer(lit=(0, 4, 8, 12, 15), velocity=64))  # a knob's value moved: no pad changes
    assert pager.messages() == before
    pager.steps(layer(lit=(0, 4, 6, 8, 12)))  # step 7 came on, step 16 went off
    assert pager.lit() == [0, 4, 6, 8, 12] and pager.messages() == before + 2
    pager.steps(layer(lit=(0, 4, 6, 8, 12)), force=True)  # said again whole: after a press Live refused
    assert pager.messages() == before + 2 + 16 and pager.lit() == [0, 4, 6, 8, 12]


def test_a_press_flips_the_light_under_the_finger_and_the_apps_word_sets_it_right(pager):
    pager.steps(layer(lit=(0,)))
    pad = pager.e.pad_bank_a_raw[3]
    pad.receive(127)
    assert pager.lit() == [0, 3]  # at once, before Live has flipped the step
    sent = len(pad.messages)
    pad.receive(0)
    assert len(pad.messages) == sent + 1 and pad.lit  # letting go says the light again (the hardware may differ)
    pager.steps(layer(lit=(0, 3)))  # the app: the step is on
    assert len(pad.messages) == sent + 1 and pager.lit() == [0, 3]  # as the pad shows already
    pager.steps(layer(lit=(0,)), force=True)  # or: Live refused, the app says the lights again
    assert pager.lit() == [0]


def test_when_the_layer_ends_the_lights_are_what_the_armed_page_wants(pager):
    page = pager.call("len(m.DESK.cfg['pages'])") - 1
    pager.call(f"m.DESK.arm({page})")
    assert pager.lit() == [6, 14]  # the compare state that holds, "as it is", on pad 7 of both banks
    pager.steps(layer(lit=(0, 9)))
    assert pager.lit() == [0, 9]
    pager.live.run("find_track('Kick bus').mixer_device.volume.value = 0.95")  # the other state holds now
    assert pager.lit() == [0, 9]  # the page's values move: the pads stay the sequencer's
    pager.e.pad_bank_a_raw[6].receive(127)
    assert pager.sent()[-1] == {"t": "step", "pad": 6}  # and its compare pad is a step, not a state
    pager.steps(layer(lit=(0, 9)), force=True)
    pager.steps(None)
    assert pager.lit() == [7, 15]  # "hotter", pad 8 of both banks: read from the values, as always
    pager.e.pad_bank_a_raw[6].receive(127)
    assert pager.sent()[-1] == {"t": "pad", "page": page, "slot": "b7"}  # the compare pad is a state again


def test_the_layer_outlives_a_page_armed_from_the_screen_and_a_controller_that_comes_back(pager):
    pager.steps(layer(lit=(2,), velocity=90))
    pager.call("m.DESK.arm(1)")
    assert pager.lit() == [2] and pager.e.encoders_raw[0].sent[-1] == 90  # knob 1 is still the velocity
    for pad in pager.pads():
        pad.colour = None  # the controller was unplugged: it forgot
    assert pager.call("m.DESK.attach()") is True
    assert pager.lit() == [2]
    pager.e.pad_bank_b_raw[7].receive(127)
    assert pager.sent()[-1] == {"t": "step", "pad": 15}


# ---- the knobs ------------------------------------------------------------------------------------------------------


def perc(pager):
    return next(t for t in pager.live.song.tracks if t.name == "Perc bus").mixer_device.volume  # page 0, k1


def test_knobs_1_to_3_set_velocity_length_and_swing_and_the_other_knobs_stay_the_pages(pager):
    volume = perc(pager).value
    pager.steps(layer())
    k = pager.e.encoders_raw
    k[0].receive(96)
    k[1].receive(127)
    k[1].receive(0)
    k[2].receive(64)
    assert pager.sent() == [
        {"t": "step_knob", "what": "velocity", "value": 96},
        {"t": "step_knob", "what": "length", "value": 16.0},  # the pattern's own length is the longest
        {"t": "step_knob", "what": "length", "value": 0.25},
        {"t": "step_knob", "what": "swing", "value": 0.38},
    ]
    assert perc(pager).value == volume  # the page's control on knob 1 did not move
    k[1].receive(1)  # still the shortest: the value did not change, so nothing is sent
    assert pager.sent() == []
    hats = next(t for t in pager.live.song.tracks if t.name == "Hats bus").mixer_device.volume  # page 0, k2
    assert hats.value != pytest.approx(1 / 127)
    k[3].receive(127)  # knob 4 is the page's, in the layer too
    assert {"t": "hw", "page": 0, "slot": "k4", "hw": 1.0, "picked": True} in pager.sent()
    pager.e.volume_fader.receive(127)  # and so are the faders
    assert any(m["t"] == "hw" and m["slot"] == "f1" for m in pager.sent())
    pager.steps(None)
    k[0].receive(64)
    assert perc(pager).value == pytest.approx(64 / 127)  # knob 1 is the page's again
    assert not [m for m in pager.sent() if m["t"] == "step_knob"]


def test_the_knobs_stand_where_the_values_are_when_the_layer_starts_and_where_the_page_is_when_it_ends(pager):
    k = pager.e.encoders_raw
    page_places = [enc.sent[-1] for enc in k[:3]]
    pager.steps(layer(velocity=100, length=2.0, swing=0.3))
    places = [enc.sent[-1] for enc in k[:3]]
    assert places == [100, C.step_knob_place("length", 2.0, 16), C.step_knob_place("swing", 0.3, 16)]
    assert [C.step_knob_value(w, p, 16) for w, p in zip(("velocity", "length", "swing"), places, strict=True)] == [
        100,
        2.0,
        0.3,
    ]
    assert k[0].messages[-1] == (240, 0, 32, 107, 127, 66, 33, 16, 0, 7, 0, 100, 247)  # the script's own realign
    sent = [len(enc.sent) for enc in k]
    pager.steps(layer(lit=(1,), velocity=100, length=2.0, swing=0.3))  # only a light changed: no knob is told
    assert [len(enc.sent) for enc in k] == sent
    pager.steps(layer(velocity=70, length=2.0, swing=0.3))  # the page changed the velocity: knob 1 follows
    assert k[0].sent[-1] == 70 and [len(enc.sent) for enc in k[1:]] == sent[1:]
    pager.steps(None)
    assert [enc.sent[-1] for enc in k[:3]] == page_places and [len(enc.sent) for enc in k[3:]] == sent[3:]


def test_the_apps_echo_does_not_move_a_knob_the_hand_is_on(pager):
    pager.steps(layer(velocity=100))
    k1 = pager.e.encoders_raw[0]
    k1.receive(60)
    k1.receive(61)
    told = len(k1.messages)
    pager.steps(layer(velocity=60))  # the echo of the first turn arrives after the second
    assert len(k1.messages) == told
    pager.steps(layer(velocity=61))  # where the knob stands: nothing to say
    assert len(k1.messages) == told
    pager.call("m.DESK.step_touched.clear()")  # the hand has been off the knob for a while
    pager.steps(layer(velocity=30))  # the page set it
    assert k1.sent[-1] == 30 and len(k1.messages) == told + 1


# ---- the data knob --------------------------------------------------------------------------------------------------


def test_the_data_knob_steps_through_sounds_in_the_layer_and_through_pages_outside_it(pager):
    turn = pager.e.display_encoder
    turn.receive(65)
    assert pager.call("m.DESK.page") == 1 and [m["t"] for m in pager.sent()] == ["page"]
    pager.steps(layer())
    turn.receive(65)
    turn.receive(62)
    turn.receive(64)  # no turn
    assert pager.sent() == [{"t": "step_sound", "turn": 1}, {"t": "step_sound", "turn": -2}]
    assert pager.call("m.DESK.page") == 1  # no page was armed
    pager.steps(None)
    turn.receive(63)
    assert pager.call("m.DESK.page") == 0


# ---- keys choose the sound: the Drum Rack's selected pad ---------------------------------------------------------------

SELECT = "r = find_track('Drums').devices[0]\nr.view.selected_drum_pad = r.drum_pads[{note}]"


def test_the_pad_selected_in_the_tracks_drum_rack_is_reported_as_the_sound_chosen(pager):
    pager.live.run(SELECT.format(note=37))
    assert pager.sent() == []  # no layer: nobody listens
    pager.steps(layer())
    pager.live.run(SELECT.format(note=38))  # as Live does when a key plays the snare (GUESS: Auto Select)
    assert pager.sent() == [{"t": "step_sound", "pitch": 38}]
    pager.live.run(SELECT.format(note=40))  # a pad that holds nothing is no sound
    assert pager.sent() == []
    pager.steps(layer(lit=(3,)))  # the layer goes on for the same track: still one listener
    pager.live.run(SELECT.format(note=42))
    assert pager.sent() == [{"t": "step_sound", "pitch": 42}]
    pager.steps(None)
    pager.live.run(SELECT.format(note=36))
    assert pager.sent() == []  # the layer ended: the listener is gone


def test_a_track_with_no_drum_rack_or_a_live_without_the_listener_is_no_error(pager, monkeypatch):
    assert pager.steps(layer(track="Kick bus")) is True  # an audio track: nothing to listen to
    assert pager.steps(layer(track="Nobody")) is True  # a track that is gone
    pager.steps(None)
    monkeypatch.setattr(lom.RackDeviceView, "_listenable", frozenset())  # a Live whose view has no such listener
    assert pager.steps(layer()) is True
    pager.live.run(SELECT.format(note=38))
    assert pager.sent() == []
    pager.e.pad_bank_a_raw[0].receive(127)
    assert pager.sent() == [{"t": "step", "pad": 0}]  # the rest of the layer works
