"""The MiniLab 3 controller profile: the file, its schema, the parser and the matching of messages to controls."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from zpkt.app.minilab.profile import Event, Hit, Message, ProfileError, load_profile, parse_profile, profile_path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "lib" / "contracts"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads((CONTRACTS / "minilab3-profile.json").read_text())


@pytest.fixture(scope="module")
def profile():
    return load_profile()


def test_the_profile_file_agrees_with_its_schema(raw):
    schema = json.loads((CONTRACTS / "minilab3-profile.schema.json").read_text())
    jsonschema.validate(raw, schema)


def test_the_schema_rejects_what_the_parser_rejects(raw):
    schema = json.loads((CONTRACTS / "minilab3-profile.schema.json").read_text())
    bad = copy.deepcopy(raw)
    del bad["controls"][0]["verified"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    with pytest.raises(ProfileError, match="needs 'verified'"):
        parse_profile(bad)


def test_every_item_is_marked_unverified_and_says_where_it_came_from(raw):
    assert raw["status"] == "unverified"
    assert not any(c["verified"] for c in raw["controls"])
    assert not raw["ports"]["verified"] and not any(raw["sysex"][k]["verified"] for k in ("led", "display", "realign"))
    for c in raw["controls"]:
        assert c["source"] and c["basis"] in {"live-script", "midi-standard", "arturia-default", "guess", "unknown"}
        if c["basis"] == "live-script":
            assert "MiniLab_3" in c["source"]


def test_it_holds_every_control_the_design_names(profile):
    names = {c.name for c in profile.controls}
    expected = {f"k{i}" for i in range(1, 9)} | {f"f{i}" for i in range(1, 5)}
    expected |= {f"a{i}" for i in range(1, 9)} | {f"b{i}" for i in range(1, 9)}
    expected |= {"data_turn", "data_push", "octave_down", "octave_up", "hold", "mod", "bend", "keys", "shift"}
    expected |= {"play", "stop", "loop"}
    assert expected <= names


def test_messages_found_in_lives_script_are_matched_to_their_controls(profile):
    cases = [
        (Event("cc", 1, 86, 64), Hit("k1", 64, 86)),
        (Event("cc", 1, 117, 5), Hit("k8", 5, 117)),
        (Event("cc", 1, 30, 100), Hit("f3", 100, 30)),
        (Event("note", 10, 36, 90), Hit("a1", 90, 36)),
        (Event("note", 10, 51, 0), Hit("b8", 0, 51)),
        (Event("cc", 1, 28, 65), Hit("data_turn", 65, 28)),
        (Event("cc", 1, 29, 65), Hit("data_turn", 65, 29, shifted=True)),
        (Event("cc", 1, 118, 127), Hit("data_push", 127, 118)),
        (Event("cc", 1, 119, 127), Hit("data_push", 127, 119, shifted=True)),
        (Event("cc", 1, 27, 127), Hit("shift", 127, 27)),
        (Event("cc", 1, 107, 127), Hit("play", 127, 107)),
        (Event("cc", 1, 1, 50), Hit("mod", 50, 1)),
        (Event("cc", 1, 64, 127), Hit("hold", 127, 64)),
        (Event("pitchbend", 1, 0, 16383), Hit("bend", 16383, 0)),
        (Event("note", 1, 48, 80), Hit("keys", 80, 48)),
        (Event("note", 1, 72, 80), Hit("keys", 80, 72)),
    ]
    for event, hit in cases:
        assert profile.match(event) == hit, event


def test_a_message_the_profile_does_not_know_is_not_a_hit(profile):
    assert profile.match(Event("cc", 1, 3, 10)) is None
    assert profile.match(Event("note", 1, 47, 10)) is None  # below the keys
    assert profile.match(Event("note", 1, 73, 10)) is None  # above them
    assert profile.match(Event("note", 5, 36, 10)) is None  # pads are on channel 10
    assert profile.match(Event("pitchbend", 2, 0, 8192)) is None


def test_the_controls_with_no_known_message_are_listed_and_ignored_until_learned(profile):
    assert set(profile.unlearned()) == {"octave_down", "octave_up"}
    learned = profile.with_message("octave_up", Message("cc", 1, 99))
    assert learned.unlearned() == ["octave_down"]
    assert learned.match(Event("cc", 1, 99, 127)) == Hit("octave_up", 127, 99)
    assert not learned.by_name("octave_up").verified  # a learned number is still not verified
    assert profile.match(Event("cc", 1, 99, 127)) is None  # the original is not changed


def test_the_sysex_pieces_are_read_from_the_profile(profile):
    assert profile.sysex.header == (0xF0, 0x00, 0x20, 0x6B, 0x7F, 0x42) and profile.sysex.end == 0xF7
    assert profile.sysex.led_prefix == (0x02, 0x02, 0x16)
    assert profile.sysex.display.line_1_width == 10 and profile.sysex.display.line_2_width == 18
    assert profile.by_name("k1").realign_sysex_id == 7 and profile.by_name("b8").led_sysex_id == 75


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["controls"].append(copy.deepcopy(d["controls"][0])), "same name"),
        (lambda d: d["controls"][0]["message"].update(channel=17), "channel"),
        (lambda d: d["controls"][0]["message"].update(type="sysex"), "message type"),
        (lambda d: d["controls"][0]["message"].update(number=200), "number"),
        (lambda d: d["controls"][0].update(shifted_of="nothing"), "Shift variant"),
        (lambda d: d["sysex"].pop("header"), "needs 'header'"),
        (lambda d: d["sysex"].update(header=[1, 999]), "bytes"),
        (lambda d: d.pop("ports"), "needs 'ports'"),
    ],
)
def test_a_bad_profile_is_refused_with_a_sentence_that_says_what_to_fix(raw, edit, message):
    bad = copy.deepcopy(raw)
    edit(bad)
    with pytest.raises(ProfileError, match=message):
        parse_profile(bad)


def test_the_file_can_be_another_one_and_a_missing_or_broken_one_says_so(tmp_path, monkeypatch, raw):
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps(raw))
    monkeypatch.setenv("ZPKT_MINILAB_PROFILE", str(mine))
    assert profile_path() == mine and load_profile().device == "Arturia MiniLab 3"
    mine.write_text("{not json")
    with pytest.raises(ProfileError, match="not valid JSON"):
        load_profile()
    mine.unlink()
    with pytest.raises(ProfileError, match="no MiniLab profile"):
        load_profile()
