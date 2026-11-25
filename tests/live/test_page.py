"""zpkt.live.page: the spec an agent writes, the rules that turn it into widgets and MiniLab slots, and the gate."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import pytest

from zpkt.live import describe as D
from zpkt.live import page as P
from zpkt.live.testing import FakeLive, hw002_like

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hands" / "tools"))
import gen_schemas

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
    schema = gen_schemas.build("page", P.Page)
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
