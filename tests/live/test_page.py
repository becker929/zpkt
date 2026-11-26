"""zpkt.live.page: the spec an agent writes, the rules that turn it into widgets and MiniLab slots, and the gate."""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

from zpkt.live import describe as D
from zpkt.live import page as P
from zpkt.live import schemas
from zpkt.live.testing import FakeLive, hw002_like

SPEC = {
    "title": "Kick: sub and knock",
    "made_by": "agent",
    "groups": [
        {
            "name": "Sub",
            "controls": [
                {"target": "Kick bus/desk EQ/1 Gain A", "role": "level", "weight": 3},
                {"target": "Kick bus/desk EQ/1 Frequency A", "role": "tone", "range": ["34 Hz", "42 Hz"], "steps": 3},
            ],
        },
        {
            "name": "Glue",
            "controls": [
                {"target": "Kick bus/desk Glue/Dry/Wet"},
                {"target": "Kick bus/desk Glue/Threshold"},
                {"target": "Kick bus/volume"},
                {"target": "Kick bus/mute"},
            ],
        },
    ],
}


@pytest.fixture
def live():
    with FakeLive(hw002_like()) as fake:
        yield fake


def _checked(live, spec):
    page = P.parse(spec)
    found, missing = D.look(live, page.targets())
    return page, found, missing


def _errors(problems):
    return [(p["where"], p["text"]) for p in problems if p["level"] == "error"]


def test_a_good_page_passes_and_gets_widgets_roles_and_labels(live):
    page, found, missing = _checked(live, SPEC)
    assert P.lint(page, found, missing) == []
    widgets = {c.ref.rsplit("/", 1)[-1]: P.widget(c, found[c.ref]) for c in page.controls()}
    assert widgets == {
        "1 Gain A": "fader", "1 Frequency A": "knob", "Wet": "knob", "Threshold": "fader", "volume": "fader",
        "mute": "key",
    }  # fmt: skip
    roles = [P.role_of(c, found[c.ref]) for c in page.controls()]
    assert roles == ["level", "tone", "amount", "level", "level", "switch"]
    names = P.labels(page, found)
    assert names["Kick bus/desk EQ/1 Gain A"] == "1 Gain A" and all(len(n) <= P.MAX_LABEL for n in names.values())


def test_the_minilab_gets_levels_on_faders_the_rest_on_knobs_and_switches_on_pads(live):
    page, found, _ = _checked(live, SPEC)
    (hw,) = P.assign(page, found)
    assert hw["groups"] == ["Sub", "Glue"]
    slots = {s["slot"]: s["ref"].rsplit("/", 1)[-1] for s in hw["slots"]}
    assert slots == {
        "f1": "1 Gain A",
        "f2": "Threshold",
        "f3": "volume",
        "k1": "1 Frequency A",
        "k2": "Wet",
        "b1": "mute",
    }


def test_a_fifth_level_goes_to_a_knob_lightest_first_and_the_user_is_told(live):
    spec = {
        "title": "Levels",
        "groups": [
            {"name": "a", "controls": [{"target": f"{t}/volume", "weight": w} for t, w in (("Kick bus", 1), ("Hats bus", 3), ("Perc bus", 3))]},
            {"name": "b", "controls": [{"target": "Kick bus/send Space", "weight": 2}, {"target": "Kick bus/send Echo", "weight": 2}]},
        ],
    }  # fmt: skip
    page, found, missing = _checked(live, spec)
    problems = P.lint(page, found, missing)
    assert problems == [
        {"level": "note", "where": "Kick bus/volume", "text": "the MiniLab has 4 faders; this level is on a knob"}
    ]
    slots = {s["slot"]: s["ref"] for s in P.assign(page, found)[0]["slots"]}
    assert slots["k1"] == "Kick bus/volume" and slots["f1"] == "Hats bus/volume" and len(slots) == 5
    names = P.labels(page, found)
    assert names["Kick bus/volume"] != names["Hats bus/volume"] and names["Kick bus/volume"].startswith("Kick")


