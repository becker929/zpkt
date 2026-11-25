"""The MiniLab's map as a pure function: each control in each layer, with plain views and no I/O."""

from __future__ import annotations

from dataclasses import replace

import pytest

from zpkt.app.minilab import mapper
from zpkt.app.minilab.mapper import ControlView, MapState, PageView, Show, Submit, View
from zpkt.app.minilab.profile import Hit


def view(**over) -> View:
    controls = {
        "k1": ControlView("Kick/vol", 0.5, "-6 dB", "Kick volume"),
        "k2": ControlView("Kick/pan", 0.5, "C", "Kick pan"),
        "f1": ControlView("Hats/vol", 0.3, "-9 dB", "Hats volume"),
        "b1": ControlView("Main/glue", 0.0, "Off", "Glue", True),
    }
    base = View(
        page=1,
        pages=tuple(PageView(f"Page {i}", pad=None if i > 7 else i + 1) for i in range(9)),
        controls=controls,
    )
    return replace(base, **over)


def hit(name, value=127, number=0, shifted=False) -> Hit:
    return Hit(name, value, number, shifted)


def run(*moves, state=None, v=None, tempo=False):
    """Feed moves (Hit, or (Hit, View)) through step; return the last state and every action in order."""
    state, out = state or MapState(), []
    for move in moves:
        h, vw = move if isinstance(move, tuple) else (move, v or view())
        state, actions = mapper.step(state, h, vw, tempo)
        out.extend(actions)
    return state, out


def submits(actions):
    return [a for a in actions if isinstance(a, Submit)]


def test_a_knob_sets_its_control_to_its_place_and_is_a_stream():
    state, actions = run(hit("k1", 127))
    assert actions == [Submit("page.set", {"page": 1, "controls": [{"slot": "k1", "n": 1.0}]}, "set")]
    assert state.sent == {"k1": 1.0}


def test_a_knob_with_no_control_on_the_page_does_nothing():
    assert run(hit("k7", 90))[1] == []


def test_a_fader_picks_up_before_it_moves_anything():
    far = hit("f1", 120)  # the control is at 0.3
    state, actions = run(far)
    assert actions == [] and "f1" not in state.picked
    state, actions = run(hit("f1", 100), hit("f1", 30), state=state)  # it passes the value
    assert "f1" in state.picked and len(submits(actions)) == 1
    assert actions[0].args["controls"][0]["n"] == pytest.approx(30 / 127, abs=1e-5)


def test_a_fader_that_starts_near_the_value_picks_up_at_once_and_a_new_page_makes_it_pick_up_again():
    state, actions = run(hit("f1", 39))  # 39/127 = 0.307, within the pickup distance of 0.3
    assert len(actions) == 1 and "f1" in state.picked
    state, actions = run((hit("f1", 120), view(page=2)), state=state)  # a new page: picked up again from nothing
    assert actions == [] and state.picked == frozenset() and state.page == 2


def test_shift_gives_fine_steps_on_the_knobs_and_the_first_report_moves_nothing():
    state, actions = run(hit("shift", 127), hit("k1", 60))
    assert actions == []
    state, actions = run(hit("k1", 110), state=state)
    n = actions[0].args["controls"][0]["n"]
    assert n == pytest.approx(0.5 + 50 / 127 * 0.1, abs=1e-5)
    state, actions = run(hit("shift", 0), hit("k1", 127), state=state)
    assert actions[0].args["controls"][0]["n"] == 1.0  # Shift let go: absolute again


def test_fine_steps_build_on_what_was_sent_not_on_what_live_has_reported_so_far():
    state, _ = run(hit("shift", 127), hit("k1", 0))
    state, a1 = run(hit("k1", 50), state=state)
    state, a2 = run(hit("k1", 100), state=state)  # Live has not echoed: the view still shows 0.5
    n1, n2 = a1[0].args["controls"][0]["n"], a2[0].args["controls"][0]["n"]
    assert n2 > n1 > 0.5


