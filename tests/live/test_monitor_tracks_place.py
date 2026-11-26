"""Where a switch to or from a reference puts the playhead (zpkt.live.monitor_tracks.placed_beat)."""

import pytest

from zpkt.live.monitor_tracks import Place, placed_beat

MIX = {"origin": 64.0, "bpm": None, "span": 96.0}  # the drop of a 160 BPM set: 24 bars
REF = {"origin": 64.0, "bpm": 155.0, "bars": 19.0}  # a reference at 155 BPM: 19 of its own bars from the drop


def test_the_same_bar_and_place_in_the_bar_is_found_on_the_references_own_bars():
    to, span = placed_beat(64.0 + 5 * 4.0 + 1.0, 4.0, 160.0, Place(src=MIX, dst=REF))  # bar 6, a beat in
    bar = 4.0 * 160.0 / 155.0
    assert to == pytest.approx(64.0 + 5.25 * bar) and span == pytest.approx(19 * bar)


def test_bars_past_the_references_end_wrap_into_it():
    to, _ = placed_beat(64.0 + 21 * 4.0 + 2.0, 4.0, 160.0, Place(src=MIX, dst=REF))  # bar 22 of the drop
    assert to == pytest.approx(64.0 + 2.5 * 4.0 * 160.0 / 155.0)


def test_and_back_to_the_mix_is_the_reverse():
    there, _ = placed_beat(77.5, 4.0, 160.0, Place(src=MIX, dst=REF))
    back, span = placed_beat(there, 4.0, 160.0, Place(src=REF, dst=MIX))
    assert back == pytest.approx(77.5) and span == 96.0


def test_a_grid_with_no_end_does_not_wrap_and_never_goes_before_its_origin():
    open_grid = {"origin": 64.0, "bpm": None}
    assert placed_beat(10.0, 4.0, 160.0, Place(src=MIX, dst=open_grid)) == (64.0, None)
    assert placed_beat(300.0, 4.0, 160.0, Place(src=open_grid, dst=open_grid)) == (300.0, None)