def test_groups_that_do_not_fit_one_hardware_page_go_to_the_next(live):
    bands = [f"Kick bus/desk EQ/{n} Frequency A" for n in range(1, 9)]
    spec = {
        "title": "EQ",
        "groups": [
            {"name": "low", "controls": [{"target": t} for t in bands[:5]]},
            {"name": "high", "controls": [{"target": t} for t in bands[5:]]},
            {"name": "q", "controls": [{"target": "Kick bus/desk EQ/1 Q A"}]},
        ],
    }
    page, found, missing = _checked(live, spec)
    assert _errors(P.lint(page, found, missing)) == []
    pages = P.assign(page, found)
    assert [hw["groups"] for hw in pages] == [["low", "high"], ["q"]]
    assert [s["slot"] for s in pages[0]["slots"]] == [f"k{n}" for n in range(1, 9)]


def test_the_gate_names_each_thing_wrong(live):
    spec = copy.deepcopy(SPEC)
    spec["groups"][0]["controls"] += [
        {"target": "Nope/volume"},
        {"target": "Kick bus/desk EQ/1 Gain A"},
        {"target": "Kick bus/pan", "label": "a label too long"},
        {"target": "Kick bus/desk EQ/2 Frequency A", "range": ["1 Hz", "50 Hz"]},
        {"target": "Kick bus/desk EQ/3 Frequency A", "steps": 3},
        {"target": "Kick bus/solo", "range": [0, 1]},
    ]
    spec["groups"].append({"name": "Glue", "controls": []})
    page, found, missing = _checked(live, spec)
    text = "\n".join(f"{w}: {t}" for w, t in _errors(P.lint(page, found, missing)))
    assert "Sub: 8 controls; a group holds at most 6" in text
    assert "Glue: the group is empty" in text and "Glue: two groups have this name" in text
    assert "Nope/volume: not in the open set: no track, return or Main named 'Nope'" in text
    assert "Kick bus/desk EQ/1 Gain A: the page has this control twice" in text
    assert "Kick bus/pan: the label 'a label too long' is over 10 characters" in text
    assert "Kick bus/desk EQ/2 Frequency A: the range ['1 Hz', '50 Hz'] is outside 10.0 Hz to 22.0 kHz" in text
    assert "Kick bus/desk EQ/3 Frequency A: steps needs a range to step through" in text
    assert "Kick bus/solo: a range needs a continuous value" in text


def test_too_many_controls_and_no_controls_are_refused(live):
    bands = [f"Kick bus/desk EQ/{n} {what} A" for n in range(1, 9) for what in ("Frequency", "Gain", "Q")]
    many = [*bands, "Kick bus/volume"]
    spec = {"title": "All", "groups": [{"name": f"g{i}", "controls": [{"target": t} for t in many[i : i + 5]]} for i in range(0, 25, 5)]}  # fmt: skip
    page, found, missing = _checked(live, spec)
    assert ("page", "25 controls; a page holds at most 24: split it in two") in _errors(P.lint(page, found, missing))
    assert _errors(P.lint(P.parse({"title": "x", "groups": []}), {})) == [("page", "the page has no controls")]


def test_a_role_live_disagrees_with_is_a_note_not_an_error(live):
    spec = {"title": "x", "groups": [{"name": "g", "controls": [{"target": "Kick bus/mute", "role": "level"}]}]}
    page, found, missing = _checked(live, spec)
    assert P.lint(page, found, missing) == [
        {"level": "note", "where": "Kick bus/mute", "text": "Live says this is a switch, not a level; shown as a key"}
    ]


def test_a_spec_may_not_be_half_a_control():
    with pytest.raises(ValueError, match="not a page: groups/0/controls/0: .*a target or a macro"):
        P.parse({"title": "x", "groups": [{"name": "g", "controls": [{"role": "level"}]}]})
    with pytest.raises(ValueError, match="weight"):
        P.parse({"title": "x", "groups": [{"name": "g", "controls": [{"target": "a/volume", "weight": 4}]}]})
    with pytest.raises(ValueError, match="a macro needs a label"):
        part = {"target": "a/volume", "low": "-6 dB", "high": "0 dB"}
        P.parse({"title": "x", "groups": [{"name": "g", "controls": [{"macro": [part, part]}]}]})


