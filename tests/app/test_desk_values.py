"""What the desk's server side does for a hand on a control (on FakeLive, no browser): one gesture is one history
step, a drag's positions do not each ask Live for the control's range, the page can ask a control's scale once,
a checkpoint keeps what can be redone and never overwrites another, and the state says which song is open."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from tests.app.test_history_bus import make
from tests.app.test_web import first_control
from zpkt.app import deskstate


def counting(rig, monkeypatch) -> list[str]:
    """Every piece of code sent into the fake Live from now on."""
    calls: list[str] = []
    real = rig.live.run

    def run(code, *args, **kwargs):
        calls.append(code)
        return real(code, *args, **kwargs)

    monkeypatch.setattr(rig.live, "run", run)
    return calls


# ---- one gesture, one step -----------------------------------------------------------------------------------------


def test_one_gesture_is_one_history_row_and_one_undo(rig):
    _, key, _ = first_control(rig, "f")
    start, before = rig.desk.history.cur[key][1], len(rig.desk.history.entries)
    for n in (0.30, 0.35, 0.42):  # a drag: the page sends the place it is at, again and again, with one group
        assert rig.command("mix.set", {"norms": [[key, n]]}, group="touch-abc")[0] == 200
    moves = [e for e in rig.desk.history.entries[before:] if e["k"] == "move"]
    assert len(moves) == 1 and len(moves[0]["moves"]) == 1
    assert moves[0]["moves"][0]["from"][1] == start  # from where the gesture found it, not the place before the last
    assert rig.command("history.undo")[0] == 200
    assert rig.desk.history.cur[key][1] == start  # one undo: back where the drag began, not at a value in between
    assert rig.desk.history.pos == before


def test_another_control_is_another_step_and_one_that_ends_where_it_began_is_none(rig):
    _, key, _ = first_control(rig, "f")
    other = next(
        v["key"]
        for v in rig.state()["values"].values()
        if v.get("key") and v["key"] != key and v.get("n") is not None and not v.get("q")
    )
    before = len(rig.desk.history.entries)
    rig.command("mix.set", {"norms": [[key, 0.30]]}, group="touch-1")
    rig.command("mix.set", {"norms": [[other, 0.50]]}, group="touch-2")
    assert len(rig.desk.history.entries) == before + 2
    place = rig.state()["values"]
    home = next(v["n"] for v in place.values() if v.get("key") == key)
    rig.command("mix.set", {"norms": [[key, 0.9]]}, group="touch-3")
    wait_for(lambda: next(v["n"] for v in rig.state()["values"].values() if v.get("key") == key) != home)
    rig.command("mix.set", {"norms": [[key, home]]}, group="touch-3")  # dragged away and back: nothing to undo
    assert len(rig.desk.history.entries) == before + 2


def test_a_drag_then_nudges_of_one_control_are_one_step_back_to_where_it_was(rig):
    """The walkthrough's finding: 6.00 -> 7.49 by a drag, then three bursts of nudges, took four undos. Changes to
    one control by one person, with nothing else in between, are one step, whatever gesture each was."""
    _, key, _ = first_control(rig, "f")
    start, before = rig.desk.history.cur[key][1], len(rig.desk.history.entries)
    for n, group in ((0.60, "touch-drag"), (0.58, "touch-keys1"), (0.575, "touch-keys2"), (0.57, "touch-keys3")):
        assert rig.command("mix.set", {"norms": [[key, n]]}, group=group)[0] == 200
    moves = [e for e in rig.desk.history.entries[before:] if e["k"] == "move"]
    assert len(moves) == 1 and moves[0]["moves"][0]["from"][1] == start
    view = rig.get("/api/history")[1]
    assert view["undo"]["id"] == moves[0]["id"] and view["undo"]["values"][0][0] == key and view["redo"] is None
    assert rig.command("history.undo")[0] == 200
    assert rig.desk.history.cur[key][1] == start and rig.desk.history.pos == before  # one undo: all the way back
    view = rig.get("/api/history")[1]
    assert view["can_redo"] and view["redo"]["values"][0][0] == key and view["undo"] is None


def test_a_checkpoint_or_thirty_seconds_ends_the_step(rig, monkeypatch):
    _, key, _ = first_control(rig, "f")
    before = len(rig.desk.history.entries)
    rig.command("mix.set", {"norms": [[key, 0.30]]})
    rig.command("history.checkpoint", {"name": "between"})
    rig.command("mix.set", {"norms": [[key, 0.35]]})
    moves = [e for e in rig.desk.history.entries[before:] if e["k"] == "move"]
    assert len(moves) == 2  # the checkpoint stands between them
    real = rig.desk.history.clock
    monkeypatch.setattr(rig.desk.history, "clock", lambda: real() + 31)  # half a minute on
    rig.command("mix.set", {"norms": [[key, 0.40]]})
    assert len([e for e in rig.desk.history.entries[before:] if e["k"] == "move"]) == 3


def test_the_echo_names_the_value_in_the_row_and_the_page_is_told(rig):
    _, key, _ = first_control(rig, "f")
    q = rig.desk.subscribe(app=True)
    rig.command("mix.set", {"norms": [[key, 0.3]]}, group="touch-9")
    row = lambda: rig.desk.history.entries[-1]["moves"][0]  # noqa: E731
    wait_for(lambda: row()["to"][0] != str(row()["to"][1]))
    assert "dB" in row()["to"][0] and "dB" in row()["from"][0]  # old and new as Live shows them
    views = []
    while not q.empty():
        m = q.get_nowait()
        if m["t"] == "hist":
            views.append(m["entries"][-1]["moves"][0]["to"][0])
    assert views and "dB" in views[-1]  # the last history message the page got has the shown text


def test_an_echo_that_comes_after_a_slow_write_is_not_a_new_move(tmp_path):
    h, _, clock = make(tmp_path)
    h.record([["A/volume", 0.5]], "you", "touch-1")
    clock[0] += 5.0  # Live was busy: the write took longer than the echo is waited for
    h.written([["A/volume", 0.5]])
    h.record([["A/volume", 0.4]], "you", "touch-1")
    assert h.seen("A/volume", "-6.0 dB", 0.5) is False  # the first write's echo, late: still an echo
    assert len(h.entries) == 1 and h.entries[0]["moves"][0]["to"][1] == 0.4


# ---- no call per update --------------------------------------------------------------------------------------------


def test_a_drags_positions_do_not_each_ask_live_for_the_range(rig, monkeypatch):
    _, key, _ = first_control(rig, "f")
    rig.command("mix.set", {"norms": [[key, 0.3]]}, group="touch-a")  # the first one learns the range
    calls = counting(rig, monkeypatch)
    for n in (0.31, 0.32, 0.33, 0.34):
        rig.command("mix.set", {"norms": [[key, n]]}, group="touch-a")
    assert len(calls) == 4, [c[:60] for c in calls]  # one write each, nothing else
    assert all("set_raw" in c for c in calls)


def test_the_page_asks_a_controls_scale_once(rig, monkeypatch):
    _, fader, _ = first_control(rig, "f")
    code, reply = rig.command("mix.describe", {"keys": [fader, "Kick bus/mute", "No such/volume"]})
    assert code == 200 and set(reply["scales"]) == {fader, "Kick bus/mute"}  # a key the set lacks is left out
    scale = reply["scales"][fader]
    assert scale["kind"] == "continuous" and len(scale["stops"]) == 33
    assert scale["stops"][0][1] == 0.0 and scale["stops"][-1][1] == 1.0  # places, lowest first
    assert all(isinstance(text, str) for text, _ in scale["stops"])
    assert reply["scales"]["Kick bus/mute"]["kind"] == "switch" and len(reply["scales"]["Kick bus/mute"]["items"]) == 2
    calls = counting(rig, monkeypatch)
    assert rig.command("mix.describe", {"keys": [fader, "Kick bus/mute"]})[0] == 200
    assert calls == []  # kept: the second ask does not reach Live
    assert rig.command("mix.describe", {"keys": []})[0] == 400


# ---- checkpoints ---------------------------------------------------------------------------------------------------


def test_a_checkpoint_keeps_what_can_be_redone(rig):
    _, key, _ = first_control(rig, "f")
    rig.command("mix.set", {"norms": [[key, 0.3]]}, group="touch-a")
    moved = rig.desk.history.cur[key][1]
    rig.command("history.undo")
    assert rig.command("history.checkpoint", {"name": "kept", "new": True})[0] == 200
    view = rig.desk.history.view()
    assert view["can_redo"] and [e["k"] for e in view["entries"]][-2:] == ["checkpoint", "move"]
    assert view["pos"] == len(view["entries"]) - 1  # the undone move is still after where undo stands
    rig.command("history.redo")
    assert rig.desk.history.cur[key][1] == moved


def test_a_new_checkpoint_never_overwrites_one_with_its_name(rig):
    assert rig.command("history.checkpoint", {"name": "before the drop", "new": True})[1]["name"] == "before the drop"
    assert rig.command("history.checkpoint", {"name": "before the drop", "new": True})[1]["name"] == "before the drop 2"
    assert rig.command("history.checkpoint", {"name": "before the drop", "new": True})[1]["name"] == "before the drop 3"
    names = {c["name"] for c in rig.desk.history.view()["checkpoints"]}
    assert {"before the drop", "before the drop 2", "before the drop 3"} <= names
    assert rig.command("history.checkpoint", {"name": "bad/name", "new": True})[0] == 400


def test_going_back_to_a_checkpoint_is_one_step_that_undo_reverses(rig):
    _, key, _ = first_control(rig, "f")
    start = rig.desk.history.cur[key][1]
    rig.command("history.checkpoint", {"name": "home", "new": True})
    rig.command("mix.set", {"norms": [[key, 0.3]]}, group="touch-a")
    moved = rig.desk.history.cur[key][1]
    code, reply = rig.command("history.revert", {"to": "home"})
    assert code == 200 and reply["moved"] == 1
    assert rig.desk.history.cur[key][1] == pytest.approx(start)
    rig.command("history.undo")
    assert rig.desk.history.cur[key][1] == pytest.approx(moved)


# ---- which song is open --------------------------------------------------------------------------------------------


def test_the_state_says_which_set_its_tempo_signature_and_length(rig):
    song = rig.state()["song"]
    assert song["name"] and song["tempo"] == 160.0 and song["sig"] == [4, 4] and song["beats_per_bar"] == 4.0
    assert song["bars"] is None or song["bars"] >= 1
    rig.send({"t": "pos", "b": 8.0, "p": True, "bpm": 127.5})  # the pager sends the tempo with the playhead
    assert wait_for(lambda: rig.state()["song"]["tempo"] == 127.5)
    rig.send({"t": "pos", "b": 9.0, "p": True})  # an older pager says none: the tempo stays
    wait_for(lambda: rig.state()["pos"] == 9.0)
    assert rig.state()["song"]["tempo"] == 127.5


def test_song_facts_count_bars_by_the_signature():
    facts = deskstate.song_facts({"tempo": 160.0, "sig": [4, 4], "length": 160.0})
    assert facts == {"tempo": 160.0, "sig": [4, 4], "beats_per_bar": 4.0, "bars": 40}
    assert deskstate.song_facts({"sig": [6, 8], "length": 30.5})["bars"] == 11  # 3 beats a bar, rounded up
    assert deskstate.song_facts({}) == {"tempo": None, "sig": None, "beats_per_bar": 4.0, "bars": None}


def test_hearing_the_pin_does_not_move_the_playhead(rig, monkeypatch):
    """The walkthrough saw bar 39 turn into bar 19 after Pin: that was Live's loop coming round, not the Pin."""
    _, key, _ = first_control(rig, "f")
    rig.command("mix.set", {"norms": [[key, 0.3]]})
    rig.command("transport", {"action": "seek", "beat": 152.0})
    wait_for(lambda: rig.state()["pos"] == 152.0)
    calls = counting(rig, monkeypatch)
    assert rig.command("monitor.hear", {"hearing": "pin"})[0] == 200
    assert rig.state()["pos"] == 152.0 and not any("transport" in c for c in calls)
