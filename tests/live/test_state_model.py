"""The whole-mix state as typed data: its keys (zpkt.live.inlive.keys), the [shown, raw] pair, the desk contract a
recipe is read by (zpkt.live.desk, lib/contracts/desk.schema.json), and raw writes in chunks (zpkt.live.writes)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from zpkt.live import desk, writes
from zpkt.live import state as S
from zpkt.live.inlive import keys
from zpkt.live.testing import FakeLive, hw002_like

ROOT = Path(__file__).resolve().parents[2]

DESK = {
    "made": 1763900000.0,
    "set": "HW002_121_pp_finish",
    "note": "the desk",
    "returns": [
        {"name": "Space", "devices": [{"name": "Reverb", "class": "Reverb", "values": {"Dry/Wet": ["100 %", 1.0]}}]}
    ],
    "chains": {"Kick bus": [{"name": "desk EQ", "class": "Eq8", "values": {"1 Gain A": ["-3.00 dB", -3.0]}}]},
    "mixer": {
        "Kick bus": {
            "volume": ["0.0 dB", 0.85],
            "pan": ["C", 0.0],
            "sends": {"Space": ["-inf dB", 0.0]},
            "mute": False,
        },
        "Main": {"volume": ["0.0 dB", 0.85], "pan": ["C", 0.0], "sends": {}},
    },
    "owned": [{"track": "kick", "device": "EQ Eight", "values": {"Device On": ["On", 1.0]}}],
    "monitor": [{"track": "mon A", "file": "/renders/a.wav", "beat": 0.0, "warping": False}],
}


def test_keys_name_every_value_of_the_mix():
    assert keys.mixer_key("Kick bus", "volume") == "Kick bus/volume"
    assert keys.send_key("Kick bus", "Space") == "Kick bus/send Space"
    assert keys.device_key("Main", keys.device_label("desk Glue", 1), "Threshold") == "Main/desk Glue/Threshold"
    assert keys.device_label("EQ Eight", 2) == "EQ Eight#2"
    with pytest.raises(ValueError, match="not a mixer value"):
        keys.mixer_key("Kick bus", "width")


def test_the_three_spellings_of_a_send():
    assert keys.send_param("Space") == "send:Space"
    assert keys.send_return("send:Space") == keys.send_return("send Space") == "Space"
    assert keys.send_return("volume") is None


def test_shown_raw_is_a_list_with_names():
    v = S.ShownRaw.of("-6.0 dB", 0.7)
    assert v == ["-6.0 dB", 0.7] and (v.shown, v.raw) == ("-6.0 dB", 0.7) and json.dumps(v) == '["-6.0 dB", 0.7]'


def test_the_desk_contract_matches_what_recipe_writes():
    schema = json.loads((ROOT / "lib" / "contracts" / "desk.schema.json").read_text())
    jsonschema.validate(DESK, schema)
    assert desk.parse(DESK).chains["Kick bus"][0].class_ == "Eq8"
    st = S.load_dict({"name": "short-8d2a2", "desk": DESK})
    flat = S.flatten(st)
    assert st["partial"] is True
    assert flat["Kick bus/mute"] == ["False", False] and flat["Kick bus/send Space"] == ["-inf dB", 0.0]
    assert flat["Space/Reverb/Dry/Wet"] == ["100 %", 1.0] and flat["kick/EQ Eight/Device On"] == ["On", 1.0]
    assert flat["Kick bus/desk EQ/1 Gain A"] == ["-3.00 dB", -3.0]


def test_a_desk_that_breaks_the_contract_says_where():
    bad = {**DESK, "mixer": {"Kick bus": {"volume": ["0.0 dB"], "pan": ["C", 0.0]}}}
    with pytest.raises(ValueError, match=r"not a mix desk recipe: mixer/Kick bus/volume"):
        S.load_dict({"desk": bad})
    with pytest.raises(ValueError, match="neither a state nor a desk recipe"):
        S.load_dict({"regions": []})


def test_raw_writes_go_in_chunks_and_name_what_they_skip():
    with FakeLive(hw002_like()) as live:
        dev = f"next(d for d in {S.track_expr('Kick bus')}.devices if d.name == 'desk EQ')"
        names = [n for n in writes.read_raw(live, dev)][:20]
        n = len(live.calls)
        skipped = writes.set_raw(live, dev, [(name, 0.0) for name in names] + [("Nope", 1.0)], chunk=8)
        assert skipped == ["Nope"] and len(live.calls) == n + 3
        assert not any(c.readbacks for c in live.calls)
        after = writes.read_raw(live, dev, chunk=7)
        assert len(after) > 20 and all(after[name][1] == max(0.0, live_min(live, dev, name)) for name in names)


def live_min(live: FakeLive, dev: str, name: str) -> float:
    return live.run(f"result = next(p for p in {dev}.parameters if p.name == {name!r}).min")