def test_a_macro_is_one_knob_and_all_its_targets_are_checked(live):
    parts = [
        {"target": "Kick bus/desk Glue/Dry/Wet", "low": "0 %", "high": "40 %"},
        {"target": "Nope/volume", "low": "-6 dB", "high": "0 dB"},
    ]
    spec = {"title": "x", "groups": [{"name": "g", "controls": [{"macro": parts, "label": "Squash"}]}]}
    page, found, missing = _checked(live, spec)
    assert page.targets() == ["Kick bus/desk Glue/Dry/Wet", "Nope/volume"]
    assert P.widget(page.controls()[0], None) == "macro"
    assert _errors(P.lint(page, found, missing)) == [
        ("macro:Squash", "not in the open set: no track, return or Main named 'Nope'")
    ]
    assert P.assign(page, found)[0]["slots"] == [{"slot": "k1", "ref": "macro:Squash", "group": "g"}]


def test_short_labels():
    assert P.short_label("Threshold") == "Threshold"
    assert P.short_label("1 Frequency A") == "1 Frqncy A"
    assert len(P.short_label("Compression Makeup Gain")) <= 10


def test_save_load_keeps_unknown_keys_and_numbers_a_taken_name(rig):
    spec = {**copy.deepcopy(SPEC), "later": {"x": 1}}
    spec["groups"][0]["controls"][0]["hint"] = "new in v3"
    page = P.parse(spec)
    path = P.save(page, "test_set")
    assert path == rig.sets_dir / "pages" / "test_set" / "kick-sub-and-knock.json"
    on_disk = json.loads(path.read_text())
    assert on_disk["schema"] == 2 and on_disk["later"] == {"x": 1}
    assert on_disk["groups"][0]["controls"][0]["hint"] == "new in v3"
    assert P.to_json(P.load(path)) == on_disk
    assert P.save(P.parse(SPEC), "test_set").name == "kick-sub-and-knock-2.json"
    assert P.save(page, "test_set") == path and len(P.saved("test_set")) == 2


def test_the_contract_accepts_what_the_model_writes_and_refuses_a_bad_weight():
    schema = schemas.build("page", P.Page)
    jsonschema.validate(P.to_json(P.parse(SPEC)), schema)
    bad = copy.deepcopy(SPEC)
    bad["groups"][0]["controls"][0]["weight"] = 9
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


# --------------------------------------------------------------------------- the commands, against a served fake


def test_describe_selection_and_page_lint_commands(live, tmp_path):
    from typer.testing import CliRunner

    from zpkt.live.live_cli import app

    port, run = str(live.serve()), CliRunner()
    seen = run.invoke(app, ["describe", "Kick bus/desk EQ/1 Gain A", "Nope/volume", "--port", port])
    assert seen.exit_code == 1
    assert "Kick bus/desk EQ/1 Gain A: 0.00 dB  (continuous; -15.0 dB to 15.0 dB)" in seen.output
    assert "Nope/volume: MISSING: no track, return or Main named 'Nope'" in seen.output
    assert run.invoke(app, ["selection", "--port", port]).output.strip() == "nothing selected"

    good = tmp_path / "good.json"
    good.write_text(json.dumps(SPEC))
    ok = run.invoke(app, ["page", "lint", str(good), "--port", port])
    assert ok.exit_code == 0 and ok.output.splitlines()[-1] == "ok"
    assert "MiniLab page 1 (Sub, Glue):" in ok.output and "f1=1 Gain A" in ok.output
    as_json = json.loads(run.invoke(app, ["page", "lint", str(good), "--json", "--port", port]).output)
    assert as_json["problems"] == [] and as_json["widgets"]["Kick bus/mute"] == "key"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"title": "x", "groups": [{"name": "g", "controls": [{"target": "Nope/volume"}]}]}))
    no = run.invoke(app, ["page", "lint", str(bad), "--port", port])
    assert no.exit_code == 1 and "error: Nope/volume: not in the open set" in no.output
    assert run.invoke(app, ["page", "lint", str(tmp_path / "none.json"), "--port", port]).exit_code == 2


# ---- compare states --------------------------------------------------------------------------------------------------

VOL, GAIN, MUTE, TYPE = (
    "Kick bus/volume",
    "Kick bus/desk EQ/1 Gain A",
    "Kick bus/mute",
    "Kick bus/desk EQ/1 Filter Type A",
)


