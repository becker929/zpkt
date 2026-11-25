"""zpkt.live.changes: the changes between two states, who made them, and one set's stream on disk."""

from __future__ import annotations

import copy

import pytest

from zpkt.live import changes as C
from zpkt.live import state as S
from zpkt.live.testing import FakeLive, hw002_like


def _moved():
    with FakeLive(hw002_like()) as live:
        before = S.take(live)
        with live.main_thread():
            bus = next(t for t in live.song.tracks if t.name == "Hats bus")
            bus.mixer_device.volume.value = 0.5
            bus.mute = True
        return before, S.take(live)


def test_between_names_each_value_that_moved_with_both_pairs_and_who():
    before, after = _moved()
    made = C.between(before, after, "agent", at="2026-11-24 17:00:00", group="quieter hats")
    assert [c["key"] for c in made] == ["Hats bus/mute", "Hats bus/volume"]
    volume = made[1]
    assert volume["was"] == ["0.0 dB", 0.85] and volume["now"] == ["-14.0 dB", 0.5]
    assert volume["now"].shown == "-14.0 dB" and volume["who"] == "agent" and volume["group"] == "quieter hats"
    assert C.between(before, copy.deepcopy(before), "you") == []
    assert C.by_who(made) == {"agent": 2}


def test_a_value_on_one_side_only_has_none_on_the_other():
    before, after = _moved()
    del after["tracks"]["Hats bus"]
    gone = C.between(before, after, "you")
    assert gone and all(c["now"] is None and c["was"] is not None for c in gone)


def test_who_is_one_of_four():
    with pytest.raises(ValueError, match="who is one of you, minilab, agent, sys, not 'gemini'"):
        C.change("a/volume", ["0 dB", 0.85], ["-1 dB", 0.8], "gemini")  # type: ignore[arg-type]


def test_a_stream_numbers_appends_and_reads_on_from_a_number(rig):
    before, after = _moved()
    stream = C.Stream(C.path_for("test_set"))
    assert stream.path == rig.sets_dir / "changes" / "test_set.jsonl"
    assert stream.read() == [] and stream.last() == 0
    first = stream.append(C.between(before, after, "agent"))
    assert [c["n"] for c in first] == [1, 2]
    second = stream.append([C.change("Hats bus/volume", ["-14.0 dB", 0.5], ["0.0 dB", 0.85], "minilab")])
    assert second[0]["n"] == 3 and stream.last() == 3
    assert [c["n"] for c in stream.read(since=2)] == [3]
    assert [c["n"] for c in stream.read(who="agent")] == [1, 2]
    assert stream.read()[0]["now"].shown == "True"
    assert C.latest(stream.read())["Hats bus/volume"]["who"] == "minilab"
    assert C.by_who(stream.read()) == {"agent": 2, "minilab": 1}


def test_a_line_that_cannot_be_read_is_skipped_and_counted(rig):
    stream = C.Stream(C.path_for("test_set"))
    stream.append([C.change("a/volume", ["0 dB", 0.85], ["-1 dB", 0.8], "you")])
    with stream.path.open("a") as f:
        f.write('not json\n{"n": 2}\n\n')
    stream.append([C.change("a/pan", ["C", 0.0], ["10L", -0.2], "you")])
    assert [c["key"] for c in stream.read()] == ["a/volume", "a/pan"] and stream.skipped == 2
    assert stream.read()[-1]["n"] == 2
