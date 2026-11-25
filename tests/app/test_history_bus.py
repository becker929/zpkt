"""The history's new side: moves recorded for a bus command, groups, the change stream and the shown text."""

from __future__ import annotations

import pytest

from zpkt.app import history as H
from zpkt.live import changes as C


def make(tmp_path, now=None):
    clock = [100.0] if now is None else now
    stream = C.Stream(tmp_path / "set.jsonl")
    h = H.History(
        "S", {"A/volume": "A volume"}, tmp_path / "h", tmp_path / "cp", clock=lambda: clock[0], changes=stream
    )
    h.baseline(
        {"0:f1": {"key": "A/volume", "s": "0.0 dB", "r": 0.85}, "0:f2": {"key": "B/volume", "s": "0 dB", "r": 0.5}}
    )
    return h, stream, clock


def test_a_recorded_move_is_an_entry_with_who_and_the_echo_is_not_a_second_one(tmp_path):
    h, _, _ = make(tmp_path)
    e = h.record([["A/volume", 0.5]], "agent")
    assert e is not None and e["who"] == "agent" and e["moves"][0]["from"] == ["0.0 dB", 0.85]
    assert h.seen("A/volume", "-6.0 dB", 0.5) is False  # Live reports the write back: not a move
    assert len(h.entries) == 1 and h.entries[0]["moves"][0]["to"] == ["-6.0 dB", 0.5]  # and it names the shown text


def test_a_move_to_where_a_control_already_is_makes_no_entry(tmp_path):
    h, _, _ = make(tmp_path)
    assert h.record([["A/volume", 0.85]], "you") is None and h.entries == []


def test_moves_with_one_group_and_who_are_one_entry(tmp_path):
    h, _, clock = make(tmp_path)
    h.record([["A/volume", 0.5]], "agent", "quieter")
    clock[0] += 30  # a long time later: still the group's entry
    h.record([["B/volume", 0.3]], "agent", "quieter")
    h.record([["A/volume", 0.4]], "agent", "quieter")
    assert len(h.entries) == 1 and [m["key"] for m in h.entries[0]["moves"]] == ["A/volume", "B/volume"]
    assert h.entries[0]["moves"][0]["to"][1] == 0.4 and h.entries[0]["moves"][0]["from"][1] == 0.85
    h.record([["A/volume", 0.2]], "agent", "other group")
    assert len(h.entries) == 2
    writes, e = h.undo("you")
    assert e is h.entries[1] and writes == [["A/volume", 0.4]]


def test_who_must_be_known(tmp_path):
    h, _, _ = make(tmp_path)
    with pytest.raises(ValueError, match="who is one of you, minilab, agent, booth, demo, cli, sys"):
        h.record([["A/volume", 0.5]], "gemini")
    h.record([["A/volume", 0.5]], "booth")
    assert h.entries[0]["who"] == "booth"


def test_settled_entries_go_to_the_stream_once_one_change_per_control(tmp_path):
    h, stream, clock = make(tmp_path)
    h.record([["A/volume", 0.5], ["B/volume", 0.3]], "agent", "quieter")
    assert h.flush_changes() == 0  # not settled yet
    clock[0] += 3
    assert h.flush_changes() == 2 and h.flush_changes() == 0
    changes = stream.read()
    assert [(c["key"], c["who"], c["group"]) for c in changes] == [
        ("A/volume", "agent", "quieter"),
        ("B/volume", "agent", "quieter"),
    ]
    assert changes[0]["was"].raw == 0.85 and changes[0]["now"].raw == 0.5


def test_a_gesture_without_a_group_is_grouped_by_its_entry(tmp_path):
    h, stream, _ = make(tmp_path)
    h.seen("A/volume", "-3 dB", 0.7, who="minilab")
    h.flush_changes(force=True)
    assert stream.read()[0]["group"] == f"gesture-{h.entries[0]['id']}" and stream.read()[0]["who"] == "minilab"


def test_undo_and_redo_are_changes_by_the_one_who_asked(tmp_path):
    h, stream, _ = make(tmp_path)
    h.record([["A/volume", 0.5]], "you")
    h.undo("minilab")
    h.redo("cli")
    got = [(c["who"], c["group"].split("-")[0], c["now"].raw) for c in stream.read()]
    assert got == [("you", "gesture", 0.5), ("minilab", "undo", 0.85), ("cli", "redo", 0.5)]


def test_entries_from_a_run_before_are_not_written_again(tmp_path):
    h, stream, _ = make(tmp_path)
    h.record([["A/volume", 0.5]], "you")
    h.flush_changes(force=True)
    again = H.History("S", {}, tmp_path / "h", tmp_path / "cp", changes=stream)
    assert again.flush_changes(force=True) == 0 and len(stream.read()) == 1


def test_forget_takes_back_a_move_whose_write_failed(tmp_path):
    h, _, _ = make(tmp_path)
    e = h.record([["A/volume", 0.5]], "you")
    h.forget(e)
    assert h.entries == [] and h.cur["A/volume"] == ["0.0 dB", 0.85] and not h.awaiting("A/volume")


def test_a_move_while_a_write_is_due_back_is_the_echo_and_a_later_one_counts(tmp_path):
    h, _, clock = make(tmp_path)
    h.record([["A/volume", 0.5]], "you")
    assert h.awaiting("A/volume")
    clock[0] += 5  # past EXPECT_S
    assert not h.awaiting("A/volume")
    assert h.seen("A/volume", "-9 dB", 0.3, who="minilab") is True
