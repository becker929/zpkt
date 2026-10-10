"""hands.live.session against a fake GUI (ui) and a mock LOM; nothing here touches Live."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime

import pytest

from hands.live import session, ui
from hands.live.session import Guard
from hands.live.transport import McpResult, MockTransport, Transport

DOWN = McpResult(status="error", error="Cannot reach Ableton: refused")


class Down(Transport):
    def execute(self, code):
        return DOWN


class FakeGui:
    """What ui would say: a front window (or None while loading) and the open dialogs."""

    def __init__(self, monkeypatch, fronts, dialogs=0, save_enabled=True, on_save=None):
        self.fronts, self.n_dialogs, self.save_enabled, self.on_save = list(fronts), dialogs, save_enabled, on_save
        self.clicks, self.opened = [], []
        monkeypatch.setattr(ui, "front_title", self.front_title)
        monkeypatch.setattr(ui, "dialogs", lambda: self.n_dialogs)
        monkeypatch.setattr(ui, "menu_enabled", lambda menu, item: self.save_enabled)
        monkeypatch.setattr(ui, "menu", self.menu)
        monkeypatch.setattr(session.subprocess, "run", self.run)
        monkeypatch.setattr(session.time, "sleep", lambda s: None)

    def front_title(self):
        front = self.fronts[0] if len(self.fronts) == 1 else self.fronts.pop(0)
        if front is None:
            raise ui.UiError("Can't get window 1 (-1728)")
        return front

    def menu(self, menu, item, tries=6):
        self.clicks.append(f"{menu} > {item}")
        if self.on_save:
            self.on_save()
        return True

    def run(self, argv, **kw):
        self.opened.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_check_passes_and_returns_the_front_set(monkeypatch):
    FakeGui(monkeypatch, ["test_kit_c8x4"])
    lom = MockTransport()
    assert session.check(lom, "render:start", expect_front="test_kit_c8x4") == "test_kit_c8x4"
    assert lom.calls == ["result = 1"]


@pytest.mark.parametrize("fronts, dialogs, kw, message", [
    (["test_a"], 1, {}, "1 dialog"),
    (["test_a"], 0, {"expect_front": "test_b"}, "expected 'test_b'"),
    (["Anthony's mix"], 0, {}, "not one of ours"),
    ([None], 0, {}, "cannot read Live's windows"),
])
def test_check_stops_on_surprises(monkeypatch, fronts, dialogs, kw, message):
    FakeGui(monkeypatch, fronts, dialogs=dialogs)
    with pytest.raises(Guard, match=message):
        session.check(MockTransport(), "step", **kw)


def test_check_needs_the_lom(monkeypatch):
    FakeGui(monkeypatch, ["Anthony's mix"])
    assert session.check(MockTransport(), "desk", ours=False) == "Anthony's mix"
    with pytest.raises(Guard, match="does not answer LOM"):
        session.check(MockTransport([DOWN]), "desk", ours=False)


def test_open_set_waits_for_the_window_then_the_lom(monkeypatch, rig):
    for name in ("test_old", "test_new"):
        rig.set_path(name).write_bytes(b"als")
    path = rig.set_path("test_old")
    gui = FakeGui(monkeypatch, ["test_old", "test_old", None, None, "test_new"],
                  on_save=lambda: os.utime(path, ns=(0, path.stat().st_mtime_ns + 10**9)))
    lom = MockTransport([DOWN, DOWN])
    assert session.open_set(lom, "test_new") >= 0.0
    assert gui.clicks == ["File > Save Live Set"]                     # the old set was saved first
    assert gui.opened == [["open", "-a", rig.live_app, str(rig.set_path("test_new"))]]
    assert lom.calls == ["result = 1"] * 3                             # polled until it answered


def test_open_set_refuses_to_reopen_the_front_set(monkeypatch, rig):
    rig.set_path("test_batch").write_bytes(b"als")
    gui = FakeGui(monkeypatch, ["test_batch"])
    with pytest.raises(Guard, match="would not reload"):
        session.open_set(MockTransport(), "test_batch")
    assert gui.opened == []
    with pytest.raises(Guard, match="no set"):
        session.open_set(MockTransport(), "test_missing")


def test_open_set_stops_if_the_lom_never_answers(monkeypatch, rig):
    rig.set_path("test_new").write_bytes(b"als")
    FakeGui(monkeypatch, [None, "test_new"])
    with pytest.raises(Guard, match="LOM did not answer"):
        session.open_set(Down(), "test_new", save_current=False, timeout_s=0.01)


def test_save(monkeypatch, rig):
    path = rig.set_path("test_kit")
    path.write_bytes(b"als")
    FakeGui(monkeypatch, ["test_kit"], save_enabled=False)
    assert session.save() is False                                     # nothing to save
    FakeGui(monkeypatch, ["test_kit"], on_save=lambda: os.utime(path, ns=(0, 1)))
    assert session.save("test_kit") is True
    FakeGui(monkeypatch, ["test_kit"])                                 # clicked, file never changes
    with pytest.raises(Guard, match="not rewritten"):
        session.save(timeout_s=0.01)
    FakeGui(monkeypatch, ["test_other"])
    with pytest.raises(Guard, match="not the front set"):
        session.save("test_kit")


def test_copy_set(rig):
    rig.set_path("test_src").write_bytes(b"als data")
    assert session.copy_set("test_src", "test_dst").read_bytes() == b"als data"


def test_audio_clock_compares_positions():
    assert session.audio_clock_ok(MockTransport([McpResult("ok", 4.0), McpResult("ok", 7.2)]), wait_s=0)
    assert not session.audio_clock_ok(MockTransport([McpResult("ok", 0.0), McpResult("ok", 0.0)]), wait_s=0)


def test_other_agent_active_reads_the_live_log(rig):
    log = rig.live_log
    log.write_text("2026-10-10T07:00:00.000001: info: RemoteScriptMessage: (AbletonLiveMCP) AbletonLiveMCP: connected: 127.0.0.1:5\n"
                   "2026-10-10T07:15:11.464529: info: MemoryUsage: V: 508 GB\n")
    assert session.last_lom_connection() == datetime(2026, 10, 10, 7, 0, 0, 1)
    assert session.other_agent_active(now=datetime(2026, 10, 10, 7, 4))
    assert not session.other_agent_active(now=datetime(2026, 10, 10, 7, 6))
    log.write_text("2026-10-10T07:15:11.464529: info: MemoryUsage: V: 508 GB\n")
    assert not session.other_agent_active()


def test_top_values():
    assert [session._gb(v) for v in ("1536M", "2G+", "512K", "0B")] == [1.5, 2.0, 0.0, 0.0]