def test_a_bank_a_pad_arms_a_page_and_pressing_it_again_flips_to_the_layer():
    cfg_pages = (PageView("Buses", 1), PageView("Kick", 2), PageView("Kick EQ", 2))
    v = view(page=0, pages=cfg_pages)
    _, actions = run((hit("a2", 100), v))
    assert actions[0] == Submit("page.arm", {"page": 1}) and isinstance(actions[1], Show)
    _, actions = run((hit("a2", 100), view(page=1, pages=cfg_pages)))
    assert actions[0] == Submit("page.arm", {"page": 2})
    assert run((hit("a2", 0), v))[1] == []  # a release does nothing
    assert run((hit("a6", 100), v))[1] == []  # no page on pad 6


def test_a_bank_b_pad_does_what_the_same_bank_a_pad_does():
    cfg_pages = tuple(PageView(f"P{i}", i + 1) for i in range(8))
    for k in range(1, 9):
        a = run((hit(f"a{k}", 100), view(pages=cfg_pages)))[1]
        b = run((hit(f"b{k}", 100), view(pages=cfg_pages)))[1]
        assert submits(a) == submits(b), k
        a = run(hit("shift", 127), hit(f"a{k}", 100))[1]
        b = run(hit("shift", 127), hit(f"b{k}", 100))[1]
        assert submits(a) == submits(b), k


def test_the_octave_buttons_step_the_pages_and_wrap():
    _, actions = run((hit("octave_up", 127), view(page=8)))
    assert actions[0] == Submit("page.arm", {"page": 0})
    _, actions = run((hit("octave_down", 127), view(page=0)))
    assert actions[0] == Submit("page.arm", {"page": 8})


def test_octave_buttons_with_shift_step_the_loop_window():
    _, actions = run(hit("shift", 127), (hit("octave_up", 127), view(loop="off")))
    assert actions[0] == Submit("transport", {"action": "loop", "loop": "build"})
    _, actions = run(hit("shift", 127), (hit("octave_down", 127), view(loop="off")))
    assert actions[0] == Submit("transport", {"action": "loop", "loop": "drop"})


def test_the_data_knob_moves_focus_through_the_controls_and_shows_the_one_it_lands_on():
    state, actions = run(hit("data_turn", 65))
    assert state.focus == "k1" and actions == [Show("Kick volume", "-6 dB")]
    state, _ = run(hit("data_turn", 65), state=state)
    assert state.focus == "k2"
    state, _ = run(hit("data_turn", 63), hit("data_turn", 63), state=state)
    assert state.focus == "b1"  # back past the first: the last


def test_hold_with_shift_latches_focus_so_the_data_knob_stops_moving_it():
    state, _ = run(hit("data_turn", 65), hit("shift", 127), hit("hold", 127), hit("shift", 0))
    assert state.focus_latched and state.focus == "k1"
    state, actions = run(hit("data_turn", 65), state=state)
    assert state.focus == "k1" and actions == []
    state, actions = run(hit("shift", 127), hit("hold", 127), state=state)
    assert not state.focus_latched and actions[-1] == Show("Focus", "free")


def test_pushing_the_data_knob_resets_the_focused_control_and_does_nothing_with_no_focus():
    assert run(hit("data_push", 127))[1] == []
    state, _ = run(hit("data_turn", 65))
    _, actions = run(hit("data_push", 127), state=state)
    assert actions[0] == Submit("mix.reset", {"keys": ["Kick/vol"]})


def test_the_data_knob_with_shift_scrubs_the_bar_position_and_pushed_goes_to_the_next_group():
    v = view(pos=8.0)
    state, actions = run(hit("shift", 127), (hit("data_turn", 65), v))
    assert actions == [Submit("transport", {"action": "seek", "beat": 12.0}, "seek")]
    _, actions = run((hit("data_turn", 65), v), state=state)  # builds on where it went, before Live reports
    assert actions[0].args["beat"] == 16.0
    _, actions = run(hit("data_turn", 60, shifted=True), (hit("data_turn", 0, shifted=True), view(pos=0.0)))
    assert actions[-1].args["beat"] == 0.0  # never before the start
    state, actions = run(hit("shift", 127), hit("data_push", 127))
    assert state.focus == "k1" and isinstance(actions[0], Show)
    state, _ = run(hit("data_push", 127, shifted=True), state=state)
    assert state.focus == "f1"  # the next group: faders


