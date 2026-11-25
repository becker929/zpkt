"""zpkt.live.page_layout: how a Page is laid out, and how it becomes the mix desk's made surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

from tests.live.test_page import SPEC
from zpkt.live import describe as D
from zpkt.live import page as P
from zpkt.live import page_layout as L
from zpkt.live.testing import FakeLive, hw002_like

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hands" / "tools"))
import gen_schemas


@pytest.fixture
def live():
    with FakeLive(hw002_like()) as fake:
        yield fake


def laid(live, spec, drop=()):
    page = P.parse(spec)
    found, missing = D.look(live, page.targets())
    return page, found, missing, L.layout(page, found, missing)


def by_label(lay):
    return {c.label: c for g in lay.groups for c in g.controls}


def test_widgets_sizes_and_the_minilab_slot_come_from_the_rules(live):
    _, _, _, lay = laid(live, SPEC)
    c = by_label(lay)
    assert c["Threshold"].widget == "fader" and c["Dry/Wet"].widget == "knob"
    assert c["mute"].widget == "key" and c["mute"].slot == "b1" and c["Threshold"].slot == "f2"
    assert [g.name for g in lay.groups] == ["Sub", "Glue"] and [g.tint for g in lay.groups] == [0, 1]
    assert lay.minilab[0]["groups"] == ["Sub", "Glue"] and lay.phone_pages == [[0, 1]]


def test_the_heaviest_control_comes_first_and_is_big(live):
    spec = {"title": "w", "groups": [{"name": "g", "controls": [
        {"target": "Kick bus/pan", "weight": 1}, {"target": "Kick bus/volume", "weight": 3}, {"target": "Kick bus/send Space"}]}]}  # fmt: skip
    _, _, _, lay = laid(live, spec)
    assert [(c.label, c.size) for c in lay.groups[0].controls] == [
        ("volume", "big"),
        ("send Space", "normal"),
        ("pan", "small"),
    ]


def test_an_eq_band_is_a_pair_and_its_members_stay_together(live):
    _, _, _, lay = laid(live, SPEC)
    sub = lay.groups[0].controls
    assert [c.ref for c in sub] == ["Kick bus/desk EQ/1 Gain A", "Kick bus/desk EQ/1 Frequency A"]
    assert sub[0].pair == sub[1].pair and sub[0].pair is not None
    assert all(c.pair is None for c in lay.groups[1].controls)


def test_a_choice_is_a_row_of_keys_or_a_list_by_how_many_it_has(live):
    page = P.parse(
        {"title": "c", "groups": [{"name": "g", "controls": [{"target": "Kick bus/desk EQ/1 Filter On A"}]}]}
    )
    found, missing = D.look(live, page.targets())
    assert not missing
    d = next(iter(found.values()))
    assert (d["kind"], P.widget(page.controls()[0], d)) == ("switch", "key")
    for steps, widget in ((3, "segmented"), (5, "segmented"), (6, "list")):
        fake = dict(d, kind="choice", steps=steps, items=[str(i) for i in range(steps)])
        assert P.widget(page.controls()[0], fake) == widget  # type: ignore[arg-type]


def test_a_range_becomes_a_stripe_along_the_control(live):
    _, _, _, lay = laid(live, SPEC)
    low, high = by_label(lay)["1 Frqncy A"].range or (None, None)
    assert low is not None and high is not None and 0 <= low < high <= 1


def test_a_missing_target_is_drawn_greyed_with_the_reason(live):
    spec = {
        "title": "m",
        "groups": [{"name": "g", "controls": [{"target": "Nope/volume"}, {"target": "Kick bus/volume"}]}],
    }
    _, _, _, lay = laid(live, spec)
    gone, here = lay.groups[0].controls
    assert gone.missing and "Nope" in gone.missing and gone.widget == "knob"
    assert here.missing is None and here.widget == "fader"
    assert [p["level"] for p in lay.problems].count("error") == 1  # the linter still says so


def test_a_big_page_is_swiped_in_whole_cards_on_a_phone():
    assert L.phone_pages([5, 5, 5]) == [[0, 1], [2]]
    assert L.phone_pages([6, 6, 6, 6]) == [[0, 1], [2, 3]]
    assert L.phone_pages([4]) == [[0]] and L.phone_pages([]) == []
    assert L.phone_pages([2] * 7) == [[0, 1, 2, 3, 4, 5], [6]]


def test_the_layout_fits_its_contract(live):
    _, _, _, lay = laid(live, SPEC)
    schema = gen_schemas.build("page-layout", L.Layout)
    jsonschema.validate(json.loads(lay.model_dump_json()), schema)


def test_key_parts_spell_mixer_sends_and_device_params():
    assert L.key_parts("Kick bus/volume") == {"track": "Kick bus", "param": "volume"}
    assert L.key_parts("Kick bus/send Space") == {"track": "Kick bus", "param": "send:Space"}
    assert L.key_parts("Kick bus/desk Glue/Dry/Wet") == {"track": "Kick bus", "device": "desk Glue", "param": "Dry/Wet"}


def test_surfaces_follow_the_minilab_pages_and_name_their_page(live):
    page, found, _, _ = laid(live, SPEC)
    page.id = "kick"
    (s,) = L.to_surfaces(page, found)
    assert s["page_id"] == "kick" and s["hardware"] == 0
    assert s["controls"]["f1"] == {"track": "Kick bus", "device": "desk EQ", "param": "1 Gain A", "label": "1 Gain A"}
    assert s["controls"]["b1"]["param"] == "mute"


def test_a_macro_becomes_a_desk_macro(live):
    spec = {"title": "m", "groups": [{"name": "g", "controls": [{"label": "Darker", "macro": [
        {"target": "Kick bus/desk EQ/1 Gain A", "low": "0 dB", "high": -6},
        {"target": "Kick bus/volume", "low": "min", "high": "max"}]}]}]}  # fmt: skip
    page, found, _, lay = laid(live, spec)
    assert lay.groups[0].controls[0].widget == "macro" and lay.groups[0].controls[0].macro == [
        "Kick bus/desk EQ/1 Gain A",
        "Kick bus/volume",
    ]
    (s,) = L.to_surfaces(page, found)
    parts = s["controls"]["k1"]["macro"]
    assert parts[0] == {"track": "Kick bus", "device": "desk EQ", "param": "1 Gain A", "from": "0 dB", "to": "-6"}
