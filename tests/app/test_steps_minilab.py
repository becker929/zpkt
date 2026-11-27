"""Steps on the MiniLab, through the app: the pager's steps layer on the fake controller, the app's hand
(zpkt.app.steps_minilab) between it and the bus, and FakeLive behind. While the sequencer has a pattern in hand the
pads are its steps: a press is steps.toggle as the minilab, the lit pads are the steps that are on, knobs 1-3 and
the data knob set the focus, and the screen gets the same {"t": "steps"} message as for any other hand.

Nothing here reaches the running desk, a MiniLab or the real Live.
"""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from zpkt.app import steps_minilab
from zpkt.app.bus import Command
from zpkt.live import steps

KICK, RIM, SNARE, HAT, OPEN = 36, 37, 38, 42, 46
SPAN = {"track": "Drums", "bar": 5, "bars": 1}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(steps.time, "sleep", lambda s: None)


def ask(rig, kind, args=None, who="you"):
    return rig.desk.bus.submit(Command(kind, who, args or {}))


def settle(rig):
    """Wait until the hand has done everything it was given (the pager is told on the hand's own thread)."""
    assert wait_for(rig.desk.steps_hand.idle)


def pads(rig):
    return [*rig.minilab.elements.pad_bank_a_raw, *rig.minilab.elements.pad_bank_b_raw]


def lit(rig):
    """The step pads (0-15) whose light is on."""
    return [k for k, pad in enumerate(pads(rig)) if pad.lit]


def press(rig, pad):
    pads(rig)[pad].receive(110)
    pads(rig)[pad].receive(0)


def focus_of(rig):
    return rig.desk.steps_now()


def notes(rig):
    track = rig.track("Drums")
    return sorted((c.start_time, n.pitch, n.start_time, n.velocity) for c in track.arrangement_clips for n in c._notes)


def by_minilab(rig, kind):
    """The commands of that kind the MiniLab sent, once the hand is done with all it was given: {"args", "status"}
    each (the `commands` fixture records them when they have answered)."""
    settle(rig)
    return [e for e in rig.sent_commands if e["kind"] == kind and e["who"] == "minilab"]


@pytest.fixture(autouse=True)
def commands(rig):
    """Every command the bus gets, with its arguments and the status it answered."""
    submit = rig.desk.bus.submit
    rig.sent_commands = []

    def recording(cmd):
        reply = submit(cmd)
        rig.sent_commands.append({"kind": cmd.kind, "who": cmd.who, "args": dict(cmd.args), "status": reply[0]})
        return reply

    rig.desk.bus.submit = recording
    return rig.sent_commands


def heard(q, kind="steps"):
    return [m for m in list(q.queue) if m.get("t") == kind]


@pytest.fixture()
def drums(rig):
    """The rig with a drum track and two steps of the kick on in bar 5; nothing in hand yet."""
    assert ask(rig, "steps.new_track", {"name": "Drums", "kit": "909 Core Kit"})[0] == 200
    ask(rig, "steps.toggle", {**SPAN, "pitch": KICK, "step": 0})
    ask(rig, "steps.toggle", {**SPAN, "pitch": KICK, "step": 12, "velocity": 90})
    return rig


@pytest.fixture()
def held(drums):
    """... and the kick of bar 5 in hand."""
    assert ask(drums, "steps.focus", {**SPAN, "pitch": KICK})[0] == 200
    settle(drums)
    return drums


# ---- the layer follows the focus ---------------------------------------------------------------------------------


def test_the_pads_are_steps_exactly_while_the_sequencer_has_something_in_hand(drums):
    rig = drums
    assert lit(rig) == [] and rig.desk.steps_hand.calls == 0  # no focus: the pager was told nothing
    ask(rig, "steps.focus", {**SPAN, "pitch": KICK})
    assert wait_for(lambda: lit(rig) == [0, 12])  # bank A pad 1, bank B pad 5
    page = rig.state()["page"]
    press(rig, 1)
    assert wait_for(lambda: focus_of(rig)["steps"][1] == 100) and rig.state()["page"] == page  # no page was armed
    ask(rig, "steps.focus", {})
    assert wait_for(lambda: lit(rig) == [])
    press(rig, 1)  # pad A2 arms its page again
    assert wait_for(lambda: rig.state()["page"] != page)
    assert focus_of(rig) is None and len(by_minilab(rig, "steps.toggle")) == 1