def test_the_data_knob_sends_its_own_numbers_while_shift_is_held_and_they_count_as_shift():
    _, actions = run((hit("data_turn", 65, shifted=True), view(pos=0.0)))
    assert actions == [Submit("transport", {"action": "seek", "beat": 4.0}, "seek")]


def test_the_mod_strip_moves_the_focused_control_and_the_keys_select_a_place_in_25_steps():
    state, _ = run(hit("data_turn", 65))
    _, actions = run(hit("mod", 127), state=state)
    assert actions[0].args["controls"] == [{"slot": "k1", "n": 1.0}]
    _, actions = run(hit("keys", 90, 60), state=state)
    assert actions[0].args["controls"] == [{"slot": "k1", "n": 0.5}]
    _, actions = run(hit("keys", 90, 72), state=state)
    assert actions[0].args["controls"] == [{"slot": "k1", "n": 1.0}]
    assert run(hit("keys", 0, 60), state=state)[1] == []  # a key up
    assert run(hit("mod", 100))[1] == [] and run(hit("keys", 90, 60))[1] == []  # nothing focused


def test_pitch_bend_up_holds_the_pin_down_holds_the_reference_and_letting_go_brings_now_back():
    state, actions = run(hit("bend", 16000))
    assert submits(actions) == [Submit("monitor.hear", {"hearing": "pin"})]
    assert run(hit("bend", 16100), state=state)[1] == []  # still held: no new command
    state, actions = run(hit("bend", 8192), state=state)
    assert submits(actions) == [Submit("monitor.hear", {"hearing": "now"})]
    state, actions = run(hit("bend", 200))
    assert submits(actions) == [Submit("monitor.hear", {"hearing": "ref"})]


def test_a_trembling_strip_does_not_flicker():
    state, _ = run(hit("bend", 14000))  # engaged
    for tremble in (11000, 12000, 10500):  # past the release point of 0.15
        state, actions = run(hit("bend", tremble), state=state)
        assert actions == [] and state.zone == "pin"


def test_hold_latches_the_compare_so_letting_go_of_the_strip_keeps_pin_or_ref():
    state, _ = run(hit("hold", 127))
    assert state.latched
    state, _ = run(hit("bend", 16000), state=state)
    state, actions = run(hit("bend", 8192), state=state)
    assert actions == [] and state.hearing == "pin"
    state, actions = run(hit("hold", 127), state=state)  # Hold again: unlatch, and Now comes back
    assert not state.latched and submits(actions) == [Submit("monitor.hear", {"hearing": "now"})]


def test_unlatching_while_the_strip_is_still_held_leaves_the_compare_on():
    state, _ = run(hit("hold", 127), hit("bend", 16000))
    state, actions = run(hit("hold", 127), state=state)
    assert submits(actions) == []


def test_the_desk_hearing_something_else_is_what_the_map_believes_unless_it_is_holding():
    state, actions = run((hit("shift", 0), view(hearing="pin")))
    assert state.hearing == "pin"
    _, actions = run((hit("bend", 8192), view(hearing="pin")), state=state)
    assert actions == []  # at rest, nothing held: the desk heard the pin from the web, the strip does not undo it


def test_the_shift_pads_do_transport_hearing_history_and_pins():
    shifted = [
        ("a1", Submit("transport", {"action": "play"})),
        ("a2", None),  # hear now: already hearing now, nothing to ask
        ("a3", Submit("monitor.hear", {"hearing": "pin"})),
        ("a4", Submit("monitor.hear", {"hearing": "ref"})),
        ("a5", Submit("history.undo")),
        ("a6", Submit("history.redo")),
        ("a7", Submit("history.checkpoint")),
        ("a8", Submit("monitor.choose", {"match": False})),
    ]
    for pad, expected in shifted:
        _, actions = run(hit("shift", 127), hit(pad, 100))
        assert (submits(actions) or [None])[0] == expected, pad
    _, actions = run(hit("shift", 127), (hit("a1", 100), view(playing=True)))
    assert submits(actions) == [Submit("transport", {"action": "pause"})]


