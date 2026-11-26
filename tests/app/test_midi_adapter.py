"""The MIDI adapter on the app's rig: a fake MiniLab port in, the bus and Live (FakeLive) behind it.

Nothing here opens a MIDI port, talks to a MiniLab or to the running desk.
"""

from __future__ import annotations

import time

import pytest

from tests.app.conftest import wait_for
from zpkt.app import adapters
from zpkt.app.adapters import AppContext
from zpkt.app.adapters.midi import MidiAdapter
from zpkt.app.minilab.latency import LatencyProbe
from zpkt.app.minilab.ports import FakePort
from zpkt.live import state as S

KNOB_CC = {f"k{i}": cc for i, cc in enumerate((86, 87, 89, 90, 110, 111, 116, 117), 1)}
FADER_CC = {"f1": 14, "f2": 15, "f3": 30, "f4": 31}
PAD_A = {f"a{i}": 35 + i for i in range(1, 9)}
PAD_B = {f"b{i}": 43 + i for i in range(1, 9)}
SHIFT, DATA_TURN, DATA_PUSH, HOLD, MOD = 27, 28, 118, 64, 1


class Hands:
    """A person at the fake MiniLab: moves controls and waits for the adapter to act."""

    def __init__(self, rig, tempo="auto", tick_s=0.01, probe=None):
        self.rig, self.port = rig, FakePort()
        context = AppContext(rig.desk.bus, rig.desk, rig.desk.settings)
        self.adapter = MidiAdapter(context, port=self.port, tempo=tempo, tick_s=tick_s, probe=probe)

    def __enter__(self):
        self.adapter.start()
        return self

    def __exit__(self, *exc):
        self.adapter.stop()

    def knob(self, slot, value):
        self.port.receive("cc", KNOB_CC[slot], value)

    def fader(self, slot, value):
        self.port.receive("cc", FADER_CC[slot], value)

    def pad(self, name, velocity=100):
        number = {**PAD_A, **PAD_B}[name]
        self.port.receive("note", number, velocity, channel=10)
        self.port.receive("note", number, 0, channel=10)

    def cc(self, number, value):
        self.port.receive("cc", number, value)

    def hold_shift(self):
        self.cc(SHIFT, 127)

    def release_shift(self):
        self.cc(SHIFT, 0)

    def bend(self, amount):
        self.port.receive("pitchbend", 0, int(8192 + amount * 8191))

    def key(self, note):
        self.port.receive("note", note, 90)
        self.port.receive("note", note, 0)

    def settle(self):
        """Wait until the adapter has handled everything it was sent."""
        time.sleep(0.05)
        wait_for(lambda: self.adapter._inbox.empty() and not self.adapter._pending, 3)
        time.sleep(0.05)


def raw(rig, key):
    return S.flatten(S.take(rig.conn))[key].raw


def key_of(rig, slot, page=0):
    return rig.state()["values"][f"{page}:{slot}"]["key"]


def n_of(rig, slot, page=0):
    return rig.state()["values"][f"{page}:{slot}"]["n"]


def test_the_midi_adapter_is_found_by_name_and_is_not_started_by_default(rig):
    assert "midi" in adapters.discover()
    context = AppContext(rig.desk.bus, rig.desk, rig.desk.settings)
    (made,) = adapters.create(["midi"], context)
    assert made.name == "midi" and made.port is None  # no port opened until start


def test_starting_shows_the_page_on_the_minilab_and_stopping_lets_go(rig):
    with Hands(rig) as hands:
        wait_for(lambda: len(hands.port.sent()) > 20)
        sent = hands.port.sent()
        leds = [m for m in sent if m[6:9] == [2, 2, 22]]
        rings = [m for m in sent if m[6:9] == [33, 16, 0]]
        shows = [m for m in sent if m[6:9] == [4, 2, 96]]
        assert len(leds) == 16 and len(rings) == 8 and len(shows) == 1
        assert bytes(shows[0][17:22]) == b"Buses"
        ring_k8 = next(m for m in rings if m[9] == 14)
        assert ring_k8[10] == round(127 * n_of(rig, "k8"))  # the ring is at the control's place
        lit = next(m for m in leds if m[9] == 52)
        assert lit[10:13] == [127, 127, 127]  # pad A1 arms the armed page: bright
    assert hands.port.closed