def test_a_focus_with_clips_in_its_way_is_no_layer(drums):
    rig = drums
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(32.0, 8.0)\nresult = 1")
    got = ask(rig, "steps.focus", {"track": "Drums", "bar": 9, "bars": 1, "pitch": KICK})[1]["focus"]
    assert got["blocked"] is True
    settle(rig)
    assert rig.desk.steps_hand.calls == 0 and lit(rig) == []
    page = rig.state()["page"]
    press(rig, 1)
    assert wait_for(lambda: rig.state()["page"] != page)  # the pads are the desk's
    assert by_minilab(rig, "steps.toggle") == []


def test_the_pager_is_told_once_for_a_change_it_shows_and_not_at_all_for_one_it_does_not(held):
    rig = held
    hand = rig.desk.steps_hand

    def told(kind, args, calls):
        """Do a command; the pager must have been told `calls` more times once the hand is done."""
        before, rev = hand.calls, (focus_of(rig) or {}).get("rev")
        assert ask(rig, kind, args)[0] == 200
        settle(rig)
        assert hand.calls == before + calls, (kind, args)
        return rev, (focus_of(rig) or {}).get("rev")

    assert hand.calls == 1  # the focus came: one call
    assert told("steps.focus", {"velocity": 90}, 1) == (1, 2)  # a knob's value: shown
    assert told("steps.focus", {"name": "Kik"}, 0) == (2, 3)  # a new rev that shows nothing new
    assert told("steps.toggle", {**SPAN, "pitch": HAT, "step": 3}, 0)[1] == 4  # another sound's step
    assert told("steps.toggle", {**SPAN, "pitch": KICK, "step": 3}, 1)[1] == 5  # a step of the sound in hand
    assert lit(rig) == [0, 3, 12]
    assert told("steps.focus", {"pitch": HAT}, 1)[1] == 6 and lit(rig) == [3]
    assert told("steps.focus", {}, 1)[1] is None and lit(rig) == []
    assert told("steps.focus", {}, 0)[1] is None  # nothing in hand, said twice
    code = [c.code for c in rig.live.calls if "m.DESK.steps_layer" in c.code]
    assert len(code) == hand.calls == 5 and "steps_layer(None, False)" in code[-1]


def test_a_bar_out_of_view_changes_no_light_and_the_view_chooses_the_bar(drums):
    rig = drums
    two = {"track": "Drums", "bar": 9, "bars": 2}
    ask(rig, "steps.toggle", {**two, "pitch": KICK, "step": 4})
    ask(rig, "steps.focus", {**two, "pitch": KICK})
    assert wait_for(lambda: lit(rig) == [4])
    before = rig.desk.steps_hand.calls
    ask(rig, "steps.toggle", {**two, "pitch": KICK, "step": 18})  # in the second bar: not in view
    settle(rig)
    assert rig.desk.steps_hand.calls == before and lit(rig) == [4]
    ask(rig, "steps.focus", {"view": 1})
    assert wait_for(lambda: lit(rig) == [2])
    press(rig, 9)  # bank B pad 2 of the second bar: step 16 + 9
    assert wait_for(lambda: focus_of(rig)["steps"][25] == 100)
    assert by_minilab(rig, "steps.toggle")[-1]["args"]["step"] == 25


# ---- the pads -------------------------------------------------------------------------------------------------------


def test_a_pad_in_each_bank_flips_its_step_as_the_minilab_and_every_page_hears_it(held):
    rig = held
    ask(rig, "steps.focus", {"velocity": 110, "length": 2.0})
    shell, old_page = rig.desk.subscribe(app=True), rig.desk.subscribe()
    press(rig, 2)  # bank A pad 3: step 3
    assert wait_for(lambda: focus_of(rig)["steps"][2] == 110)
    press(rig, 9)  # bank B pad 2: step 10
    assert wait_for(lambda: focus_of(rig)["steps"][9] == 110)
    toggles = by_minilab(rig, "steps.toggle")
    assert [t["args"]["step"] for t in toggles] == [2, 9] and all(t["status"] == 200 for t in toggles)
    flip = {"steps_per_bar": 16, "pitch": KICK, "step": 2, "velocity": 110, "length": 2.0, "swing": 0.0}
    assert toggles[0]["args"] == {**SPAN, **flip}
    assert (16.0, KICK, 0.5, 110) in notes(rig) and (16.0, KICK, 2.25, 110) in notes(rig)  # in Live's clip
    # the screen follows the controller: the usual message, to the shell and the old page alike
    edits = [m for m in heard(shell) if m.get("edit")]
    assert [m["edit"] for m in edits] == [{"track": "Drums", "bar": 5, "bars": 1, "what": "toggle"}] * 2
    assert edits[-1]["focus"] == focus_of(rig) and edits[-1]["focus"]["steps"][9] == 110
    assert [m for m in heard(old_page) if m.get("edit")] == edits
    assert not heard(shell, "step")  # the pager's own message is not a page's business
    settle(rig)
    assert lit(rig) == [0, 2, 9, 12]
    press(rig, 0)  # a step that is on goes off
    assert wait_for(lambda: focus_of(rig)["steps"][0] == 0)
    settle(rig)
    assert lit(rig) == [2, 9, 12] and (16.0, KICK, 0.0, 100) not in notes(rig)


