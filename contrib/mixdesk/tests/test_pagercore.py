"""pagercore.py: the pager's decisions, without Live (pager.py loads the same file inside Live)."""

from __future__ import annotations

import pytest

import pagercore as C

CFG = {
    "pages": [
        {"name": "Buses"},
        {"name": "Kick", "pad": 2},
        {"name": "Kick EQ", "pad": 2},
        {"name": "Three"},
        *({"name": f"p{i}"} for i in range(4, 10)),
    ]
}


def test_pads_arm_their_pages_and_a_second_press_flips_to_the_layer():
    assert [C.pad_of(CFG, i) for i in range(len(CFG["pages"]))] == [1, 2, 2, 4, 5, 6, 7, 8, None, None]
    assert C.page_for_pad(CFG, 2, armed=0) == 1
    assert C.page_for_pad(CFG, 2, armed=1) == 2 and C.page_for_pad(CFG, 2, armed=2) == 1
    assert C.page_for_pad(CFG, 3, armed=0) is None


def test_the_big_encoder_steps_through_every_page_and_wraps():
    assert C.page_for_encoder(65, 0, 10) == 1 and C.page_for_encoder(63, 0, 10) == 9
    assert C.page_for_encoder(64, 5, 10) is None


@pytest.mark.parametrize(
    ("n", "last", "value", "picks"),
    [
        (0.51, None, 0.5, True),
        (0.6, None, 0.5, False),
        (0.6, 0.4, 0.5, True),
        (0.6, 0.55, 0.5, False),
        (0.4, 0.6, 0.5, True),
    ],
)
def test_a_fader_picks_up_near_the_value_or_once_it_passes_it(n, last, value, picks):
    assert C.picks_up(n, last, value) is picks


def test_loops_seeks_and_the_end_of_the_arrangement():
    assert C.loop_mode(False, 0.0, 64.0) == "off"
    assert C.loop_mode(True, 0.0, 64.0) == "build" and C.loop_mode(True, 64.0, 96.0) == "drop"
    assert C.loop_mode(True, 8.0, 16.0) == "on"
    assert C.seek_position(-3) == 0.0 and C.seek_position(500) == pytest.approx(159.99)
    assert C.play_from(160.0) == 0.0 and C.play_from(32.0) == 32.0
    assert C.ran_past_end(True, False, 160.0) and not C.ran_past_end(True, True, 170.0)


def test_a_reloaded_pager_maps_a_v1_b_slot_to_the_working_mix():
    assert C.carried_slot({"slot": "B", "v": 1}) == "W"
    assert C.carried_slot({"slot": "B", "v": 2}) == "B"
    assert C.carried_slot({}) == "W"


def test_control_values():
    assert C.norm(0.5, 0.0, 2.0) == 0.25 and C.norm(1.0, 1.0, 1.0) == 0.0
    assert C.value_at(1.5, 0.0, 10.0, False) == 10.0 and C.value_at(0.26, 0.0, 10.0, True) == 3.0
    assert C.toggled(1.0, 0.0, 1.0, True) == 0.0 and C.toggled(0.0, 0.0, 1.0, True) == 1.0
    assert C.toggled(2.0, 0.0, 3.0, True) == 3.0 and C.toggled(3.0, 0.0, 3.0, True) == 0.0
    assert C.macro_position(0.75, 0.5, 1.0) == 0.5 and C.macro_position(0.0, 0.5, 1.0) == 0.0
    assert C.macro_position(0.3, 0.5, 0.5) == 0.0
    assert C.macro_value(0.5, 1.0, 0.0, 0.0, 1.0, False) == 0.5 and C.macro_value(0.5, 0.0, 3.0, 0.0, 3.0, True) == 2


class FakeControl:
    def __init__(self, error=None):
        self.error, self.key = error, "Kick bus/volume"

    def norm(self):
        return 0.5

    def text(self):
        return "-6.0 dB"

    def quantized(self):
        return False

    def raw(self):
        return 0.5


def test_reports_of_a_control():
    assert C.value_report(FakeControl()) == {
        "n": 0.5,
        "s": "-6.0 dB",
        "q": False,
        "err": None,
        "r": 0.5,
        "key": "Kick bus/volume",
    }
    assert C.value_report(FakeControl("not in the set")) == {
        "n": None,
        "s": "",
        "q": False,
        "err": "not in the set",
        "r": None,
        "key": "Kick bus/volume",
    }
    assert C.value_message(0, "f1", FakeControl(), True) == {
        "t": "v",
        "page": 0,
        "slot": "f1",
        "n": 0.5,
        "s": "-6.0 dB",
        "r": 0.5,
        "key": "Kick bus/volume",
        "sys": True,
    }
    assert C.inventory_line("Kick bus", "", "mute", "off", "off", "on", True) == "Kick bus\t\tmute\toff\toff\ton\tQ"


