"""Steps through the MIDI adapter (off by default; the pager in Live is the rig's path): the same layer as the
pager's, from the full map. While the step sequencer has a pattern in hand, pads are its steps, knobs 1-3 its
values, the data knob and the keys choose the sound, and the pad LEDs show the steps.

The map and the feedback are pure; the adapter runs on the app's rig with a fake port. No MIDI port is opened.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.app.conftest import wait_for
from tests.app.test_midi_adapter import Hands
from zpkt.app.bus import Command
from zpkt.app.minilab import feedback, mapper
from zpkt.app.minilab.core import pagercore
from zpkt.app.minilab.mapper import ControlView, MapState, PageView, Show, StepsView, Submit, View
from zpkt.app.minilab.profile import Event, Hit, load_profile
from zpkt.app.minilab.view import steps_view
from zpkt.live import steps

PROFILE = load_profile()
KICK, RIM, SNARE, HAT, OPEN = 36, 37, 38, 42, 46
KIT = [
    {"pitch": p, "name": n}
    for p, n in ((36, "Kick"), (37, "Rim"), (38, "Snare"), (39, "Clap"), (42, "Hat"), (46, "Open"))
]
FOCUS = {
    "track": "Drums",
    "bar": 5,
    "bars": 2,
    "steps_per_bar": 16,
    "view": 0,
    "pitch": KICK,
    "name": "Kick",
    "velocity": 100,
    "length": 1.0,
    "swing": 0.0,
    "steps": [100, 0, 0, 0, 90, *[0] * 27],
    "blocked": False,
    "rev": 3,
}
PRESS = {k: FOCUS[k] for k in mapper.STEP_KEYS}


def view(focus=FOCUS, sounds=KIT, **over) -> View:
    base = View(
        page=1,
        pages=tuple(PageView(f"Page {i}", pad=i + 1) for i in range(8)),
        controls={"k1": ControlView("Kick/vol", 0.5, "-6 dB", "Kick volume"), "k4": ControlView("Hats/vol", 0.3)},
        steps=steps_view(focus, sounds),
    )
    return replace(base, **over)


def run(*hits, state=None, v=None):
    state, out = state or MapState(), []
    for h in hits:
        state, actions = mapper.step(state, h, v or view())
        out.extend(actions)
    return state, out


def submits(actions):
    return [a for a in actions if isinstance(a, Submit)]


# ---- the map --------------------------------------------------------------------------------------------------------


def test_the_layer_is_on_for_a_focus_with_nothing_in_its_way():
    assert steps_view(None) is None and steps_view({**FOCUS, "blocked": True}, KIT) is None
    made = steps_view(FOCUS, KIT)
    assert made == StepsView(FOCUS, tuple((s["pitch"], s["name"]) for s in KIT))
    assert made.pitches() == [36, 37, 38, 39, 42, 46] and made.name_of(42) == "Hat" and made.name_of(50) == "note 50"
    assert steps_view(FOCUS).pitches() is None  # the kit was not read: nothing can be chosen yet


def test_a_pad_flips_its_step_bank_a_1_to_8_and_bank_b_9_to_16_of_the_bar_in_view():
    assert run(Hit("a3", 100, 38))[1] == [Submit("steps.toggle", {**PRESS, "step": 2})]
    assert run(Hit("b2", 100, 45))[1] == [Submit("steps.toggle", {**PRESS, "step": 9})]
    assert run(Hit("a3", 0, 38))[1] == []  # letting go
    second = view({**FOCUS, "view": 1})
    assert run(Hit("b8", 100, 51), v=second)[1] == [Submit("steps.toggle", {**PRESS, "step": 31})]
    # with nothing in hand the same pad arms its page
    assert run(Hit("a3", 100, 38), v=view(None))[1][0] == Submit("page.arm", {"page": 2})


def test_the_layer_wins_over_shift_and_the_tempo_layer_for_the_controls_it_names():
    state = MapState(shift=True)
    assert submits(run(Hit("a5", 100, 40), state=state)[1]) == [Submit("steps.toggle", {**PRESS, "step": 4})]
    assert submits(mapper.step(MapState(), Hit("a7", 100, 42), view(), True)[1])[0].kind == "steps.toggle"
    assert submits(run(Hit("k1", 64, 0), state=state)[1])[0].kind == "steps.focus"  # no fine step of the page's knob


def test_knobs_1_to_3_are_a_stream_of_the_focus_values_and_knob_4_is_the_pages():
    state, actions = run(Hit("k1", 77, 0), Hit("k2", 127, 0), Hit("k3", 64, 0), Hit("k4", 127, 0))
    assert submits(actions) == [
        Submit("steps.focus", {"velocity": 77}, "steps"),
        Submit("steps.focus", {"length": 32.0}, "steps"),  # the pattern's own length is the longest
        Submit("steps.focus", {"swing": 0.38}, "steps"),
        Submit("page.set", {"page": 1, "controls": [{"slot": "k4", "n": 1.0}]}, "set"),
    ]
    assert Show("Velocity", "77") in actions and Show("Length", "32") in actions and Show("Swing", "0.38") in actions
    assert "k1" not in state.sent  # the page's control on knob 1 was not touched
    # a knob that asks for what it asked for last, or for what the focus has, says nothing
    assert run(Hit("k1", 77, 0), state=state)[1] == [] and run(Hit("k1", 100, 0))[1] == []
    pending: list[Submit] = []
    for action in submits(actions)[:3]:
        pending = mapper.merge(pending, action)
    pending = mapper.merge(pending, Submit("steps.focus", {"velocity": 80}, "steps"))
    assert pending == [Submit("steps.focus", {"velocity": 80, "length": 32.0, "swing": 0.38}, "steps")]  # one command
    assert mapper.sync(state, view(None)).step_knobs == {}  # the layer ended: nothing is remembered


def test_the_data_knob_walks_the_sounds_from_the_one_it_last_asked_for():
    state, actions = run(Hit("data_turn", 65, 0))
    assert actions == [Submit("steps.focus", {"pitch": RIM}, "steps"), Show("Sound", "Rim")]
    state, actions = run(Hit("data_turn", 65, 0), state=state)  # before the desk shows the rim
    assert submits(actions) == [Submit("steps.focus", {"pitch": SNARE}, "steps")]
    shown = view({**FOCUS, "pitch": SNARE})
    state, actions = run(Hit("data_turn", 63, 0), state=state, v=shown)  # the desk shows the snare: on from there
    assert submits(actions) == [Submit("steps.focus", {"pitch": RIM}, "steps")]
    assert submits(run(Hit("data_turn", 63, 0))[1]) == [Submit("steps.focus", {"pitch": OPEN}, "steps")]  # wraps
    assert run(Hit("data_turn", 64, 0))[1] == []
    assert run(Hit("data_turn", 65, 0), v=view(sounds=None))[1] == []  # the kit is not known: nothing is chosen
    elsewhere = view({**FOCUS, "pitch": HAT})  # the page chose the hat meanwhile: the turn goes on from the hat
    assert submits(run(Hit("data_turn", 65, 0), state=state, v=elsewhere)[1])[0].args == {"pitch": OPEN}
    with_focus = replace(MapState(), focus="k1")
    assert run(Hit("data_push", 127, 0), state=with_focus)[1][0] == Submit(
        "mix.reset", {"keys": ["Kick/vol"]}
    )  # a push: as it was


def test_a_key_that_is_one_of_the_kits_sounds_chooses_it():
    assert run(Hit("keys", 90, SNARE))[1] == [Submit("steps.focus", {"pitch": SNARE}), Show("Sound", "Snare")]
    assert run(Hit("keys", 90, 40))[1] == []  # no sound of the kit: and no control of the page moves either
    assert run(Hit("keys", 0, SNARE))[1] == [] and run(Hit("keys", 90, KICK))[1] == []  # a key up; the sound in hand
    assert submits(run(Hit("keys", 90, 61), v=view(sounds=[]))[1]) == [Submit("steps.focus", {"pitch": 61})]  # no kit
    focused = replace(MapState(), focus="k1")
    assert run(Hit("keys", 90, 60), state=focused, v=view(None))[1][0].kind == "page.set"  # no layer: as it was


def test_in_the_layer_a_key_in_any_octave_is_a_key():
    assert PROFILE.match(Event("note", 1, SNARE, 90)) is None  # below the 25 keys the profile names
    assert PROFILE.key(Event("note", 1, SNARE, 90)) == Hit("keys", 90, SNARE)
    assert PROFILE.key(Event("note", 10, SNARE, 90)) is None  # a pad's note is a pad
    assert PROFILE.key(Event("cc", 1, 28, 65)) is None


# ---- what the MiniLab is told back ------------------------------------------------------------------------------------


def test_the_pads_show_the_steps_and_knobs_1_to_3_stand_at_the_values_and_the_display_names_the_sound():
    core = pagercore()
    leds = feedback.leds(PROFILE, view())

    def colour(target):
        return tuple(leds[target][-4:-1])

    assert len(leds) == 16
    assert [name for name in leds if colour(name) == core.PAD_LIT] == ["led:a1", "led:a5"]
    assert all(colour(name) == feedback.OFF for name in leds if name not in ("led:a1", "led:a5"))
    rings = feedback.rings(PROFILE, view({**FOCUS, "velocity": 90, "length": 2.0, "swing": 0.3}))
    places = [rings[f"ring:k{k}"][-2] for k in (1, 2, 3)]
    assert [core.step_knob_value(w, p, 32) for w, p in zip(("velocity", "length", "swing"), places, strict=True)] == [
        90,
        2.0,
        0.3,
    ]
    assert rings["ring:k4"][-2] == round(127 * 0.3)  # the page's knob 4, as always
    shown = feedback.page_display(PROFILE, view())["display"]
    assert bytes(shown[17:21]) == b"Kick" and b"Drums bar 5" in bytes(shown)
    # with nothing in hand the pads and the display are the page's
    assert tuple(feedback.leds(PROFILE, view(None))["led:a2"][-4:-1]) == feedback.ARMED
    assert b"Page 1" in bytes(feedback.page_display(PROFILE, view(None))["display"])


# ---- the adapter on the rig -------------------------------------------------------------------------------------------


@pytest.fixture()
def held(rig, monkeypatch):
    """The rig with a drum track and the kick of bar 5 (steps 1 and 13 on) in hand."""
    monkeypatch.setattr(steps.time, "sleep", lambda s: None)
    span = {"track": "Drums", "bar": 5, "bars": 1}
    for kind, args in [
        ("steps.new_track", {"name": "Drums", "kit": "909 Core Kit"}),
        ("steps.toggle", {**span, "pitch": KICK, "step": 0}),
        ("steps.toggle", {**span, "pitch": KICK, "step": 12}),
        ("steps.focus", {**span, "pitch": KICK}),
    ]:
        assert rig.desk.bus.submit(Command(kind, "you", args))[0] == 200
    return rig


PAD_IDS = (*range(52, 60), *range(68, 76))  # the pads' LED ids: a1-a8, then b1-b8


def leds_now(hands):
    """Each pad's colour as last sent: {LED id: (r, g, b)}."""
    return {m[9]: tuple(m[10:13]) for m in hands.port.sent() if m[6:9] == [2, 2, 22]}