def test_a_press_live_refuses_puts_the_pads_light_back(held):
    rig = held
    rig.desk.bus.guard.forget()
    rig.desk.bus.guard.open_set = lambda: "Another set"  # Live has another set open: every move is refused
    before = notes(rig)
    pads(rig)[5].receive(110)
    assert pads(rig)[5].lit  # under the finger, at once
    pads(rig)[5].receive(0)
    assert wait_for(lambda: by_minilab(rig, "steps.toggle") and not pads(rig)[5].lit)
    assert by_minilab(rig, "steps.toggle")[-1]["status"] == 409 and notes(rig) == before
    settle(rig)
    assert lit(rig) == [0, 12]


def test_a_press_is_a_history_row_by_the_minilab_and_undo_puts_the_light_out(held):
    rig = held
    press(rig, 5)
    assert wait_for(lambda: focus_of(rig)["steps"][5] == 100)
    settle(rig)
    assert lit(rig) == [0, 5, 12]
    last = rig.desk.history.entries[-1]
    assert (last["k"], last["who"]) == ("steps", "minilab")
    assert ask(rig, "history.undo")[0] == 200
    assert wait_for(lambda: lit(rig) == [0, 12]) and focus_of(rig)["steps"][5] == 0


def test_a_pager_that_starts_again_is_told_the_focus(held):
    rig = held
    for pad in pads(rig):
        pad.colour = None
    rig.desk.restart_pager()
    assert lit(rig) == [0, 12]  # told in the restart itself
    press(rig, 4)
    assert wait_for(lambda: focus_of(rig)["steps"][4] == 100)


# ---- the knobs ------------------------------------------------------------------------------------------------------


def test_knobs_1_to_3_set_the_velocity_length_and_swing_of_the_focus_and_knob_4_is_the_pages(held):
    rig = held
    knobs = rig.minilab.elements.encoders_raw
    key = rig.state()["values"]["0:k1"]["key"]
    before = rig.state()["values"]["0:k1"]["r"]
    knobs[0].receive(77)
    assert wait_for(lambda: focus_of(rig)["velocity"] == 77)
    knobs[1].receive(127)
    assert wait_for(lambda: focus_of(rig)["length"] == 16.0)  # the pattern's own length
    knobs[2].receive(64)
    assert wait_for(lambda: focus_of(rig)["swing"] == 0.38)
    assert all(e["status"] == 200 for e in by_minilab(rig, "steps.focus"))
    assert rig.state()["values"]["0:k1"]["r"] == before  # the page's control on knob 1 did not move
    assert not [e for e in rig.desk.history.entries if e.get("key") == key]
    press(rig, 6)  # a new step gets those values
    assert wait_for(lambda: focus_of(rig)["steps"][6] == 77)
    assert [n for n in notes(rig) if n[3] == 77]  # in Live's clip (where swing puts it is zpkt.live.steps' own)
    k4 = rig.state()["values"]["0:k4"]["key"]
    knobs[3].receive(127)
    assert wait_for(lambda: rig.state()["values"]["0:k4"]["n"] == pytest.approx(1.0)) and k4