def test_pagercore_imports_nothing():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(C.__file__).read_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


def test_the_hardware_table_says_which_minilab_control_does_what():
    import surfaces

    assert len(C.HARDWARE) == 29 and {row[2] for row in C.HARDWARE} == set(C.ROLES) - {"toggle_pad"}
    slots = [row[3] for row in C.HARDWARE if row[2] in ("knob", "fader")]
    switches = [s for s in surfaces.SLOTS if s.startswith("b")]  # flipped on the screen, not on a pad
    assert sorted(slots + switches) == sorted(surfaces.SLOTS)
    assert [row[0] for row in C.hardware_rows("fader")] == list(C.FADER_ELEMENTS)
    pads = C.hardware_rows("page_pad")
    assert [row[3] for row in pads] == list(range(1, 9)) * 2  # bank A and bank B arm the same pages
    assert [row[0] for row in pads] == ["pad_bank_a_raw"] * 8 + ["pad_bank_b_raw"] * 8
    assert C.hardware_rows("knob")[0] == ("encoders_raw", 0, "knob", "k1")
    assert C.hardware_rows("page_encoder") == [("display_encoder", None, "page_encoder", None)]


def test_another_timeline_is_passed_in():
    loops = {"build": (0.0, 32.0), "drop": (32.0, 32.0)}
    assert C.loop_mode(True, 32.0, 32.0, loops) == "drop" and C.loop_mode(True, 64.0, 96.0, loops) == "on"
    assert C.seek_position(500, end=64.0) == pytest.approx(63.99)
    assert C.play_from(64.0, end=64.0) == 0.0 and C.ran_past_end(True, False, 64.0, end=64.0)


# ---- the full map (DESIGN 3b): data and the small decisions it needs --------------------------------------------------


def test_the_pager_still_reads_the_old_table_and_it_is_unchanged():
    assert len(C.HARDWARE) == 29 and C.ROLES == ("knob", "fader", "toggle_pad", "page_pad", "page_encoder")
    assert C.step_page(0, -1, 12) == 11 and C.step_page(11, 1, 12) == 0 and C.step_page(3, 0, 12) is None


def test_every_control_of_the_design_has_a_row_in_base_and_the_map_has_no_two_rows_for_one_place():
    places = [(c, layer) for c, layer, *_ in C.MINILAB_MAP]
    assert len(places) == len(set(places))
    base = {c for c, layer, *_ in C.MINILAB_MAP if layer == "base"}
    assert base >= {f"k{i}" for i in range(1, 9)} | {f"f{i}" for i in range(1, 5)}
    assert base >= {f"a{i}" for i in range(1, 9)} | {f"b{i}" for i in range(1, 9)}
    assert base >= {"data_turn", "data_push", "octave_down", "octave_up", "mod", "bend", "hold", "keys"}
    assert {layer for _, layer, *_ in C.MINILAB_MAP} <= set(C.LAYERS)


def test_every_named_action_in_the_map_is_known():
    named = {arg for _, _, role, arg in C.MINILAB_MAP if role == "action"}
    assert named <= set(C.ACTIONS)
    assert set(C.ACTIONS) <= named | {"transport.stop", "pin.set", "pin.drop", "choice.mark"}  # on the screen


def test_a_control_does_what_its_layer_says_and_shift_falls_back_to_base():
    assert C.row_for("k1", shift=False, tempo=False)[2] == "knob"
    assert C.row_for("k1", shift=True, tempo=False)[2] == "knob_fine"
    assert C.row_for("f1", shift=True, tempo=False)[2] == "fader"  # unchanged with Shift
    assert C.row_for("a3", shift=True, tempo=False) == ("a3", "shift", "action", "hear.pin")
    assert C.row_for("a3", shift=False, tempo=False)[2] == "page_pad"
    assert C.row_for("nothing", shift=False, tempo=False) is None


def test_the_tempo_layer_takes_fader_4_and_pads_7_and_8_as_zpkt_minilab_tempo_did():
    assert C.row_for("f4", False, tempo=True) == ("f4", "tempo", "tempo_fader", None)
    assert C.row_for("a7", False, tempo=True)[3] == 0.5 and C.row_for("a8", False, tempo=True)[3] == 2.0
    assert C.row_for("f3", False, tempo=True)[2] == "fader"  # the other controls are as they were
    assert (
        C.tempo_from_fader(0) == 60 and C.tempo_from_fader(127) == 200 and C.tempo_from_fader(64) == 131
    )  # the script's own formula
    assert C.tempo_scaled(160, 0.5) == 80 and C.tempo_scaled(600, 2) == 999 and C.tempo_scaled(30, 0.5) == 20


@pytest.mark.parametrize(
    ("mode", "driving", "on"), [("auto", True, False), ("auto", False, True), ("on", True, True), ("off", False, False)]
)
def test_the_tempo_layer_is_on_when_the_desk_is_not_driving_unless_told(mode, driving, on):
    assert C.tempo_layer_on(mode, driving) is on