def lit_pads(hands):
    """The step pads (0-15) lit as a step that is on."""
    core = pagercore()
    return sorted(PAD_IDS.index(k) for k, colour in leds_now(hands).items() if colour == core.PAD_LIT)


def focus_of(rig):
    return rig.desk.steps_now()


def test_the_adapter_shows_the_steps_and_a_pad_flips_one_as_the_minilab(held):
    rig = held
    with Hands(rig) as hands:
        assert wait_for(lambda: lit_pads(hands) == [0, 12])
        shows = [m for m in hands.port.sent() if m[6:9] == [4, 2, 96]]
        assert bytes(shows[-1][17:21]) == b"Kick"
        page = rig.state()["page"]
        hands.pad("a3")
        assert wait_for(lambda: focus_of(rig)["steps"][2] == 100)
        hands.pad("b2")
        assert wait_for(lambda: focus_of(rig)["steps"][9] == 100)
        assert wait_for(lambda: lit_pads(hands) == [0, 2, 9, 12])
        assert rig.state()["page"] == page and not hands.adapter.refused
        toggles = [e for e in rig.desk.bus.log if e["kind"] == "steps.toggle" and e["who"] == "minilab"]
        assert len(toggles) == 2 and all(e["status"] == 200 for e in toggles)
        rig.desk.bus.submit(Command("steps.focus", "you", {}))  # nothing in hand: the pads are the desk's again
        back = {52: feedback.ARMED, 53: feedback.AVAILABLE}  # a1 arms the armed page, a2 another
        assert wait_for(lambda: {k: leds_now(hands)[k] for k in back} == back)
        hands.pad("a2")
        assert wait_for(lambda: rig.state()["page"] == 2)


