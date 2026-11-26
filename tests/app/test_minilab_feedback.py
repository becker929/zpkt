"""What the MiniLab is told back (rings, LEDs, the page's name), and the View built from the desk's state."""

from __future__ import annotations

from zpkt.app.minilab import feedback
from zpkt.app.minilab.mapper import ControlView, PageView, View
from zpkt.app.minilab.profile import load_profile
from zpkt.app.minilab.view import controls_of, pages_from_cfg, view_from

PROFILE = load_profile()


def sample_view() -> View:
    return View(
        page=0,
        pages=(PageView("Buses", 1), PageView("Match", 1), PageView("Kick", 2)),
        controls={
            "k1": ControlView("a", 1.0),
            "k3": ControlView("c", 0.25),
            "b1": ControlView("m", 1.0),
            "b2": ControlView("n", 0.0),
        },
    )


def test_each_ring_is_at_its_controls_place_and_a_knob_with_no_control_is_at_zero():
    rings = feedback.rings(PROFILE, sample_view())
    assert len(rings) == 8
    assert rings["ring:k1"][-2] == 127 and rings["ring:k3"][-2] == round(127 * 0.25) and rings["ring:k2"][-2] == 0


def test_bank_a_shows_the_armed_pad_and_the_pads_that_have_pages_and_bank_b_the_switches():
    leds = feedback.leds(PROFILE, sample_view())

    def colour(target):
        return tuple(leds[target][-4:-1])

    assert colour("led:a1") == feedback.ARMED and colour("led:a2") == feedback.AVAILABLE
    assert colour("led:a3") == feedback.OFF  # no page on pad 3
    assert colour("led:b1") == feedback.ON and colour("led:b2") == feedback.IDLE and colour("led:b3") == feedback.OFF


def test_rings_and_the_pages_name_go_out_only_when_a_page_was_armed():
    steady = feedback.feedback(PROFILE, sample_view(), page_changed=False)
    assert all(k.startswith("led:") for k in steady)
    changed = feedback.feedback(PROFILE, sample_view(), page_changed=True)
    assert "display" in changed and sum(k.startswith("ring:") for k in changed) == 8
    assert feedback.page_display(PROFILE, View()) == {}


def test_the_view_is_made_from_the_desks_state_and_leaves_out_controls_that_do_not_work():
    values = {
        "0:k1": {"key": "Kick/vol", "n": 0.5, "s": "-6 dB", "q": False},
        "0:k2": {"key": "Gone/vol", "n": None, "s": "", "err": "no such track"},
        "0:k3": {"key": None, "n": 0.1},
        "1:k1": {"key": "Other/vol", "n": 0.9},
    }
    controls = controls_of(values, 0, {"Kick/vol": "Kick volume"})
    assert list(controls) == ["k1"] and controls["k1"].label == "Kick volume" and controls["k1"].text == "-6 dB"
    state = {"page": 1, "values": values, "playing": True, "pos": 12.5, "loop": "drop", "match": False}
    view = view_from(state, pages_from_cfg([{"name": "A", "pad": 3}, {"name": "B"}]), {}, "pin")
    assert view.page == 1 and view.playing and view.pos == 12.5 and view.loop == "drop" and not view.match
    assert view.hearing == "pin" and view.driving and list(view.controls) == ["k1"]
    assert view.pages == (PageView("A", 3), PageView("B", None))
    assert view.cfg() == {"pages": [{"name": "A", "pad": 3}, {"name": "B"}]}
    assert not view_from({**state, "values": {}}, (), {}).driving  # the pager reports nothing: the desk is not driving


COMPARE = {
    "pads": {"b7": 0, "b8": 1},
    "states": [{"name": "as it is", "writes": [["Kick/vol", 0.5]]}, {"name": "hotter", "writes": [["Kick/vol", 0.8]]}],
    "ranges": {"Kick/vol": [0.0, 1.0, False]},
}


def test_the_lit_pad_is_worked_out_from_the_values_and_the_pads_show_it_on_both_banks():
    from zpkt.app.minilab.view import lit_pad

    values = {"0:k1": {"key": "Kick/vol", "n": 0.8, "r": 0.8}}
    assert lit_pad(COMPARE, values) == "b8"
    assert lit_pad(COMPARE, {"0:k1": {"key": "Kick/vol", "n": 0.5, "r": 0.5}}) == "b7"
    assert lit_pad(COMPARE, {"0:k1": {"key": "Kick/vol", "n": 0.65, "r": 0.65}}) is None  # a knob was turned
    assert lit_pad(COMPARE, {}) is None and lit_pad(None, values) is None
    (page,) = pages_from_cfg([{"name": "Kick: hotter?", "compare": COMPARE}])
    assert page.compare == {"b7": 0, "b8": 1}
    state = {"page": 0, "values": values, "playing": False, "pos": 0.0, "loop": "off", "match": True}
    view = view_from(state, (page,), {}, compare=COMPARE)
    assert view.lit == "b8"
    leds = feedback.leds(PROFILE, view)
    colour = lambda target: tuple(leds[target][-4:-1])  # noqa: E731
    assert colour("led:b8") == colour("led:a8") == feedback.ON
    assert colour("led:b7") == colour("led:a7") == feedback.IDLE
    assert colour("led:a1") == feedback.ARMED  # the other pads still show the pages
