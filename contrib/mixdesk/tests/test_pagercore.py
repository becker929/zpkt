"""pagercore.py: the pager's decisions, without Live (pager.py loads the same file inside Live)."""

from __future__ import annotations

import pagercore as C
import pytest

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

    assert len(C.HARDWARE) == 29 and {row[2] for row in C.HARDWARE} == set(C.ROLES)
    slots = [row[3] for row in C.HARDWARE if row[2] in ("knob", "fader", "toggle_pad")]
    assert sorted(slots) == sorted(surfaces.SLOTS)  # every slot a surface may fill has a control, and only those
    assert [row[0] for row in C.hardware_rows("fader")] == list(C.FADER_ELEMENTS)
    assert [row[3] for row in C.hardware_rows("page_pad")] == list(range(1, 9))
    assert C.hardware_rows("knob")[0] == ("encoders_raw", 0, "knob", "k1")
    assert C.hardware_rows("page_encoder") == [("display_encoder", None, "page_encoder", None)]


def test_another_timeline_is_passed_in():
    loops = {"build": (0.0, 32.0), "drop": (32.0, 32.0)}
    assert C.loop_mode(True, 32.0, 32.0, loops) == "drop" and C.loop_mode(True, 64.0, 96.0, loops) == "on"
    assert C.seek_position(500, end=64.0) == pytest.approx(63.99)
    assert C.play_from(64.0, end=64.0) == 0.0 and C.ran_past_end(True, False, 64.0, end=64.0)