def test_the_transport_buttons_do_what_lives_own_script_did_once_live_lets_go_of_the_minilab():
    assert run(hit("play", 127))[1] == [Submit("transport", {"action": "play"})]
    assert run((hit("play", 127), view(playing=True)))[1] == [Submit("transport", {"action": "pause"})]
    assert run(hit("stop", 127))[1] == [Submit("transport", {"action": "pause"})]
    assert submits(run((hit("loop", 127), view(loop="build")))[1]) == [
        Submit("transport", {"action": "loop", "loop": "drop"})
    ]
    assert run(hit("play", 0))[1] == []


def test_the_tempo_layer_is_fader_4_in_whole_bpm_and_pads_7_and_8_halve_and_double():
    _, actions = run(hit("f4", 127), tempo=True)
    assert actions[0] == Submit("tempo.set", {"bpm": 200}, "tempo")
    _, actions = run(hit("a7", 100), tempo=True)
    assert actions == [Submit("tempo.scale", {"factor": 0.5})]
    _, actions = run(hit("a8", 100), tempo=True)
    assert actions == [Submit("tempo.scale", {"factor": 2.0})]
    assert run(hit("a7", 0), tempo=True)[1] == []
    _, actions = run((hit("a7", 100), view(page=0)), tempo=False)  # tempo off: pad 7 arms its page
    assert actions[0].kind == "page.arm"


def test_unknown_controls_and_the_shift_button_itself_ask_nothing():
    state, actions = run(hit("tap", 127), hit("rec", 127), hit("nothing", 1))
    assert actions == [] and not state.shift
    state, _ = run(hit("shift", 127))
    assert state.shift
    state, _ = run(hit("shift", 0), state=state)
    assert not state.shift


def test_echoed_values_stop_counting_as_sent_and_a_new_page_forgets_everything_page_bound():
    state, _ = run(hit("k1", 127))
    assert "k1" in state.sent
    state = mapper.sync(state, view(controls={"k1": ControlView("Kick/vol", 1.0)}))
    assert state.sent == {}  # Live reported it back
    state, _ = run(hit("k1", 100))
    state = mapper.sync(state, view(page=5))
    assert state.sent == {} and state.page == 5


def test_a_focus_that_left_the_page_is_dropped():
    state, _ = run(hit("data_turn", 65))
    assert mapper.sync(state, view(controls={})).focus is None


def test_streams_are_merged_latest_per_control_and_one_batch_per_page():
    def knob(slot, n, page=1):
        return Submit("page.set", {"page": page, "controls": [{"slot": slot, "n": n}]}, "set")

    pending: list[Submit] = []
    for a in (knob("k1", 0.1), knob("k2", 0.2), knob("k1", 0.3), knob("k1", 0.4, page=2), knob("k2", 0.5)):
        pending = mapper.merge(pending, a)
    assert len(pending) == 2
    assert pending[0].args["controls"] == [{"slot": "k1", "n": 0.3}, {"slot": "k2", "n": 0.5}]
    assert pending[1].args == {"page": 2, "controls": [{"slot": "k1", "n": 0.4}]}


def test_a_seek_and_a_tempo_keep_only_their_latest_and_a_plain_command_is_not_merged():
    pending = mapper.merge([], Submit("transport", {"action": "seek", "beat": 4}, "seek"))
    pending = mapper.merge(pending, Submit("tempo.set", {"bpm": 120}, "tempo"))
    pending = mapper.merge(pending, Submit("transport", {"action": "seek", "beat": 8}, "seek"))
    assert [p.args for p in pending] == [{"action": "seek", "beat": 8}, {"bpm": 120}]
    with pytest.raises(ValueError, match="stream"):
        mapper.merge([], Submit("history.undo"))
