"""history.py offline: moves, coalescing, undo/redo, checkpoints, compare, revert.

hands/.venv/bin/python -m pytest contrib/mixdesk/tests
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history


@pytest.fixture()
def h(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "hist")
    monkeypatch.setattr(history.S, "folder", lambda set_name: tmp_path / "state" / set_name)
    clock = [1000.0]
    x = history.History("SET", {"Kick bus/volume": "Kick bus volume"}, clock=lambda: clock[0])
    x.baseline(
        {
            "0:f1": {"key": "Kick bus/volume", "s": "0.0 dB", "r": 0.85},
            "0:k1": {"key": "Hats bus/desk EQ/1 Gain A", "s": "0.00 dB", "r": 0.5},
        }
    )
    x.now = clock
    return x


def full(vol: float, gain: float) -> dict:
    return {
        "returns": [],
        "tracks": {
            "Kick bus": {"mixer": {"volume": [f"{vol}", vol], "pan": ["C", 0.0], "sends": {}}, "devices": []},
            "Hats bus": {
                "mixer": {"volume": ["0", 0.85], "pan": ["C", 0.0], "sends": {}},
                "devices": [{"name": "desk EQ", "class": "Eq8", "params": {"1 Gain A": [f"{gain}", gain]}}],
            },
            "mon A": {
                "mixer": {
                    "volume": ["0", 0.8],
                    "pan": ["C", 0.0],
                    "sends": {},
                    "mute": ["False", False],
                    "solo": ["True", True],
                },
                "devices": [],
            },
        },
    }


def test_a_sweep_is_one_step_and_undo_redo_write_the_ends(h):
    for r in (0.80, 0.75, 0.70):
        h.now[0] += 0.3
        assert h.seen("Kick bus/volume", "x dB", r)
    assert len(h.entries) == 1 and h.entries[0]["moves"][0]["from"][1] == 0.85
    h.now[0] += 5
    h.seen("Hats bus/desk EQ/1 Gain A", "-3 dB", 0.4)
    assert len(h.entries) == 2

    pairs, _e = h.undo()
    assert pairs == [["Hats bus/desk EQ/1 Gain A", 0.5]]
    assert not h.seen("Hats bus/desk EQ/1 Gain A", "0.00 dB", 0.5)  # the echo of our own write is not a move
    pairs, _ = h.undo()
    assert pairs == [["Kick bus/volume", 0.85]]
    assert h.undo() == ([], None)
    assert h.redo()[0] == [["Kick bus/volume", 0.70]]
    assert h.view()["can_redo"]


def test_moving_back_to_the_start_leaves_no_step_and_sys_moves_are_not_steps(h):
    h.seen("Kick bus/volume", "a", 0.6)
    h.now[0] += 0.5
    h.seen("Kick bus/volume", "b", 0.85)
    assert h.entries == []
    h.seen("Kick bus/volume", "c", 0.1, sys=True)
    assert h.entries == [] and h.cur["Kick bus/volume"][1] == 0.1


def test_a_new_move_drops_the_redo_tail(h):
    h.seen("Kick bus/volume", "a", 0.6)
    h.undo()
    h.now[0] += 5
    h.seen("Hats bus/desk EQ/1 Gain A", "b", 0.2)
    assert [e["moves"][0]["key"] for e in h.entries] == ["Hats bus/desk EQ/1 Gain A"]
    assert not h.view()["can_redo"]


def test_checkpoint_compare_and_revert(h):
    e = h.checkpoint("before", full(0.85, 0.5), None)
    assert e["k"] == "checkpoint"
    saved = history.S.load(h.folder() / "before.json")
    assert saved["tracks"]["mon A"]["mixer"]["solo"][1] is False  # monitor tracks as the desk leaves them
    h.now[0] += 5
    h.seen("Kick bus/volume", "-6 dB", 0.6)
    assert set(h.compare("before")) == {"Kick bus/volume"}
    pairs, e = h.revert("before")
    assert pairs == [["Kick bus/volume", 0.85]] and e["k"] == "revert"
    h.seen("Kick bus/volume", "0.0 dB", 0.85)
    assert h.compare("before") == {}
    assert h.undo()[0] == [["Kick bus/volume", 0.6]]  # a revert is undoable
    h.checkpoint("after", full(0.6, 0.5), None)
    assert set(h.compare("before", "after")) == {"Kick bus/volume"}
    assert [c["name"] for c in h.view()["checkpoints"]] == ["before", "after"]
    with pytest.raises(ValueError):
        h.checkpoint("../evil", full(0.6, 0.5), None)


def test_undo_passes_over_checkpoints_and_history_survives_a_restart(h):
    h.seen("Kick bus/volume", "a", 0.6)
    h.checkpoint("cp", full(0.6, 0.5), None)
    assert h.undo()[0] == [["Kick bus/volume", 0.85]]
    again = history.History("SET", {})
    assert again.pos == h.pos and len(again.entries) == 2


def test_parameters_moved_together_are_one_step(h):
    for r_k, r_g in ((0.8, 0.45), (0.7, 0.4)):  # a macro sweeping two parameters
        h.now[0] += 0.05
        h.seen("Kick bus/volume", "a", r_k)
        h.now[0] += 0.01
        h.seen("Hats bus/desk EQ/1 Gain A", "b", r_g)
    assert len(h.entries) == 1 and len(h.entries[0]["moves"]) == 2
    pairs, _ = h.undo()
    assert sorted(pairs) == [["Hats bus/desk EQ/1 Gain A", 0.5], ["Kick bus/volume", 0.85]]