def test_turning_a_knob_moves_the_control_in_live_as_the_minilab_and_history_says_so(rig):
    key = key_of(rig, "k3")
    with Hands(rig) as hands:
        hands.knob("k3", 127)
        assert wait_for(lambda: raw(rig, key) == pytest.approx(1.0))
    moves = [e for e in rig.desk.history.entries if e["k"] == "move"]
    assert moves and all(e["who"] == "minilab" for e in moves)
    assert rig.post("/api/undo")[0] == 200  # undo covers the MiniLab's hand like any other
    assert wait_for(lambda: raw(rig, key) == pytest.approx(0.0))


def test_a_stream_of_knob_values_is_sent_as_one_batch_of_the_latest(rig):
    key = key_of(rig, "k3")
    with Hands(rig, tick_s=0.4) as hands:
        hands.settle()
        before = len(rig.desk.bus.log)
        for v in range(1, 101):
            hands.knob("k3", v)
        hands.knob("k4", 64)
        assert wait_for(lambda: n_of(rig, "k3") == pytest.approx(100 / 127, abs=0.01), 5)
        hands.settle()
    sets = [e for e in list(rig.desk.bus.log)[before:] if e["kind"] == "page.set"]
    assert len(sets) <= 2 and all(e["who"] == "minilab" for e in sets)
    assert raw(rig, key) == pytest.approx(100 / 127, abs=0.01)  # the last value won, not an early one
    assert n_of(rig, "k4") == pytest.approx(64 / 127, abs=0.01)  # one batch carried both knobs


def test_a_fader_does_nothing_until_it_picks_up_the_value(rig):
    key = key_of(rig, "f1")  # sits at 0.85
    with Hands(rig) as hands:
        hands.fader("f1", 10)
        hands.settle()
        assert raw(rig, key) == pytest.approx(0.85)
        hands.fader("f1", 120)  # passes 0.85 on the way: picks up
        assert wait_for(lambda: raw(rig, key) != pytest.approx(0.85))
        hands.fader("f1", 20)
        assert wait_for(lambda: raw(rig, key) == pytest.approx(20 / 127, abs=0.01))


def test_pad_a2_arms_its_page_and_pad_a1_pressed_again_flips_to_the_layer_and_the_rings_follow(rig):
    with Hands(rig) as hands:
        hands.settle()
        count = len(hands.port.sent())
        hands.pad("a2")  # desk.json: Kick is the first page on pad 2
        assert wait_for(lambda: rig.state()["page"] == 2)

        def shown():
            new = hands.port.sent()[count:]
            rings = [m for m in new if m[6:9] == [33, 16, 0]]
            shows = [m for m in new if m[6:9] == [4, 2, 96]]
            return len(rings) >= 8 and shows and bytes(shows[-1][17:21]) == b"Kick"

        wait_for(shown)
        new = hands.port.sent()[count:]
        shows = [m for m in new if m[6:9] == [4, 2, 96]]
        assert shows and bytes(shows[-1][17:21]) == b"Kick"
        assert len([m for m in new if m[6:9] == [33, 16, 0]]) == 8
        hands.pad("a1")  # Buses, the first page on pad 1
        assert wait_for(lambda: rig.state()["page"] == 0)
        hands.pad("a1")  # pressed again: its layer, Match A/B
        assert wait_for(lambda: rig.state()["page"] == 1)


def test_octave_buttons_step_pages_once_their_numbers_are_learned(rig):
    from zpkt.app.minilab.profile import Message, load_profile

    profile = load_profile().with_message("octave_up", Message("cc", 1, 99))
    with Hands(rig) as hands:
        hands.adapter.profile = profile
        hands.cc(99, 127)
        assert wait_for(lambda: rig.state()["page"] == 1)


def test_a_bank_b_pad_arms_the_same_page_as_bank_a(rig):
    with Hands(rig) as hands:
        hands.pad("b2")  # desk.json: Kick is the first page on pad 2, as for A2
        assert wait_for(lambda: rig.state()["page"] == 2)


def test_shift_a5_undoes_and_shift_a6_redoes(rig):
    key = key_of(rig, "k3")
    with Hands(rig) as hands:
        hands.knob("k3", 127)
        assert wait_for(lambda: raw(rig, key) == pytest.approx(1.0))
        hands.settle()
        hands.hold_shift()
        hands.pad("a5")
        assert wait_for(lambda: raw(rig, key) == pytest.approx(0.0))
        hands.pad("a6")
        assert wait_for(lambda: raw(rig, key) == pytest.approx(1.0))
        hands.release_shift()
    assert [e["who"] for e in rig.desk.history.entries] == ["minilab"]  # one move, undone and done again
    _, body = rig.get("/api/changes")
    assert {c["who"] for c in body["changes"]} == {"minilab"}  # the undo and the redo are the MiniLab's too