def compare_spec(states, **more):
    return {
        "title": "Kick: hotter?",
        "groups": [{"name": "Kick", "controls": [{"target": VOL}, {"target": GAIN}]}],
        "compare": {"states": states, **more},
    }


def _filled(live, spec):
    page, found, missing = _checked(live, spec)
    P.fill(page, found)
    return page, found, missing


def test_a_state_with_no_writes_takes_the_values_the_controls_had(live):
    spec = compare_spec([{"name": "as it is"}, {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}]}])
    page, found, missing = _filled(live, spec)
    assert P.lint(page, found, missing) == []
    cmp = page.compare
    assert cmp.baseline == {VOL: found[VOL]["now"].raw}
    assert [(w.target, w.to) for w in cmp.states[0].writes] == [(VOL, found[VOL]["now"].raw)]  # the way back
    assert cmp.ranges[VOL] == (found[VOL]["min"], found[VOL]["max"], False)
    assert page.targets() == [VOL, GAIN]  # the page's controls, then what only the states write


def test_a_gap_between_states_is_filled_from_the_baseline(live):
    spec = compare_spec(
        [
            {"name": "as it is"},
            {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}]},
            {"name": "muted", "writes": [{"target": MUTE, "to": True}, {"target": TYPE, "to": 2}]},
        ]
    )
    page, found, missing = _filled(live, spec)
    assert P.lint(page, found, missing) == []
    base = page.compare.baseline
    assert set(base) == {VOL, MUTE, TYPE} and base[MUTE] is False
    for state in page.compare.states:  # every state writes the same set of controls
        assert [w.target for w in state.writes] == [VOL, MUTE, TYPE]
    hotter = {w.target: w.to for w in page.compare.states[1].writes}
    assert hotter == {VOL: 0.8, MUTE: base[MUTE], TYPE: base[TYPE]}
    assert MUTE in page.targets() and TYPE in page.targets()  # they are looked up in Live like any control


def test_a_baseline_kept_before_is_not_taken_again(live):
    """A page made again under its id keeps the mix as it was when it was first made: that is the way back."""
    spec = compare_spec([{"name": "as it is"}, {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}]}])
    page, found, _ = _checked(live, spec)
    page.compare.baseline = {VOL: 0.25, "Gone/volume": 0.5}  # as the app hands over what the saved page kept
    P.fill(page, found)
    assert page.compare.baseline == {VOL: 0.25}  # kept; what no state writes any more is dropped
    assert page.compare.states[0].writes[0].to == 0.25


def test_a_gap_that_cannot_be_filled_is_an_error(live):
    spec = compare_spec(
        [
            {"name": "one", "writes": [{"target": VOL, "to": 0.5}]},
            {"name": "two", "writes": [{"target": "No such/volume", "to": 0.5}]},
        ]
    )
    page, found, missing = _filled(live, spec)
    errors = _errors(P.lint(page, found, missing))
    assert ("compare:No such/volume", f"not in the open set: {missing['No such/volume']}") in errors
    assert all(w.target != "No such/volume" for w in page.compare.states[0].writes)  # nothing was made up for it
    # without the fill the linter says which state leaves what out
    raw_page, found, missing = _checked(
        live, compare_spec([{"name": "a"}, {"name": "b", "writes": [{"target": VOL, "to": 0.8}]}])
    )
    assert any("no value of it was kept" in text for _, text in _errors(P.lint(raw_page, found, missing)))


@pytest.mark.parametrize(
    ("states", "says"),
    [
        ([{"name": "only", "writes": [{"target": VOL, "to": 0.8}]}], "1 states; a compare has 2 to 8"),
        ([{"name": f"s{i}", "writes": [{"target": VOL, "to": i / 10}]} for i in range(9)], "9 states"),
        ([{"name": "a"}, {"name": "b"}], "no state writes anything"),
        ([{"name": "a"}, {"name": "A", "writes": [{"target": VOL, "to": 0.8}]}], "two states have this name"),
        ([{"name": "a"}, {"name": "much too long", "writes": [{"target": VOL, "to": 0.8}]}], "over 10 characters"),
        ([{"name": "a"}, {"name": "b", "writes": [{"target": VOL, "to": 1.5}]}], "outside its raw range"),
        ([{"name": "a"}, {"name": "b", "writes": [{"target": TYPE, "to": 1.5}]}], "a whole number"),
        (
            [{"name": "a"}, {"name": "b", "writes": [{"target": VOL, "to": 0.8}, {"target": VOL, "to": 0.7}]}],
            "twice",
        ),
        (
            [
                {"name": "a", "writes": [{"target": VOL, "to": 0.8}]},
                {"name": "b", "writes": [{"target": VOL, "to": 0.8}]},
            ],
            "is the same as 'a'",
        ),
    ],
)
def test_the_linter_holds_compare_states_to_their_limits(live, states, says):
    page, found, missing = _filled(live, compare_spec(states))
    assert any(says in text for _, text in _errors(P.lint(page, found, missing))), P.lint(page, found, missing)


