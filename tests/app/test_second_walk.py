"""The second walkthrough's findings, below the page (no browser): solo and mute come from inside Live and are
history like any control; a step that grew is whole in the change stream; "changed" counts from a checkpoint; the
loop's span and the Song's sections; the spectrum's device as an undoable move."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from zpkt.app import deskstate, history, protocol
from zpkt.app.bus import Command
from zpkt.app.desk import METER_KEY


def flag(rig, track: str, name: str, on: bool) -> None:
    rig.conn.run(f"next(t for t in song.tracks if t.name == {track!r}).{name} = {on!r}\nresult = 1")


def control(rig, n: int = 0) -> str:
    keys = [v["key"] for v in rig.state()["values"].values() if v.get("key") and v.get("n") is not None]
    return [k for k in dict.fromkeys(keys) if not k.endswith(("/mute", "/solo"))][n]


# ---- solo and mute -----------------------------------------------------------------------------------------------------


def test_a_solo_made_in_live_reaches_the_state_and_the_history_without_asking_live(rig):
    calls = len(rig.live.calls)
    flag(rig, "Kick bus", "solo", True)
    assert wait_for(lambda: rig.state()["solo"] == ["Kick bus"])
    assert len(rig.live.calls) == calls + 1  # the one call of this test that set it: the app asked nothing
    entry = rig.desk.history.entries[-1]
    assert entry["moves"][0] == {
        "key": "Kick bus/solo",
        "label": "Kick bus solo",
        "from": ["off", False],
        "to": ["on", True],
    }
    flag(rig, "Hats bus", "mute", True)
    assert wait_for(lambda: rig.state()["mute"] == ["Hats bus"])
    assert rig.get("/api/hear")[1]["changed"] == 2  # a solo left on is a change to the mix, and it is counted


def test_clearing_a_solo_is_a_move_through_the_bus_that_undo_takes_back(rig):
    flag(rig, "Kick bus", "solo", True)
    wait_for(lambda: rig.state()["solo"] == ["Kick bus"])
    before = len(rig.desk.history.entries)
    code, reply = rig.command("mix.set", {"writes": [["Kick bus/solo", 0, "off"]]})  # a track no page need hold
    assert code == 200 and reply["missing"] == [] and reply["entry"]
    assert rig.track("Kick bus").solo is False and wait_for(lambda: rig.state()["solo"] == [])
    assert len(rig.desk.history.entries) == before + 1  # on, then off: two steps, not "nothing happened"
    assert rig.command("history.undo")[0] == 200
    assert rig.track("Kick bus").solo is True and wait_for(lambda: rig.state()["solo"] == ["Kick bus"])
    assert rig.desk.bus.submit(Command("mix.set", "agent", {"writes": [["Kick bus/solo", 0]]}))[0] == 403


def test_the_monitors_switch_is_not_a_solo_of_the_mix(rig):
    before = len(rig.desk.history.entries)
    assert rig.command("monitor.choose", {"slot": "A"})[0] == 200  # solos "mon A": the desk's own doing
    assert rig.state()["solo"] == [] and len(rig.desk.history.entries) == before
    assert not any(k.startswith("mon ") for k in rig.desk.history.cur)


def test_the_flags_message_and_the_loops_span_are_in_the_protocol_and_the_state():
    msg = protocol.parse_message({"t": "flags", "solo": ["Kick bus"], "mute": [], "sys": False})
    state = deskstate.reduce(deskstate.initial(), msg, 0.0)
    assert state["solo"] == ["Kick bus"] and state["mute"] == []
    assert deskstate.flag_changes(deskstate.initial(), state) == [("Kick bus/solo", True)]
    with pytest.raises(protocol.BadMessage):
        protocol.parse_message({"t": "flags", "solo": "Kick bus", "mute": []})
    loop = protocol.parse_message({"t": "loop", "loop": "drop", "start": 64.0, "length": 96.0})
    assert deskstate.reduce(state, loop, 0.0)["loop_span"] == [64.0, 96.0]
    old = deskstate.reduce(state, protocol.parse_message({"t": "loop", "loop": "drop"}), 0.0)
    assert old["loop"] == "drop" and old["loop_span"] is None  # an older pager: the name alone


def test_setting_the_loop_reports_where_it_is(rig):
    assert rig.command("transport", {"action": "loop", "loop": "drop"})[0] == 200
    assert wait_for(lambda: rig.state()["loop"] == "drop")
    span = rig.state()["loop_span"]
    assert span[0] == 64.0 and span[0] + span[1] == 160.0  # bars 17 to 40 of 4/4
    assert rig.desk.call("m.DESK.snapshot()")["loop_span"] == span


# ---- one step per control, whole in the change stream --------------------------------------------------------------------


def test_a_step_that_grows_after_it_was_streamed_is_whole_in_the_change_stream(tmp_path):
    from zpkt.live import changes

    now = [1000.0]
    stream = changes.Stream(tmp_path / "set.jsonl")
    h = history.History("s", {}, tmp_path, checkpoints=tmp_path / "cp", clock=lambda: now[0], changes=stream)
    h.baseline(
        {"0:k1": {"key": "A/volume", "s": "6.00 dB", "r": 6.0}, "0:k2": {"key": "B/volume", "s": "0 dB", "r": 0.0}}
    )
    h.record([["A/volume", 7.49, "7.49 dB"]], "you", "touch-1")
    now[0] += 5
    assert h.flush_changes() == 1  # settled: the drag is in the stream
    h.record([["A/volume", 7.19, "7.19 dB"]], "you", "touch-2")  # a nudge, 5 s later: the same step
    now[0] += 1
    h.record([["A/volume", 7.01, "7.01 dB"]], "you", "touch-3")
    assert len(h.entries) == 1 and h.entries[0]["moves"][0]["from"] == ["6.00 dB", 6.0]
    now[0] += 5
    assert h.flush_changes() == 1  # the rest of the step, once: from where the stream left the control
    rows = stream.read()
    assert [(c["was"][1], c["now"][1]) for c in rows] == [(6.0, 7.49), (7.49, 7.01)]
    h.record([["B/volume", 1.0, "1 dB"]], "you")  # another control: the step is over
    h.record([["A/volume", 6.5, "6.50 dB"]], "you")
    assert len(h.entries) == 3
    pairs, entry = h.undo()
    assert pairs == [["A/volume", 7.01]] and entry is h.entries[2]


def test_an_agents_changes_join_by_group_only_and_a_switch_never_joins(tmp_path):
    h = history.History("s", {}, tmp_path, checkpoints=tmp_path / "cp")
    h.baseline({"0:k1": {"key": "A/volume", "s": "0", "r": 0.0}, "0:b1": {"key": "A/mute", "s": "off", "r": False}})
    h.record([["A/volume", 1.0]], "agent", "ask-1")
    h.record([["A/volume", 2.0]], "agent", "ask-2")
    assert len(h.entries) == 2  # two asks of an agent are two steps, though one control
    assert h.seen("A/mute", "on", True) and h.seen("A/mute", "off", False)
    assert [e["moves"][0]["key"] for e in h.entries[2:]] == ["A/mute", "A/mute"]


# ---- "changed" counts from a checkpoint ------------------------------------------------------------------------------------


def test_changed_is_zero_after_a_save_and_after_going_back_and_names_its_checkpoint(rig):
    key = control(rig)
    rig.command("mix.set", {"norms": [[key, 0.33]]})
    assert rig.get("/api/hear")[1]["changed"] == 1
    q = rig.desk.subscribe(app=True)
    assert rig.command("history.checkpoint", {"name": "clean", "new": True})[0] == 200
    hear = rig.get("/api/hear")[1]
    assert (hear["changed"], hear["base"]) == (0, "clean")
    assert any(m["t"] == "hear" and m["base"] == "clean" for m in list(q.queue))  # the page is told at once
    rig.command("mix.set", {"norms": [[control(rig, 1), 0.44]]})
    assert rig.get("/api/hear")[1]["changed"] == 1
    assert rig.command("history.revert", {"to": "clean"})[0] == 200
    hear = rig.get("/api/hear")[1]
    assert (hear["changed"], hear["base"]) == (0, "clean")  # the walkthrough's "1 changed" after going back
    assert rig.command("history.undo")[0] == 200  # the going back is undone: one control differs from "clean" again
    assert rig.get("/api/hear")[1]["changed"] == 1


def test_at_a_start_the_base_is_the_last_checkpoint_on_file(rig):
    key = control(rig)

    def raw_now():
        return next(v.get("r") for v in rig.state()["values"].values() if v.get("key") == key)

    rig.command("history.checkpoint", {"name": "yesterday", "new": True})
    before = raw_now()
    rig.command("mix.set", {"norms": [[key, 0.21]]})
    # Live's report of the move comes a moment after the command answers: wait for the state to hold the new value
    # (reading history.cur at once could still give the old one, and then nothing had changed "at a start")
    wait_for(lambda: raw_now() != before and rig.desk.history.cur[key][1] == raw_now())
    h = rig.desk.history
    again = history.History(h.set_name, {}, h.directory, checkpoints=h.checkpoints_dir)  # the app starts again
    again.baseline({k: v for k, v in rig.state()["values"].items() if v.get("key")})
    assert again.changed() == [key] and again.base_name == "yesterday"


# ---- going back shows at once ----------------------------------------------------------------------------------------------


def test_going_back_tells_the_page_where_the_controls_go_before_live_is_written(rig, monkeypatch):
    key = control(rig)
    rig.command("mix.describe", {"keys": [key]})  # the page has asked for the control's scale, as it does
    start = next(v["n"] for v in rig.state()["values"].values() if v.get("key") == key)
    rig.command("history.checkpoint", {"name": "here", "new": True})
    rig.command("mix.set", {"norms": [[key, 0.9]]})
    q, seen = rig.desk.subscribe(app=True), []
    real = rig.desk.write
    monkeypatch.setattr(
        rig.desk, "write", lambda pairs: (seen.extend(m for m in list(q.queue) if m["t"] == "own"), real(pairs))[1]
    )
    assert rig.command("history.revert", {"to": "here"})[0] == 200
    assert len(seen) == 1 and seen[0]["values"][0][0] == key  # said before the write
    assert seen[0]["values"][0][1] == pytest.approx(start, abs=1e-6)
    view = rig.get("/api/history")[1]
    assert view["undo"]["values"][0][0] == key and view["undo"]["values"][0][1] == pytest.approx(0.9, abs=1e-3)


# ---- the spectrum's device ---------------------------------------------------------------------------------------------------


def test_turning_the_spectrum_on_is_one_undoable_move_and_an_agent_may_not(rig, monkeypatch):
    from zpkt.live.testing import devices

    tool = rig.desk.meter_tool()
    assert tool.NAME == "zpkt desk meter" and not tool.present(rig.conn) and rig.state()["meter"] is False
    put = lambda live, log=print: bool(rig.live.song.master_track._add_device(devices.make("Utility", name=tool.NAME)))  # noqa: E731
    monkeypatch.setattr(tool, "install", put)
    assert rig.desk.bus.submit(Command("meter.install", "agent", {}))[0] == 403
    q = rig.desk.subscribe(app=True)
    assert rig.command("meter.install")[0] == 200
    assert wait_for(lambda: any(m["t"] == "meterjob" and m["status"] == "done" for m in list(q.queue)))
    assert tool.present(rig.conn) and rig.state()["meter"] is True
    entry = rig.desk.history.entries[-1]
    assert entry["moves"][0]["key"] == METER_KEY and entry["who"] == "you"
    assert rig.get("/api/hear")[1]["changed"] == 0
    assert rig.command("history.undo")[0] == 200 and not tool.present(rig.conn) and rig.state()["meter"] is False
    assert rig.command("history.redo")[0] == 200 and tool.present(rig.conn)
    assert rig.desk.call("m.DESK.snapshot()")["meter"] is True  # the pager says so from inside Live


def test_a_spectrum_that_cannot_be_turned_on_is_said_and_leaves_no_step(rig, monkeypatch):
    tool = rig.desk.meter_tool()

    def refuse(live, log=print):
        raise tool.MeterError("Live's browser does not show the meter yet")

    monkeypatch.setattr(tool, "install", refuse)
    before = len(rig.desk.history.entries)
    q = rig.desk.subscribe(app=True)
    rig.command("meter.install")
    said = wait_for(lambda: next((m for m in list(q.queue) if m["t"] == "meterjob" and m["status"] == "error"), None))
    assert "browser" in said["msg"] and len(rig.desk.history.entries) == before and rig.state()["meter"] is False