def test_shift_b7_makes_a_version_like_shift_a7(rig):
    with Hands(rig) as hands:
        hands.hold_shift()
        hands.pad("b7")
        assert wait_for(lambda: any(e["k"] == "checkpoint" and e["who"] == "minilab" for e in rig.desk.history.entries))


def test_pitch_bend_up_holds_the_pin_and_letting_go_brings_now_back(rig):
    key = key_of(rig, "k3")
    rig.command("monitor.pin")
    rig.command("mix.set", {"norms": [[key, 0.9]]})
    now = raw(rig, key)
    with Hands(rig) as hands:
        hands.bend(0.9)
        assert wait_for(lambda: rig.desk.monitor.message()["hearing"] == "pin")
        assert raw(rig, key) != pytest.approx(now)  # the pinned value is in Live
        hands.bend(0.0)
        assert wait_for(lambda: rig.desk.monitor.message()["hearing"] == "now")
        assert wait_for(lambda: raw(rig, key) == pytest.approx(now))


def test_hold_keeps_the_pin_on_after_the_strip_lets_go(rig):
    rig.command("monitor.pin")
    with Hands(rig) as hands:
        hands.cc(HOLD, 127)
        hands.bend(0.9)
        assert wait_for(lambda: rig.desk.monitor.message()["hearing"] == "pin")
        hands.bend(0.0)
        hands.settle()
        assert rig.desk.monitor.message()["hearing"] == "pin"
        hands.cc(HOLD, 127)  # Hold again
        assert wait_for(lambda: rig.desk.monitor.message()["hearing"] == "now")


def test_the_data_knob_picks_a_control_and_the_mod_strip_and_keys_move_it_and_a_push_resets_it(rig):
    key = key_of(rig, "k1")  # Perc bus volume, default (from Live) is not 1.0
    with Hands(rig) as hands:
        hands.cc(DATA_TURN, 65)  # focus: the first control, k1
        hands.settle()
        assert hands.adapter._map.focus == "k1"
        shows = [m for m in hands.port.sent() if m[6:9] == [4, 2, 96]]
        assert b"Perc bus" in bytes(shows[-1])  # the display shows the focused control
        hands.cc(MOD, 127)
        assert wait_for(lambda: raw(rig, key) == pytest.approx(1.0))
        hands.settle()
        hands.key(60)  # the middle of the 25 keys
        assert wait_for(lambda: n_of(rig, "k1") == pytest.approx(0.5, abs=0.01))
        hands.settle()
        hands.cc(DATA_PUSH, 127)
        assert wait_for(lambda: n_of(rig, "k1") != pytest.approx(0.5, abs=0.01))
    assert all(e["who"] == "minilab" for e in rig.desk.history.entries if e["k"] == "move")
    assert rig.desk.bus.log[-1]["kind"] in ("mix.reset", "page.set")


def test_the_transport_buttons_play_and_pause_live_now_that_live_has_let_go(rig):
    with Hands(rig) as hands:
        hands.cc(107, 127)  # play
        assert wait_for(lambda: rig.live.song.is_playing)
        assert wait_for(lambda: rig.state()["playing"] and hands.adapter._view.playing)  # the desk has told the map
        hands.cc(107, 0)
        hands.cc(107, 127)  # play again toggles to pause
        assert wait_for(lambda: not rig.live.song.is_playing)


def test_the_data_knob_with_shift_scrubs_the_playhead(rig):
    with Hands(rig) as hands:
        hands.hold_shift()
        hands.cc(DATA_TURN, 65)
        hands.cc(DATA_TURN, 65)
        assert wait_for(lambda: rig.live.song.current_song_time == pytest.approx(8.0))


def test_the_tempo_layer_is_zpkt_minilab_tempos_job(rig):
    with Hands(rig, tempo="on") as hands:
        hands.fader("f4", 127)
        assert wait_for(lambda: rig.live.song.tempo == pytest.approx(200))
        hands.pad("a7")  # tempo x 0.5
        assert wait_for(lambda: rig.live.song.tempo == pytest.approx(100))
        hands.pad("a8")  # tempo x 2
        assert wait_for(lambda: rig.live.song.tempo == pytest.approx(200))


