import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import numpy as np
import pytest
import soundfile as sf

from booth import compile as C
from booth import measure as M
from booth import palette as P
from booth import video
from booth.check import check
from conftest import EXAMPLES, example

SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "score.schema.json"


def test_schema_is_current():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", Path(__file__).resolve().parents[1] / "scripts" / "gen_schema.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert json.loads(SCHEMA.read_text()) == gen.build(), "run: uv run python scripts/gen_schema.py"


def test_examples_match_the_schema():
    schema = json.loads(SCHEMA.read_text())
    for path in EXAMPLES.glob("*.json"):
        jsonschema.validate(json.loads(path.read_text()), schema)


def test_palette_loads_and_hides_its_internals():
    pal = P.load("2026-11")
    g = pal.guide()
    assert len(g["instruments"]) == len(pal.instruments) >= 10
    assert set(g["instruments"][0]) == {"id", "role", "range", "about", "macros"}
    drums = [i for i in g["instruments"] if i["role"] == "drums"]
    assert all(len(i["pads"]) == 16 and i["pads"][0]["note"] == 36 for i in drums)    # from booth survey, in git
    for inst in pal.instruments.values():
        for m in inst.macros.values():
            assert m.display(0.0) and m.display(1.0)


def test_measure_flags(tmp_path):
    sr = 44100
    t = np.arange(sr * 8) / sr
    flat = 0.2 * np.sin(2 * np.pi * 440 * t)
    sf.write(tmp_path / "flat.wav", np.stack([flat, flat], 1), sr)
    m = M.measure(tmp_path / "flat.wav", [("a", 0, 4), ("b", 4, 8)])
    assert "no_contrast" in m["flags"] and m["lufs"] < 0
    sub = 0.5 * np.sin(2 * np.pi * 50 * t) * (t > 4)
    sf.write(tmp_path / "sub.wav", np.stack([sub, sub], 1), sr)
    m = M.measure(tmp_path / "sub.wav", [("a", 0, 4), ("b", 4, 8)])
    assert "lost_on_phone" in m["flags"] and "no_contrast" not in m["flags"]
    sf.write(tmp_path / "silent.wav", np.zeros((sr, 2)), sr)
    assert M.measure(tmp_path / "silent.wav", [])["flags"] == ["silent"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_video(tmp_path):
    r = check(example())
    plan = C.compile(r.score, P.load("2026-11"))
    sr, seconds = 44100, 2.0
    y = 0.2 * np.sin(2 * np.pi * 220 * np.arange(int(sr * seconds)) / sr)
    sf.write(tmp_path / "r.wav", np.stack([y, y], 1), sr)
    size = (540, 960)
    geom = video.roll(plan, r.score.title, "120 BPM", size, tmp_path / "still.jpg")
    video.encode(tmp_path / "r.wav", tmp_path / "still.jpg", geom, size, seconds, tmp_path / "r.m4a", tmp_path / "v.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json",
                            str(tmp_path / "v.mp4")], capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)["streams"]
    assert {s["codec_type"] for s in streams} == {"video", "audio"}
    assert [s for s in streams if s["codec_type"] == "video"][0]["width"] == 540


def test_a_new_palette_keeps_the_old_one_and_was_surveyed():
    old, new = P.load("2026-11"), P.load("2026-12")
    for iid, inst in old.instruments.items():               # an old score renders the same on either
        assert new.instruments[iid] == inst
    assert len(new.instruments) - len(old.instruments) >= 25
    assert new.returns == old.returns and new.master_devices == old.master_devices and new.master_set == old.master_set
    survey = json.loads((P.PALETTES / "2026-12.survey.json").read_text())
    assert list(survey) == list(new.instruments)
    for iid, inst in new.instruments.items():
        found = survey[iid]
        assert found["devices"] == [inst.device_name, *inst.fx], iid       # it loaded as the palette says
        assert found["lufs"] is not None and found["lufs"] > -40, iid      # and it played
        if inst.role == "drums":
            assert [n for n, _ in found["pads"]] == list(range(36, 52)), iid
        assert inst.range[0] < inst.range[1] and 0 <= inst.range[0] and inst.range[1] <= 127
        assert inst.role in {"bass", "lead", "keys", "pluck", "pad", "drums", "texture"}
        for m in inst.macros.values():
            assert m.display(0.0) and m.display(1.0)
            if m.device == 0 and inst.load[2].endswith(".adg"):           # a rack macro the survey saw in Live
                assert m.param in [x[0] for x in found["macros"]], (iid, m.param)


def test_a_score_on_the_new_palette_checks_and_compiles():
    s = example()
    s["palette"] = "2026-12"
    s["parts"][0]["instrument"] = "drums.909"
    s["parts"][1]["instrument"] = "bass.acid"
    s["parts"][1]["macros"] = [{"name": "cutoff", "value": 0.5}, {"name": "reso", "value": 1.0}]
    s["parts"][2]["instrument"] = "keys.grand"
    r = check(s)
    assert r.ok, r.errors
    plan = C.compile(r.score, P.load("2026-12"))
    assert plan.tracks[1].settings == {0: {"Filter Cutoff": "620.00 Hz", "Filter Reso": "120.00 %"}}
    assert plan.tracks[1].volume_db == round(-11.4 + s["parts"][1]["gain_db"], 2)
    s["parts"][2]["instrument"] = "keys.music_box"
    s["palette"] = "2026-11"
    s["parts"][1]["instrument"] = "bass.acid"
    bad = check(s)
    assert not bad.ok and {e["code"] for e in bad.errors} >= {"unknown_instrument"}


def test_the_served_palette_is_pinned():
    assert P.SERVED == "2026-11" and P.served().version == "2026-11"         # a new file alone changes nothing
    assert P.served("2026-12").version == "2026-12"
    with pytest.raises(KeyError):
        P.served("2027-01")
