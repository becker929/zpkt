import copy

from booth.check import check
from conftest import example


def codes(raw):
    return [e["code"] for e in check(raw).errors]


def test_examples_pass():
    for name in ("clockwork", "lullaby"):
        r = check(example(name))
        assert r.ok, r.errors
        assert r.estimate["notes"] > 0 and r.estimate["audio_s"] <= 60


def test_schema_errors_point_at_the_field():
    s = example()
    s["parts"][0]["gain_db"] = 40
    r = check(s)
    assert not r.ok and r.errors[0]["path"] == "parts[0].gain_db" and r.errors[0]["code"] == "schema"


def test_extra_keys_and_code_are_refused():
    s = example()
    s["parts"][0]["device_path"] = "song.tracks[0]"
    assert codes(s) == ["schema"]
    s = example()
    s["parts"][0]["instrument"] = "__import__('os')"
    assert codes(s) == ["schema"]


def test_palette_lookups():
    s = example()
    s["parts"][0]["instrument"] = "synth.supersaw"
    assert "unknown_instrument" in codes(s)
    s = example()
    s["parts"][2]["macros"] = [{"name": "drive", "value": 0.5}]
    assert "unknown_macro" in codes(s)
    s = example()
    s["mix"]["room"] = "stadium"
    assert "unknown_setting" in codes(s)
    s = example()
    s["palette"] = "1999-01"
    assert codes(s) == ["unknown_palette"]


def test_structure():
    s = example()
    s["patterns"][3]["notes"][0]["p"] = 90            # bass line far out of the sub's range
    assert "pitch_out_of_range" in codes(s)
    s = example()
    s["patterns"][0]["notes"][0]["t"] = 4.0           # a one-bar pattern is beats 0-4
    assert "note_outside_pattern" in codes(s)
    s = example()
    s["song"][1]["play"].append({"part": "drums", "pattern": "fill"})
    assert "duplicate_play" in codes(s)
    s = example()
    s["song"][0]["play"][0] = {"part": "keys", "pattern": "beat"}
    assert "pattern_part_mismatch" in codes(s)
    s = example()
    s["parts"].append(copy.deepcopy(s["parts"][0]))
    assert "duplicate_id" in codes(s)


def test_length_limits():
    s = example()
    s["bpm"] = 60
    s["song"][3]["bars"] = 32
    assert "too_long" in codes(s)
    s = example()
    s["song"] = [{"bars": 2, "play": [{"part": "drums", "pattern": "beat"}]}]
    assert "too_short" in codes(s)


def test_note_budget_counts_repeats():
    s = example()
    s["patterns"][0]["notes"] = [{"p": 42, "t": i / 32, "d": 0.03, "v": 60} for i in range(128)]
    s["song"] = [{"bars": 16, "play": [{"part": "drums", "pattern": "beat"}]}]
    assert "too_many_notes" in codes(s)


def test_warnings_dont_stop_it():
    s = example()
    s["patterns"].append({"id": "spare", "part": "keys", "bars": 1, "notes": []})
    r = check(s)
    assert r.ok and {"unused_pattern", "empty_pattern"} <= {w["code"] for w in r.warnings}