def test_while_the_desk_drives_the_minilab_the_tempo_layer_stays_off(rig):
    tempo = rig.live.song.tempo
    with Hands(rig, tempo="auto") as hands:
        hands.fader("f4", 127)
        hands.settle()
    assert rig.live.song.tempo == tempo


def test_a_refused_move_is_said_on_the_display_and_sends_nothing_to_live(rig):
    key = key_of(rig, "k3")
    rig.live.song.file_path = "/Sets/HW002_121_pp_B Project/HW002_121_pp_B.als"
    rig.desk.bus.guard.forget()
    with Hands(rig) as hands:
        hands.knob("k3", 127)
        assert wait_for(lambda: hands.adapter.refused)
        kind, status, why = hands.adapter.refused[0]
        assert (kind, status) == ("page.set", 409) and "HW002_121_pp_B" in why
        assert wait_for(lambda: b"Refused" in bytes(hands.port.sent()[-1]))
    assert raw(rig, key) == pytest.approx(0.0)


def test_a_knob_on_a_page_with_no_such_control_and_unknown_messages_do_nothing(rig):
    with Hands(rig) as hands:
        before = len(rig.desk.bus.log)
        hands.cc(3, 100)  # a message the profile does not know
        hands.port.receive("note", 20, 100, channel=3)
        hands.settle()
        assert len(rig.desk.bus.log) == before


def test_the_probe_sees_the_knobs_batches_and_live_reporting_them_back(rig):
    probe = LatencyProbe()
    with Hands(rig, probe=probe) as hands:
        for v in (20, 60, 100):
            hands.knob("k3", v)
            hands.settle()
            time.sleep(0.1)
    result = probe.report()
    assert result["queue"]["count"] >= 1 and result["bus"]["count"] >= 1
    assert result["echo"].get("count", 0) >= 1 and result["total"]["max_ms"] > 0


def test_a_bad_message_does_not_end_the_adapter(rig, caplog, monkeypatch):
    key = key_of(rig, "k3")
    with Hands(rig) as hands:
        original = hands.adapter._on_event
        calls = []

        def boom(event, at):
            calls.append(event)
            if len(calls) == 1:
                raise RuntimeError("one bad message")
            original(event, at)

        monkeypatch.setattr(hands.adapter, "_on_event", boom)
        hands.knob("k3", 5)
        hands.knob("k3", 127)
        assert wait_for(lambda: raw(rig, key) == pytest.approx(1.0))
    assert "one bad message" in caplog.text


def test_the_tempo_choice_must_be_one_of_the_modes(rig):
    context = AppContext(rig.desk.bus, rig.desk, rig.desk.settings)
    with pytest.raises(ValueError, match="tempo is one of auto, on, off"):
        MidiAdapter(context, port=FakePort(), tempo="sometimes")


def test_a_pad_that_holds_a_compare_state_switches_the_mix_as_the_minilab(rig):
    from zpkt.app.bus import Command

    vol = "Kick bus/volume"
    spec = {
        "title": "Kick: hotter?",
        "groups": [{"name": "Kick", "controls": [{"target": vol}]}],
        "compare": {"states": [{"name": "as it is"}, {"name": "hotter", "writes": [{"target": vol, "to": 0.8}]}]},
    }
    code, made = rig.desk.bus.submit(Command("page.make", "you", {"spec": spec}))
    assert code == 200, made
    base = raw(rig, vol)
    with Hands(rig) as hands:
        hands.settle()
        hands.pad("a8")  # "hotter" is on the last pad
        assert wait_for(lambda: abs(raw(rig, vol) - 0.8) < 1e-6)
        entry = rig.desk.history.entries[-1]
        assert entry["who"] == "minilab" and entry["compare"]["to"] == "hotter"
        assert rig.state()["page"] == made["pages"][0]  # it did not arm another page
        hands.settle()
        lit = [m for m in hands.port.sent() if m[6:9] == [2, 2, 22] and m[10:13] == [0, 127, 30]]
        assert lit, "the pad of the state that is on is lit"
        hands.pad("b7")  # bank B, "as it is": the way back
        assert wait_for(lambda: abs(raw(rig, vol) - base) < 1e-6)
