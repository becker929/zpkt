"""hands.live.hold: one user of Live at a time, and what an interrupted command left is put back by the next."""
from __future__ import annotations

import fcntl
import json
import os
import signal

import pytest

from hands import config
from hands.live import hold, mix, panel, rig
from hands.live.transport import LiveError, McpResult, Transport


class Live(Transport):
    """Records the code it is given; `down` makes it unreachable, `refuse` makes Live raise."""

    def __init__(self):
        self.ran, self.down, self.refuse, self.set = [], False, False, "/sets/HW002.als"

    def execute(self, code):
        if self.down:
            return McpResult("error", error="Cannot reach Ableton: [Errno 61] Connection refused")
        if self.refuse:
            return McpResult("error", error="IndexError: list index out of range")
        if code == hold.SET_PATH:
            return McpResult("ok", self.set)
        self.ran.append(code)
        return McpResult("ok", "ok")


def test_undo_runs_its_code_whether_the_body_ends_or_raises():
    live = Live()
    with hold.undo(live, "the tempo", "song.tempo = 120"):
        assert [e["what"] for e in hold.pending()] == ["the tempo"]     # on disk while the body runs
    with pytest.raises(ValueError):
        with hold.undo(live, "the tempo", "song.tempo = 121"):
            raise ValueError("the render failed")
    assert live.ran == ["song.tempo = 120", "song.tempo = 121"] and hold.pending() == []


def test_what_a_killed_command_left_is_put_back_by_the_next_newest_first():
    hold.note("the faders of a grid", "faders()")       # a process that died after writing these
    hold.note("the Render track", "render_track()")
    live = Live()
    with hold.using_live("hands panel make", client=live) as put_back:
        assert live.ran == ["render_track()", "faders()"]
        assert put_back == ["put back the Render track, left by an interrupted command",
                            "put back the faders of a grid, left by an interrupted command"]
    assert hold.pending() == []


def test_a_note_waits_while_live_is_away_and_goes_when_live_refuses_it():
    live = Live()
    hold.note("the tempo", "song.tempo = 120")
    live.down = True
    assert hold.replay(live) == [] and len(hold.pending()) == 1
    live.down, live.refuse = False, True
    assert hold.replay(live) == ["could not put back the tempo (IndexError: list index out of range [in 'song.tempo = 120'])"]
    assert hold.pending() == []


def test_undo_keeps_its_note_when_live_cannot_be_reached_and_says_so():
    live = Live()
    with pytest.raises(LiveError):
        with hold.undo(live, "the tempo", "song.tempo = 120"):
            live.down = True
    assert len(hold.pending()) == 1


def test_a_second_command_is_told_who_has_live():
    path = config.rig().data_dir / hold.LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as other:                      # another process, as flock sees it: its own open file
        fcntl.flock(other, fcntl.LOCK_EX)
        other.write(json.dumps({"pid": 1, "what": "hands panel grid", "at": 0}))
        other.flush()
        assert hold.holder()["what"] == "hands panel grid"
        with pytest.raises(hold.Busy, match="Live is busy with `hands panel grid`.*one hands command at a time"):
            with hold.using_live("hands panel make", wait_s=0):
                pass
    with hold.using_live("hands panel make", wait_s=0):  # free again once the other let go
        assert hold.holder() == {} or hold.holder()["what"] == "hands panel make"
    assert hold.holder() == {}


def test_sigterm_while_holding_live_unwinds_through_finally():
    live = Live()
    with pytest.raises(SystemExit):
        with hold.using_live("hands panel make"):
            with hold.undo(live, "the tempo", "song.tempo = 120"):
                os.kill(os.getpid(), signal.SIGTERM)
                signal.raise_signal(signal.SIGTERM)       # delivered before the next line, whatever the platform
    assert live.ran == ["song.tempo = 120"] and hold.pending() == []
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL or callable(signal.getsignal(signal.SIGTERM))


def test_a_damaged_notes_file_reads_as_no_notes():
    (config.rig().data_dir / hold.UNDO).write_text('[{"what": "x", "code": "y"}, 3, {"code": 5}')
    assert hold.pending() == []
    (config.rig().data_dir / hold.UNDO).write_text('[{"what": "x", "code": "y"}, 3, {"code": 5}]')
    assert [e["code"] for e in hold.pending()] == ["y"]


