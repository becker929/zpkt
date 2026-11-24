"""surfaces.py offline: the checks against the set, saving, and the whole job with a stand-in for Claude."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import surfaces  # noqa: E402

INV = surfaces.parse_inventory("\n".join([
    "Kick bus\t\tvolume\t0.0 dB\t-inf dB\t6.0 dB\t",
    "Kick bus\t\tmute\toff\toff\ton\tQ",
    "Hats bus\tdesk EQ\t7 Gain A\t-6.50 dB\t-15.0 dB\t15.0 dB\t",
    "Hats bus\tdesk EQ\tDevice On\tOn\tOff\tOn\tQ",
    "Space\tReverb\tDecay Time\t1.20 s\t200 ms\t60.0 s\t",
]))


@pytest.fixture(autouse=True)
def tmp_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(surfaces, "folder", lambda set_name: tmp_path / "surfaces" / set_name)


def test_validate_keeps_what_the_set_holds_and_says_what_it_dropped():
    s = surfaces.validate({"name": "Low end!", "what": "x", "controls": {
        "k1": {"track": "hats bus", "device": "desk eq", "param": "7 gain a", "label": "Air"},
        "k2": {"label": "Dark", "macro": [{"track": "Hats bus", "device": "desk EQ", "param": "7 Gain A", "from": "0 dB", "to": "-9 dB"},
                                         {"track": "Nope", "param": "volume"}]},
        "f1": {"track": "Kick bus", "param": "volume"},
        "b1": {"track": "Kick bus", "param": "mute"},
        "b2": {"track": "Kick bus", "param": "volume"},
        "k9": {"track": "Kick bus", "param": "volume"},
        "k3": {"track": "Kick bus", "device": "Ghost", "param": "Drive"}}}, INV, ["Buses"])
    assert s["name"] == "Low end"
    assert s["controls"]["k1"] == {"track": "Hats bus", "param": "7 Gain A", "device": "desk EQ", "label": "Air"}
    assert s["controls"]["k2"]["macro"] == [{"track": "Hats bus", "param": "7 Gain A", "device": "desk EQ", "from": "0 dB", "to": "-9 dB"}]
    assert set(s["controls"]) == {"k1", "k2", "f1", "b1"}
    assert len(s["notes"]) == 4          # the macro's missing track, the fader on a pad, k9, the ghost device


def test_a_taken_name_gets_a_number_and_nothing_valid_is_an_error():
    s = surfaces.validate({"name": "Buses", "controls": {"f1": {"track": "Kick bus", "param": "volume"}}}, INV, ["buses"])
    assert s["name"] == "Buses 2"
    with pytest.raises(surfaces.SurfaceError):
        surfaces.validate({"name": "x", "controls": {"k1": {"track": "Nope", "param": "volume"}}}, INV, [])


def test_make_asks_checks_saves_and_lists_the_page():
    seen = {}
    def fake(prompt):
        seen["prompt"] = prompt
        return 'Here it is:\n```json\n' + json.dumps({"name": "Hats", "what": "hat air", "controls": {
            "k1": {"track": "Hats bus", "device": "desk EQ", "param": "7 Gain A"}}}) + "\n```"
    path, s = surfaces.make("air on the hats", INV, "SET", ["Buses"], ask=fake)
    assert "air on the hats" in seen["prompt"] and "7 Gain A: now -6.50 dB (range -15.0 dB .. 15.0 dB)" in seen["prompt"]
    saved = json.loads(path.read_text())
    assert saved["prompt"] == "air on the hats" and saved["set"] == "SET"
    assert [p["name"] for p in surfaces.pages("SET")] == ["Hats"]
    gone = surfaces.remove("SET", path.name)
    assert gone.exists() and surfaces.pages("SET") == []
    with pytest.raises(surfaces.SurfaceError):
        surfaces.remove("SET", "../x.json")