def test_a_run_of_turns_becomes_one_command_with_the_latest_of_each(held):
    rig = held
    before = len(by_minilab(rig, "steps.focus"))
    rig.desk.steps_hand.work(
        [
            {"t": "step_knob", "what": "velocity", "value": 10},
            {"t": "step_knob", "what": "velocity", "value": 20},
            {"t": "step_knob", "what": "length", "value": 2.0},
            {"t": "step_sound", "turn": 1},
            {"t": "step_sound", "turn": 1},
            {"t": "step_knob", "what": "velocity", "value": 30},
        ]
    )
    sent = by_minilab(rig, "steps.focus")[before:]
    assert [e["args"] for e in sent] == [{"velocity": 30, "length": 2.0, "pitch": SNARE}]  # two sounds on from the kick
    now = focus_of(rig)
    assert (now["velocity"], now["length"], now["pitch"], now["name"]) == (30, 2.0, SNARE, "Snare")
    # a press between turns keeps the order: what was turned before it is set before the step is flipped
    rig.desk.steps_hand.work(
        [{"t": "step_knob", "what": "velocity", "value": 64}, {"t": "step", "pad": 1}, {"t": "step_sound", "turn": -1}]
    )
    assert focus_of(rig)["pitch"] == RIM and (16.0, SNARE, 0.25, 64) in notes(rig)


def test_what_the_hand_is_given_with_nothing_in_hand_does_nothing(drums):
    rig = drums
    before = len(rig.desk.bus.log)
    rig.desk.steps_hand.work(
        [
            {"t": "step", "pad": 3},
            {"t": "step_knob", "what": "velocity", "value": 64},
            {"t": "step_sound", "turn": 1},
            {"t": "step_sound", "pitch": SNARE},
        ]
    )
    assert len(rig.desk.bus.log) == before and focus_of(rig) is None


# ---- the sound: the data knob, and the pad a key selects in Live -----------------------------------------------------


def test_the_data_knob_walks_the_kits_sounds_in_order_and_wraps(held):
    rig = held
    turn = rig.minilab.elements.display_encoder
    page = rig.state()["page"]
    turn.receive(65)
    assert wait_for(lambda: focus_of(rig)["pitch"] == RIM) and focus_of(rig)["name"] == "Rim"
    turn.receive(63)
    turn.receive(63)
    assert wait_for(lambda: focus_of(rig)["pitch"] == OPEN)  # back past the kick: the last sound
    assert rig.state()["page"] == page  # it armed no page
    settle(rig)
    asked = [c for c in rig.live.calls if "pad_sounds(_t" in c.code.splitlines()[-1]]
    assert len(asked) == 1  # the kit was read once
    ask(rig, "steps.focus", {})
    settle(rig)
    turn.receive(65)
    assert wait_for(lambda: rig.state()["page"] == page + 1)  # nothing in hand: it steps through pages again


SELECT = "r = find_track('Drums').devices[0]\nr.view.selected_drum_pad = r.drum_pads[{note}]\nresult = 1"


def test_the_pad_selected_in_lives_drum_rack_chooses_the_sound_when_it_is_one_of_the_kits(held):
    rig = held
    rig.conn.run(SELECT.format(note=SNARE))  # as Live does when a key plays the snare (GUESS: Auto Select)
    assert wait_for(lambda: focus_of(rig)["pitch"] == SNARE) and focus_of(rig)["name"] == "Snare"
    assert by_minilab(rig, "steps.focus")[-1]["args"] == {"pitch": SNARE}
    settle(rig)
    assert lit(rig) == []  # the snare has no steps: the pads follow the sound
    rig.conn.run(SELECT.format(note=40))  # an empty pad: the pager does not report it
    rig.send({"t": "step_sound", "pitch": 41})  # and a note that is no sound of the kit is not taken from anyone
    rig.send({"t": "step_sound", "pitch": KICK})
    assert wait_for(lambda: focus_of(rig)["pitch"] == KICK)
    assert [e["args"] for e in by_minilab(rig, "steps.focus")] == [{"pitch": SNARE}, {"pitch": KICK}]
    assert wait_for(lambda: lit(rig) == [0, 12])


def test_the_pagers_steps_messages_are_the_hands_and_never_the_states(held):
    rig = held
    assert set(steps_minilab.KINDS) == {"step", "step_knob", "step_sound"}
    state = rig.state()
    shell = rig.desk.subscribe(app=True)
    rig.send({"t": "step_knob", "what": "velocity", "value": 55})
    assert wait_for(lambda: focus_of(rig)["velocity"] == 55)
    after = rig.state()
    assert {k: v for k, v in after.items() if k != "steps"} == {k: v for k, v in state.items() if k != "steps"}
    assert [m["t"] for m in list(shell.queue)] == ["steps"]  # the focus, and not the pager's message
    rig.send({"t": "step_knob", "what": "pitch", "value": 3})  # not a knob of the layer: dropped as a bad message
    rig.send({"t": "step", "pad": 99})
    settle(rig)
    assert focus_of(rig)["velocity"] == 55 and by_minilab(rig, "steps.toggle") == []
