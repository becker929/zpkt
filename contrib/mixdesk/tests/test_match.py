"""match.py offline: the eqfit spec and plan, and a plan applied to FakeLive's HW002-like set."""

from __future__ import annotations

import json

import pytest

import match
from zpkt.live.ops import LiveOps
from zpkt.live.testing import FakeLive, hw002_like
from zpkt.live.testing.display import fader_db


def test_eqfit_moves_has_every_stem_and_band_in_fit_json_order():
    spec = json.loads(match.FIT.read_text())
    moves = match.eqfit_moves()
    assert list(moves) == list(spec["controls"])
    kick = moves["Kick bus"]
    assert kick["gain_db"] == [-3, 3] and [b["kind"] for b in kick["eq"]] == ["peak", "peak", "peak", "highshelf"]


def test_a_plan_from_a_fit_keeps_only_bands_that_move():
    spec = json.loads(match.FIT.read_text())
    plan = {
        stem: {"gain_db": 0.0, "eq": [{"kind": b["kind"], "f": 100.0, "gain_db": 0.0, "q": 1.0} for b in c["bands"]]}
        for stem, c in spec["controls"].items()
    }
    plan["Kick bus"]["eq"][0] = {"kind": "peak", "f": 48.0, "gain_db": 2.5, "q": 1.2}
    plan["Kick bus"]["gain_db"] = -1.0
    out = match.plan_from_fit({"plan": plan})
    kick = [m for m in out["moves"] if m["track"] == "Kick bus"]
    assert {"track": "Kick bus", "device": "desk EQ", "param": "2 Gain A", "value": "2.5 dB"} in kick
    assert {"track": "Kick bus", "device": "desk EQ", "param": "2 Frequency A", "value": "48 Hz"} in kick
    assert {"track": "Kick bus", "param": "volume", "value": "-1.0 dB"} in kick
    assert len(kick) == 6 and out["moves"][-len(spec["main"]) :] == spec["main"]


def test_apply_sets_each_move_in_live(tmp_path, capsys):
    plan = {
        "moves": [
            {"track": "Hats bus", "device": "desk EQ", "param": "7 Gain A", "value": "-6.0 dB"},
            {"track": "Kick bus", "param": "volume", "value": "-5.0 dB"},
            {"track": "Kick bus", "param": "send:Space", "value": "-12 dB"},
            {"track": "Perc bus", "param": "mute", "value": True},
        ]
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    with FakeLive(hw002_like()) as live:
        match.apply(LiveOps(live), str(path))
        song = live.song
        kick = next(t for t in song.tracks if t.name == "Kick bus")
        assert fader_db(kick.mixer_device.volume.value) == pytest.approx(-5.0, abs=0.06)
        assert str(kick.mixer_device.sends[0]).startswith("-12")
        assert next(t for t in song.tracks if t.name == "Perc bus").mute
    assert "-6.0" in capsys.readouterr().out


def test_an_unknown_move_stops(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"moves": [{"track": "Kick bus", "param": "width", "value": 1}]}))
    with FakeLive(hw002_like()) as live, pytest.raises(SystemExit, match="unknown move"):
        match.apply(LiveOps(live), str(path))