def test_the_rig_check_sees_notes_and_the_soft_reset_runs_them(monkeypatch):
    monkeypatch.setattr(rig, "live_running", lambda: True)
    monkeypatch.setattr(rig, "system_audio_ok", lambda *a, **k: True)
    monkeypatch.setattr(rig, "open_dialogs", lambda: 0)
    monkeypatch.setattr(rig, "set_window", lambda: "test_set")
    monkeypatch.setattr(rig, "log_since", lambda *a: [])

    class Lom(Live):
        def execute(self, code):
            if code == hold.SET_PATH:
                return McpResult("ok", self.set)
            self.ran.append(code)
            if code == "result = 1":
                return McpResult("ok", 1)
            if "render_tracks" in code:
                return McpResult("ok", {"playing": False, "recording": False, "render_tracks": 0})
            return McpResult("ok", 0)

    live = Lom()
    hold.note("the faders of a grid", "faders()")
    h = rig.check(live, play=False)
    assert h.undone == 1 and h.needs == "soft" and "left 1 thing(s) in Live to put back" in h.problems[0]
    report = rig.Report()
    rig.soft_reset(live, report)
    assert "faders()" in live.ran and report.steps[0] == "put back the faders of a grid, left by an interrupted command"
    assert rig.check(live, play=False).needs == "nothing"


def test_a_reset_reports_instead_of_raising(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("the disk is full")
    monkeypatch.setattr(rig, "_reset", boom)
    monkeypatch.setattr(rig, "check", lambda *a, **k: rig.Health(needs="restart", problems=["Live is not running"]))
    report = rig.reset(client=Live())
    assert not report.ok and report.steps == ["the reset stopped (RuntimeError: the disk is full)"]
    assert rig.reset(set_path=config.rig().sets_dir / "nope.als", client=Live()).needs_you[0].startswith("there is no Live set at")


def test_replacing_a_panel_with_a_bad_spec_keeps_the_one_it_had(tmp_path, monkeypatch):
    from test_panel import MIX, SPEC, bars_recorder, mix_live, recorder
    monkeypatch.setattr("time.sleep", lambda s: None)
    live = mix_live()
    live.song.create_audio_track = lambda i: None
    panel.make(live, SPEC, tmp_path, recorder=recorder([]))
    mix.make(live, MIX, tmp_path, recorder=bars_recorder([]))
    kick = next(t for t in live.song.tracks if t.name == "bus-kick")
    kick.devices[0].parameters[1].value = 11.0                       # the user's own setting of the Drive
    names = [t.name for t in live.song.tracks]
    with pytest.raises(panel.PanelError, match="no parameter 'Cutof'"):
        panel.make(live, {**SPEC, "controls": ["Cutof"]}, tmp_path, replace=True, recorder=recorder([]))
    with pytest.raises(panel.PanelError, match="no parameter 'Driv3'"):
        mix.make(live, {**MIX, "devices": [{**MIX["devices"][0], "controls": ["Driv3"]}]}, tmp_path, replace=True, recorder=bars_recorder([]))
    assert [t.name for t in live.song.tracks] == names
    assert [(d.name, d.parameters[0].value, d.parameters[1].value) for d in kick.devices] == [("mix buses Saturator", 1.0, 11.0)]
    assert hold.pending() == []
    mix.make(live, MIX, tmp_path, replace=True, recorder=bars_recorder([]))     # and a good one does replace it
    assert [(d.name, round(d.parameters[1].value)) for d in kick.devices] == [("mix buses Saturator", 6)]


def test_a_live_that_is_silent_because_a_command_is_rendering_is_busy_not_broken(monkeypatch):
    monkeypatch.setattr(rig, "live_running", lambda: True)
    monkeypatch.setattr(rig, "system_audio_ok", lambda *a, **k: True)
    monkeypatch.setattr(rig, "open_dialogs", lambda: 0)
    monkeypatch.setattr(rig, "set_window", lambda: "test_set")
    monkeypatch.setattr(rig, "log_since", lambda *a: [])
    live = Live()
    live.down = True
    assert rig.check(live, play=False).needs == "restart"
    monkeypatch.setattr(hold, "holder", lambda: {"pid": 1, "what": "hands panel grid"})
    h = rig.check(live, play=False)
    assert h.needs == "wait" and h.problems == ["Live is busy with `hands panel grid`; check again when it is done"]


def test_a_note_for_one_set_is_never_run_on_another():
    live = Live()
    hold.on_set("/sets/HW002.als")
    hold.note("the faders of a grid", "faders()")
    live.set = "/sets/Other song.als"
    assert hold.replay(live) == ["dropped a note to put back the faders of a grid: it was for HW002, and Other song is open now"]
    assert live.ran == [] and hold.pending() == []
    hold.on_set("")