def test_a_state_that_is_the_mix_as_it_is_twice_is_caught(live):
    now = D.look(live, [VOL])[0][VOL]["now"].raw
    page, found, missing = _filled(
        live, compare_spec([{"name": "a"}, {"name": "b", "writes": [{"target": VOL, "to": now}]}])
    )
    assert any("is the same as 'a'" in text for _, text in _errors(P.lint(page, found, missing)))


def test_states_take_the_last_pads_on_every_minilab_page_and_switches_the_ones_before(live):
    spec = compare_spec([{"name": "a"}, {"name": "b", "writes": [{"target": VOL, "to": 0.8}]}])
    spec["groups"][0]["controls"].append({"target": MUTE})
    page, found, _ = _filled(live, spec)
    (hw,) = P.assign(page, found)
    assert hw["compare"] == [{"slot": "b7", "state": 0, "name": "a"}, {"slot": "b8", "state": 1, "name": "b"}]
    assert [s["slot"] for s in hw["slots"] if s["ref"] == MUTE] == ["b1"]
    # 8 states leave no pad for a switch: the linter says the group does not fit
    eight = compare_spec([{"name": f"s{i}", "writes": [{"target": VOL, "to": i / 10}]} for i in range(8)])
    eight["groups"][0]["controls"].append({"target": MUTE})
    page, found, missing = _filled(live, eight)
    assert any("does not fit the MiniLab" in text for _, text in _errors(P.lint(page, found, missing)))
    # a page of states alone is a page: one MiniLab page with only its pads
    alone = {"title": "Only states", "groups": [], "compare": spec["compare"]}
    page, found, missing = _filled(live, alone)
    assert P.lint(page, found, missing) == []
    assert P.assign(page, found) == [{"groups": [], "slots": [], "compare": hw["compare"]}]


def test_the_lit_state_is_derived_from_the_values_within_a_step(live):
    spec = compare_spec(
        [
            {"name": "as it is"},
            {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}, {"target": MUTE, "to": True}]},
        ]
    )
    page, found, _ = _filled(live, spec)
    cmp, base = page.compare, page.compare.baseline
    assert P.lit(cmp, base) == 0
    assert P.lit(cmp, {VOL: 0.8, MUTE: True}) == 1
    assert P.lit(cmp, {VOL: 0.8004, MUTE: 1.0}) == 1  # within a thousandth of the range, and a switch as a number
    assert P.lit(cmp, {VOL: 0.81, MUTE: True}) is None  # somebody turned the knob
    assert P.lit(cmp, {VOL: 0.8, MUTE: False}) is None  # every target must hold, not most
    assert P.lit(cmp, {VOL: 0.8}) is None and P.lit(cmp, {}) is None  # a value nobody reported holds nothing
    assert P.tolerance(found[VOL]) == pytest.approx((found[VOL]["max"] - found[VOL]["min"]) * P.COMPARE_STEP)
    assert P.tolerance(found[MUTE]) == 0.5


def test_a_page_with_compare_states_fits_the_contract_and_goes_through_a_file(live, tmp_path):
    spec = compare_spec([{"name": "as it is"}, {"name": "hotter", "writes": [{"target": VOL, "to": 0.8}]}], name="Kick")
    page, _, _ = _filled(live, spec)
    data = P.to_json(page)
    jsonschema.validate(data, schemas.build("page", P.Page))
    again = P.load(P.save(page, "set", tmp_path))
    assert again.compare == page.compare and again.compare.name == "Kick"
