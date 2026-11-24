"""The history file and checkpoints keep their shapes: a made-up file in the form the desk wrote before is read,
and what is written back has the same keys."""

from __future__ import annotations

import json

import history


def test_a_history_file_in_the_old_shape_is_read_and_written_in_it(tmp_path):
    entry = {
        "k": "move",
        "moves": [
            {"key": "Kick bus/volume", "label": "Kick bus volume", "from": ["0.0 dB", 0.85], "to": ["-6.0 dB", 0.6]}
        ],
        "id": 7,
        "at": 1000.0,
    }
    cp = {"k": "checkpoint", "name": "start-20261120-0900", "moves": [], "id": 8, "at": 1001.0}
    (tmp_path / "SET.json").write_text(json.dumps({"entries": [entry, cp], "pos": 2, "seq": 8}))
    h = history.History("SET", {}, directory=tmp_path, checkpoints=tmp_path / "state", clock=lambda: 2000.0)
    assert h.entries == [entry, cp] and h.pos == 2 and h.seq == 8
    h.baseline({"0:f1": {"key": "Kick bus/volume", "s": "-6.0 dB", "r": 0.6}})
    assert h.undo()[0] == [["Kick bus/volume", 0.85]]
    saved = json.loads((tmp_path / "SET.json").read_text())
    assert set(saved) == {"entries", "pos", "seq"} and saved["pos"] == 0 and saved["entries"] == [entry, cp]


def test_a_checkpoint_is_a_hands_state_file_with_shown_raw_pairs(tmp_path):
    h = history.History("SET", {}, directory=tmp_path, checkpoints=tmp_path / "state", clock=lambda: 2000.0)
    full = {
        "returns": ["A-Space"],
        "tracks": {
            "Kick bus": {
                "mixer": {
                    "volume": ["0.0 dB", 0.85],
                    "pan": ["C", 0.0],
                    "sends": {"A-Space": ["-inf dB", 0.0]},
                    "mute": ["False", False],
                    "solo": ["False", False],
                },
                "devices": [{"name": "desk EQ", "class": "Eq8", "params": {"1 Gain A": ["0.00 dB", 0.5]}}],
            }
        },
    }
    h.checkpoint("cp1", full, None)
    saved = json.loads((tmp_path / "state" / "cp1.json").read_text())
    assert saved["set"] == "SET" and saved["name"] == "cp1" and saved["made_by"] == "mixdesk"
    assert saved["tracks"]["Kick bus"]["mixer"]["volume"] == ["0.0 dB", 0.85]
    assert h.load("cp1")["Kick bus/desk EQ/1 Gain A"] == ["0.00 dB", 0.5]
    assert h.load("cp1")["Kick bus/send Space"] == ["-inf dB", 0.0]
