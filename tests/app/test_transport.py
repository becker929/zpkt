"""The transport: play, pause, stop (back to the start), and what loops: the whole song, its beginning, its peak, or
nothing. On FakeLive, through the bus; none of it is a change to the mix, so none of it is history."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from zpkt.app.bus import Command

SPANS = {"whole": [0.0, 160.0], "build": [0.0, 64.0], "drop": [64.0, 96.0]}


def song(rig):
    return rig.live.song


def test_the_state_says_which_spans_can_loop(rig):
    assert rig.state()["loops"] == SPANS and rig.state()["loop"] == "off"


def test_play_pause_keeps_the_place_and_stop_goes_back_to_the_start(rig):
    before = len(rig.desk.history.entries)
    assert rig.command("transport", {"action": "seek", "beat": 40.0})[0] == 200
    assert rig.command("transport", {"action": "play"})[0] == 200
    assert wait_for(lambda: rig.state()["playing"]) and song(rig).is_playing
    assert rig.command("transport", {"action": "pause"})[0] == 200
    assert wait_for(lambda: not rig.state()["playing"])
    assert song(rig).current_song_time >= 40.0  # paused where it was: Play goes on from here
    assert rig.command("transport", {"action": "play"})[0] == 200 and song(rig).current_song_time >= 40.0
    assert rig.command("transport", {"action": "stop"})[0] == 200
    assert wait_for(lambda: not rig.state()["playing"] and rig.state()["pos"] == 0.0)
    assert song(rig).current_song_time == 0.0 and not song(rig).is_playing
    assert len(rig.desk.history.entries) == before  # the transport is no change to the mix: no row, no undo step
    assert rig.get("/api/history")[1]["can_undo"] is False


@pytest.mark.parametrize("name", ["whole", "build", "drop"])
def test_a_loop_key_sets_lives_loop_to_that_span_and_again_turns_it_off(rig, name):
    assert rig.command("transport", {"action": "loop", "loop": name})[0] == 200
    assert wait_for(lambda: rig.state()["loop"] == name and rig.state()["loop_span"] == SPANS[name])
    s = song(rig)
    assert s.loop and [s.loop_start, s.loop_length] == SPANS[name]
    assert rig.command("transport", {"action": "loop", "loop": "off"})[0] == 200
    assert wait_for(lambda: rig.state()["loop"] == "off") and not s.loop


def test_a_loop_set_while_playing_inside_it_does_not_interrupt_and_outside_it_jumps_to_its_start(rig):
    s = song(rig)
    rig.command("transport", {"action": "seek", "beat": 80.0})
    rig.command("transport", {"action": "play"})
    rig.command("transport", {"action": "loop", "loop": "drop"})  # bar 21 is in the peak: Live plays on
    assert s.is_playing and s.current_song_time >= 80.0
    rig.command("transport", {"action": "loop", "loop": "build"})  # the peak is outside the beginning: to bar 1
    assert s.is_playing and s.current_song_time < 64.0
    rig.command("transport", {"action": "stop"})
    rig.command("transport", {"action": "loop", "loop": "drop"})  # stopped at the start: Play will start at the peak
    assert s.current_song_time == 64.0
    rig.command("transport", {"action": "play"})
    rig.command("transport", {"action": "stop"})  # Stop goes back to the start of what is played
    assert s.current_song_time == 64.0 and wait_for(lambda: rig.state()["pos"] == 64.0)


def test_a_bad_loop_or_action_is_refused_and_an_agent_may_not_move_the_transport(rig):
    assert rig.command("transport", {"action": "loop", "loop": "chorus"})[0] == 400
    assert rig.command("transport", {"action": "rewind"})[0] == 400
    assert rig.desk.bus.submit(Command("transport", "agent", {"action": "stop"}))[0] == 403
