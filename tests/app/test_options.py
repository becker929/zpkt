"""Options: the pure part (zpkt.app.options) and the contract file."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from zpkt.app import options as O

SCHEMA = json.loads((Path(__file__).parents[2] / "lib" / "contracts" / "option.schema.json").read_text())
MEASURE = {"seconds": 2.0, "rate": 44100, "peak_db": -6.0, "rms_db": -9.0, "lufs": -10.0, "bands_db": [-30.0] * 31}


def valid(option):
    jsonschema.validate(json.loads(json.dumps(option)), SCHEMA)


def test_a_request_becomes_a_queued_job_with_the_mix_as_its_base():
    job = O.new_job({"title": "Kick up", "versions": [{"label": "+3", "writes": [["Kick bus/volume", 0.8]]}]})
    assert [v["id"] for v in job["versions"]] == ["base", "v1"]
    assert job["versions"][0]["writes"] is None and job["versions"][1]["writes"] == [["Kick bus/volume", 0.8]]
    assert job["total"] == 2 and job["base"] == "base" and job["kind"] == "grid"
    assert job["range"] == {"start_beat": None, "length_beats": None}
    assert O.keys_of(job) == ["Kick bus/volume"]


def test_a_request_can_leave_out_the_base_and_name_a_range():
    job = O.new_job(
        {
            "title": "t",
            "base": False,
            "versions": [{"writes": [["a", 1]]}],
            "range": {"start_beat": 64, "length_beats": 16},
        }
    )
    assert job["base"] is None and [v["id"] for v in job["versions"]] == ["v1"]
    assert job["versions"][0]["label"] == "Version 1"
    assert job["range"] == {"start_beat": 64.0, "length_beats": 16.0}


@pytest.mark.parametrize(
    "body, words",
    [
        ({}, "title"),
        ({"title": "t"}, "versions"),
        ({"title": "t", "versions": [{"writes": []}]}, "writes"),
        ({"title": "t", "versions": [{"writes": [["a", "x"]]}]}, "finite number"),
        ({"title": "t", "versions": [{"writes": [["a", True]]}]}, "finite number"),
        ({"title": "t", "versions": [{"writes": [["a", float("inf")]]}]}, "finite number"),
        ({"title": "t", "versions": ["no"]}, "version 1"),
        ({"title": "t", "versions": [{"writes": [["a", 1]]}], "range": {"start_beat": 1}}, "range"),
        ({"title": "t", "versions": [{"writes": [["a", 1]]}], "range": {"start_beat": 0, "length_beats": 0}}, "range"),
        ({"title": "t", "versions": [{"writes": [["a", 1]]}] * 16}, "at most 16"),
    ],
)
def test_a_bad_request_says_what_to_change(body, words):
    with pytest.raises(O.BadOption, match=words):
        O.new_job(body)


def test_progress_text_counts_the_version_it_is_on():
    assert O.progress_text("rendering", 1, 3) == "rendering 2 of 3"
    assert O.progress_text("rendering", 3, 3) == "rendering 3 of 3"
    assert O.progress_text("failed", 0, 3, "Live is busy") == "Live is busy"
    assert O.progress_text("queued", 0, 3) == "queued" and O.progress_text("ready", 3, 3) == "ready"


def test_gaps_are_measured_against_the_base():
    job = O.new_job({"title": "t", "versions": [{"writes": [["a", 1]]}]})
    loud = {**MEASURE, "lufs": -7.0, "peak_db": -3.0}
    job["versions"][0]["measure"], job["versions"][1]["measure"] = MEASURE, loud
    job.update(id="o1", made=1.0, status="ready")
    out = O.with_gaps(job)
    assert out["versions"][0]["gap"]["lufs"] == 0 and out["versions"][1]["gap"]["lufs"] == 3.0
    assert out["versions"][1]["gap"]["peak_db"] == 3.0
    valid(out)


def test_with_gaps_leaves_an_unmeasured_version_without_one():
    job = O.new_job({"title": "t", "versions": [{"writes": [["a", 1]]}]})
    job.update(id="o1", made=1.0, status="queued")
    assert [v["gap"] for v in O.with_gaps(job)["versions"]] == [None, None]
    valid(job)


def test_a_mix2_batch_is_an_option_and_its_files_are_named_where_mixset_puts_them(tmp_path):
    folder = tmp_path / "mix2" / "b1"
    folder.mkdir(parents=True)
    for n in ("base.flac", "p00.flac", "p00-m.flac", "p01.flac"):
        (folder / n).write_bytes(b"x")
    row = {
        "id": "b1",
        "status": "rendering",
        "made": 5.0,
        "total": 5,
        "done": 3,
        "target": "bus-kick",
        "device": "Saturator",
        "base": "base.flac",
        "baseLufs": -9.1,
        "points": [
            {"k": 0, "values": {"Drive": "6 dB"}, "file": "p00.flac", "matched": "p00-m.flac", "lufs": -8.0},
            {"k": 1, "values": {"Drive": "12 dB"}, "file": "p01.flac", "lufs": -7.0},
            {"k": 2, "values": {"Drive": "18 dB"}, "file": "p02.flac", "lufs": -6.0},
        ],
    }
    o = O.from_mix2(row, tmp_path / "mix2")
    assert o["id"] == "mix2-b1" and o["kind"] == "mix2" and o["title"] == "Mix 2: Saturator on bus-kick"
    assert o["progress"] == "rendering 4 of 5"
    assert [(v["id"], v["status"]) for v in o["versions"]] == [
        ("base", "ready"),
        ("p00", "ready"),
        ("p01", "ready"),
        ("p02", "gone"),
    ]
    assert o["versions"][1]["label"] == "Drive 6 dB" and o["versions"][1]["known"] == {"lufs": -8.0}
    assert o["versions"][1]["matched_file"].endswith("p00-m.flac") and o["versions"][3]["file"] is None
    assert all(v["writes"] is None for v in o["versions"])
    valid(o)


def test_a_failed_mix2_batch_says_why_and_an_odd_status_counts_as_failed(tmp_path):
    o = O.from_mix2({"id": "b2", "status": "failed", "error": "Live is not on the mix set"}, tmp_path)
    assert o["status"] == "failed" and o["progress"] == "Live is not on the mix set" and o["versions"] == []
    assert O.from_mix2({"id": "b3", "status": "weird"}, tmp_path)["status"] == "failed"
    valid(o)


def test_spectral_renders_become_versions(tmp_path):
    (tmp_path / "before.flac").write_bytes(b"x")
    doc = {
        "note": "Fixes from the analysis.",
        "renders": [
            {"id": "before", "title": "Before", "file": "before.flac", "lufsWhole": -9.5},
            {"id": "fix-a", "title": "Boost 3 k", "file": "fix-a.flac", "lufsWhole": -9.0},
        ],
    }
    o = O.from_spectral(doc, tmp_path, made=3.0)
    assert o["id"] == "spectral" and o["note"] == "Fixes from the analysis." and o["base"] == "before"
    assert [v["status"] for v in o["versions"]] == ["ready", "gone"]
    assert O.loudness_of(o["versions"][0]) == -9.5
    valid(o)


def test_kick_options_prefer_the_mix_render(tmp_path):
    (tmp_path / "mix-a.flac").write_bytes(b"x")
    (tmp_path / "b.flac").write_bytes(b"x")
    doc = {
        "options": [
            {"id": "a", "title": "A", "loop": "a.flac", "mix": "mix-a.flac", "loopLufs": -8.0},
            {"id": "b", "title": "B", "loop": "b.flac", "loopLufs": -7.5},
        ]
    }
    o = O.from_kick(doc, tmp_path)
    assert o["versions"][0]["file"].endswith("mix-a.flac") and o["versions"][1]["file"].endswith("b.flac")
    valid(o)


def test_each_grid_of_a_panel_is_an_option_and_a_swept_one_has_no_files(tmp_path):
    f = tmp_path / "bass-g1-a.wav"
    f.write_bytes(b"x")
    panel = {
        "grids": [
            {
                "id": 1,
                "options": [
                    {"letter": "A", "label": "Cutoff 200 Hz", "file": str(f), "peak_dbfs": -3.0, "rms_dbfs": -12.0}
                ],
            },
            {"id": 2, "swept": True, "options": [{"letter": "A", "label": "x", "file": str(f)}]},
        ]
    }
    one, two = O.from_panel("bass", panel)
    assert one["id"] == "panel-bass-g1" and one["versions"][0]["known"] == {"peak_db": -3.0, "rms_db": -12.0}
    assert two["versions"][0]["status"] == "gone"
    valid(one)
    valid(two)


def test_options_are_ordered_running_first_then_newest():
    def opt(oid, status, made):
        return {"id": oid, "status": status, "made": made}

    got = O.ordered(
        [opt("old", "ready", 1), opt("new", "ready", 9), opt("run", "rendering", 0), opt("bad", "failed", 99)]
    )
    assert [o["id"] for o in got] == ["run", "new", "old", "bad"]


def test_find_version_names_the_ones_there_are():
    job = {"id": "o1", "versions": [{"id": "base"}, {"id": "v1"}]}
    assert O.find_version(job, "v1") == {"id": "v1"}
    with pytest.raises(O.BadOption, match="base, v1"):
        O.find_version(job, "v9")
