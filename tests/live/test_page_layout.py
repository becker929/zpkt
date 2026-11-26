"""zpkt.live.page_layout: how a Page is laid out, and how it becomes the mix desk's made surfaces."""

from __future__ import annotations

import json

import jsonschema
import pytest

from tests.live.test_page import SPEC
from zpkt.live import describe as D
from zpkt.live import page as P
from zpkt.live import page_layout as L
from zpkt.live import schemas
from zpkt.live.testing import FakeLive, hw002_like


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
    assert lay.minilab[0]["groups"] == ["Sub", "Glue"]


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


def test_a_panel_is_the_whole_minilab_with_the_unmapped_slots_named(live):
    spec = {"title": "three", "groups": [{"name": "g", "controls": [
        {"target": "Kick bus/volume"}, {"target": "Kick bus/pan"}, {"target": "Kick bus/mute"}]}]}  # fmt: skip
    _, _, _, lay = laid(live, spec)
    (panel,) = lay.panels
    assert [s.slot for s in panel.slots] == [s for s, _, _ in L.HARDWARE_SLOTS] and len(panel.slots) == 20
    mapped = {s.slot: s for s in panel.slots if s.ref}
    assert {k: v.ref for k, v in mapped.items()} == {
        "f1": "Kick bus/volume",
        "k1": "Kick bus/pan",
        "b1": "Kick bus/mute",
    }
    assert all(s.group == "g" and s.tint == 0 for s in mapped.values())
    empty = [s for s in panel.slots if not s.ref]
    assert len(empty) == 17 and all(s.group is None and s.tint is None for s in empty)
    by_slot = {s.slot: (s.kind, s.name) for s in panel.slots}
    assert by_slot["k6"] == ("knob", "Knob 6") and by_slot["f2"] == ("fader", "Fader 2")
    assert by_slot["b3"] == ("pad", "Pad 3")


def test_a_page_too_big_for_one_minilab_page_gets_a_panel_each(live):
    eq = "Kick bus/desk EQ/"

    def group(n: int) -> dict:
        names = ("Gain A", "Frequency A", "Q A", "Filter On A", "Filter Type A")
        return {"name": f"band {n}", "controls": [{"target": f"{eq}{n} {name}"} for name in names]}

    _, _, _, lay = laid(live, {"title": "bands", "groups": [group(n) for n in (1, 2, 3, 4)]})
    assert len(lay.panels) == len(lay.minilab) >= 2
    for panel, hw in zip(lay.panels, lay.minilab, strict=True):
        assert panel.groups == hw["groups"] and len(panel.slots) == 20
        assert {s.slot: s.ref for s in panel.slots if s.ref} == {s["slot"]: s["ref"] for s in hw["slots"]}
    tints = {s.group: s.tint for p in lay.panels for s in p.slots if s.ref}
    assert tints == {g.name: g.tint for g in lay.groups}


def test_the_layout_fits_its_contract(live):
    _, _, _, lay = laid(live, SPEC)
    schema = schemas.build("page-layout", L.Layout)
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


# ---- compare states --------------------------------------------------------------------------------------------------

VOL, WET = "Kick bus/volume", "Kick bus/desk Glue/Dry/Wet"
COMPARE = {
    "title": "Kick: hotter?",
    "groups": [{"name": "Kick", "controls": [{"target": VOL}]}],
    "compare": {
        "name": "Kick",
        "states": [
            {"name": "as it is"},
            {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}, {"target": WET, "to": 0.25}]},
        ],
    },
}


def filled(live, spec):
    page = P.parse(spec)
    found, missing = D.look(live, page.targets())
    P.fill(page, found)
    return page, found, L.layout(page, found, missing)


def test_compare_states_are_pads_of_the_panel_with_what_the_shell_needs_to_light_them(live):
    _, found, lay = filled(live, COMPARE)
    assert lay.problems == []
    (panel,) = lay.panels
    pads = {s.slot: s.state for s in panel.slots if s.state is not None}
    assert pads == {"b7": 0, "b8": 1} and all(s.ref is None for s in panel.slots if s.state is not None)
    cmp = lay.compare
    assert cmp.name == "Kick" and [(s.name, s.slot) for s in cmp.states] == [("as it is", "b7"), ("hotter", "b8")]
    hotter = {w.target: w for w in cmp.states[1].writes}
    span = found[VOL]["max"] - found[VOL]["min"]
    assert hotter[VOL].to == 0.8 and hotter[VOL].n == pytest.approx((0.8 - found[VOL]["min"]) / span)
    assert hotter[VOL].near == pytest.approx(P.COMPARE_STEP)  # how near a place must be to hold
    assert set(hotter) == {VOL, WET} and {w.target for w in cmp.states[0].writes} == {VOL, WET}
    jsonschema.validate(lay.model_dump(), schemas.build("page-layout", L.Layout))
    assert L.layout(P.parse(SPEC), *D.look(live, P.parse(SPEC).targets())).compare is None  # a page without states


def test_the_surfaces_hand_the_pager_the_states_and_where_their_targets_are(live):
    page, found, _ = filled(live, COMPARE)
    page.id = "kick-hotter"
    (surface,) = L.to_surfaces(page, found)
    cmp = surface["compare"]
    assert cmp["pads"] == {"b7": 0, "b8": 1} and cmp["name"] == "Kick"
    assert cmp["states"][1] == {"name": "hotter", "writes": [[VOL, 0.8], [WET, 0.25]]}
    assert cmp["states"][0]["writes"] == [[VOL, page.compare.baseline[VOL]], [WET, page.compare.baseline[WET]]]
    assert cmp["targets"] == {
        VOL: {"track": "Kick bus", "param": "volume"},
        WET: {"track": "Kick bus", "device": "desk Glue", "param": "Dry/Wet"},
    }
    assert cmp["ranges"][VOL] == [found[VOL]["min"], found[VOL]["max"], False]
    assert "compare" not in L.to_surfaces(P.parse(SPEC), D.look(live, P.parse(SPEC).targets())[0])[0]
