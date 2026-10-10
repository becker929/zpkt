"""hands.live.timeops: the selection call and the song-end checks, against a fake Live."""
from __future__ import annotations

import pytest

from hands.live import session, timeops, ui
from hands.live.session import Guard
from hands.live.transport import McpResult, Transport


class FakeArrangement(Transport):
    """Answers song.last_event_time from a list of ends, and the clip count from another."""

    def __init__(self, ends, clips=()):
        self.ends, self.clips, self.calls = list(ends), list(clips), []

    def execute(self, code):
        self.calls.append(code)
        if "last_event_time" in code:
            return McpResult("ok", self.ends.pop(0))
        if "arrangement_clips" in code:
            return McpResult("ok", self.clips.pop(0))
        compile(code, "<lom>", "exec")
        return McpResult("ok", None)


@pytest.fixture
def menus(monkeypatch):
    """Edit-menu clicks, recorded; items in `disabled` never enable."""
    clicked, disabled = [], set()

    def menu(name, item, tries=6, wait_s=0.4):
        if item in disabled:
            return False
        clicked.append(item)
        return True
    monkeypatch.setattr(ui, "menu", menu)
    monkeypatch.setattr(timeops.time, "sleep", lambda s: None)
    monkeypatch.setattr(session.time, "sleep", lambda s: None)
    return clicked, disabled


def test_select_is_one_lom_call_then_select_loop(menus):
    clicked, _ = menus
    live = FakeArrangement([])
    timeops.select(live, 8, 32)
    assert len(live.calls) == 1
    code = live.calls[0]
    assert "song.loop_start = 8.0" in code and "song.loop_length = 32.0" in code and 'focus_view("Arranger")' in code
    assert clicked == ["Select Loop"]


def test_select_stops_when_select_loop_stays_disabled(menus):
    _, disabled = menus
    disabled.add("Select Loop")
    with pytest.raises(Guard, match="Select Loop stayed disabled"):
        timeops.select(FakeArrangement([]), 8, 32)


def test_delete_checks_the_song_end(menus):
    clicked, _ = menus
    assert timeops.delete(FakeArrangement([200.0, 168.0]), 40, 32) == -32.0
    assert clicked == ["Select Loop", "Delete Time"]
    with pytest.raises(Guard, match="moved -31.5 beats, expected -32"):
        timeops.delete(FakeArrangement([200.0, 168.5]), 40, 32)
    assert timeops.delete(FakeArrangement([200.0, 168.5]), 40, 32, tol=1.0) == -31.5


def test_duplicate_by_end_and_clip_count(menus):
    live = FakeArrangement([40.0, 72.0], clips=[12, 24])
    assert timeops.duplicate(live, 8, 32) == 32.0
    live = FakeArrangement([40.0, 72.5], clips=[12, 24])   # a breakpoint past the region moved the end
    assert timeops.duplicate(live, 8, 32, end=72.5, clips_from=8) == 32.5
    live = FakeArrangement([40.0, 72.0], clips=[12, 23])
    with pytest.raises(Guard, match="23 clips after 8, expected 24"):
        timeops.duplicate(live, 8, 32, end=72.0, clips_from=8)


def test_copy_and_paste(menus):
    clicked, _ = menus
    assert timeops.copy(FakeArrangement([100.0, 100.0]), 0, 4) == 0.0
    assert timeops.paste(FakeArrangement([100.0, 104.0]), 36, 4) == 4.0
    assert clicked == ["Select Loop", "Copy Time", "Select Loop", "Paste Time"]


def test_a_disabled_edit_is_retried_then_stops(menus):
    clicked, disabled = menus
    disabled.add("Delete Time")
    with pytest.raises(Guard, match="Delete Time stayed disabled at 8\\+4"):
        timeops.delete(FakeArrangement([20.0]), 8, 4)
    assert clicked == ["Select Loop"] * 4


def test_check_end_alone():
    assert timeops.check_end("Paste Time", "0+4", 10.0, 14.0, delta=4.0) == 4.0
    with pytest.raises(Guard, match="ends at 13, expected 14"):
        timeops.check_end("Duplicate Time", "0+4", 10.0, 13.0, end=14.0)