def test_the_adapters_knobs_keys_and_data_knob_set_the_focus(held):
    rig = held
    with Hands(rig) as hands:
        hands.settle()
        hands.knob("k1", 77)
        hands.knob("k3", 64)
        assert wait_for(lambda: (focus_of(rig)["velocity"], focus_of(rig)["swing"]) == (77, 0.38))
        hands.knob("k2", 127)
        assert wait_for(lambda: focus_of(rig)["length"] == 16.0)
        hands.key(SNARE)  # two octaves below the keys the profile names: a sound of the kit all the same
        assert wait_for(lambda: focus_of(rig)["pitch"] == SNARE)
        hands.key(40)  # no sound of the kit
        hands.settle()
        assert focus_of(rig)["pitch"] == SNARE
        hands.cc(28, 65)  # the data knob, one detent on
        assert wait_for(lambda: focus_of(rig)["pitch"] == 39) and focus_of(rig)["name"] == "Clap"
        assert not hands.adapter.refused
        asked = [e for e in rig.desk.bus.log if e["kind"] == "steps.focus" and e["who"] == "minilab"]
        assert asked and all(e["status"] == 200 for e in asked)
        assert len([e for e in rig.desk.bus.log if e["kind"] == "steps.sounds"]) == 1  # the kit was read once