def test_focus_walks_knobs_then_faders_then_switches_and_wraps():
    order = C.focus_order(["b2", "f1", "k10", "k2", "k1", "f3"])
    assert order == ["k1", "k2", "k10", "f1", "f3", "b2"]
    assert C.step_focus(order, "k1", 1) == "k2" and C.step_focus(order, "b2", 1) == "k1"
    assert C.step_focus(order, "k1", -1) == "b2" and C.step_focus(order, None, 1) == "k1"
    assert C.step_focus(order, None, -1) == "b2" and C.step_focus([], None, 1) is None
    assert C.next_group_focus(order, "k2") == "f1" and C.next_group_focus(order, "b2") == "k1"
    assert C.next_group_focus(order, None) == "k1" and C.next_group_focus([], None) is None


def test_pitch_bend_holds_past_a_third_of_its_throw_and_lets_go_near_the_middle():
    assert C.bend_amount(8192) == 0 and C.bend_amount(16383) == pytest.approx(1, abs=1e-3) and C.bend_amount(0) == -1
    assert C.bend_hold(0.5, None) == "pin" and C.bend_hold(-0.5, None) == "ref"
    assert C.bend_hold(0.2, None) is None  # not enough to engage
    assert C.bend_hold(0.2, "pin") == "pin"  # holding: only the middle lets go
    assert C.bend_hold(0.1, "pin") is None
    assert C.bend_hold(0.5, None, "a", "b") == "a"


def test_keys_are_a_25_step_selector_and_the_ends_hold():
    assert C.key_position(48) == 0 and C.key_position(72) == 1 and C.key_position(60) == 0.5
    assert C.key_position(10) == 0 and C.key_position(100) == 1


def test_fine_steps_move_a_tenth_as_far_and_the_first_report_moves_nothing():
    assert C.fine_value(0.5, None, 100) == 0.5
    assert C.fine_value(0.5, 50, 100) == pytest.approx(0.5 + 50 / 127 * 0.1)
    assert C.fine_value(0.99, 0, 127) == 1.0 and C.fine_value(0.01, 127, 0) == 0.0


def test_the_data_knob_is_relative_around_64_and_the_loop_window_cycles():
    assert C.relative_step(65) == 1 and C.relative_step(62) == -2 and C.relative_step(64) == 0
    assert (
        C.loop_window("off", 1) == "build" and C.loop_window("drop", 1) == "off" and C.loop_window("off", -1) == "drop"
    )
    assert C.loop_window("on", 1) == "build"  # a loop the desk did not set counts as the first window


COMPARE_CFG = {
    "pages": [
        {"name": "Buses"},
        {
            "name": "Kick: hotter?",
            "compare": {
                "pads": {"b7": 0, "b8": 1},
                "states": [
                    {"name": "as it is", "writes": [["Kick bus/volume", 0.5], ["Kick bus/mute", False]]},
                    {"name": "hotter", "writes": [["Kick bus/volume", 0.8], ["Kick bus/mute", False]]},
                ],
            },
        },
    ]
}


def test_a_pad_holds_a_compare_state_only_on_the_page_that_has_it():
    assert C.compare_state(COMPARE_CFG, 1, 7) == 0 and C.compare_state(COMPARE_CFG, 1, 8) == 1
    assert C.compare_state(COMPARE_CFG, 1, 1) is None  # that pad arms a page, as always
    assert C.compare_state(COMPARE_CFG, 0, 8) is None and C.compare_state(COMPARE_CFG, 9, 8) is None


def test_the_lit_state_is_the_one_whose_every_value_holds():
    states = COMPARE_CFG["pages"][1]["compare"]["states"]

    def reader(volume, mute=False, known=("Kick bus/volume", "Kick bus/mute")):
        values = {"Kick bus/volume": (volume, 0.0, 1.0, False), "Kick bus/mute": (mute, 0.0, 1.0, True)}
        return lambda key: values[key] if key in known else None

    assert C.lit_state(states, reader(0.5)) == 0 and C.lit_state(states, reader(0.8)) == 1
    assert C.lit_state(states, reader(0.8005)) == 1  # within a thousandth of the range
    assert C.lit_state(states, reader(0.65)) is None  # a knob was turned: no pad is lit
    assert C.lit_state(states, reader(0.8, mute=True)) is None  # every value must hold
    assert C.lit_state(states, reader(0.8, known=("Kick bus/volume",))) is None  # a value the set lacks holds nothing
    assert C.lit_state([{"name": "empty", "writes": []}], reader(0.5)) is None
    assert C.holds(2.0, 2, 0.0, 5.0, True) and not C.holds(3.0, 2, 0.0, 5.0, True)
    assert not C.holds(None, 0.5, 0.0, 1.0, False)
