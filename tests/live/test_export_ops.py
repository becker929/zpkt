"""zpkt.live.export and zpkt.live.ops: the export and Save As by the menu, with the GUI scripted (no osascript runs),
and the display-unit steps against FakeLive."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from zpkt.live import export as X
from zpkt.live import session, timeops, ui
from zpkt.live.ops import LiveOps
from zpkt.live.testing import FakeLive, fake_set, hw002_like


class Gui:
    """Live's dialogs and the Save panel, answering the AppleScript zpkt.live.export sends."""

    def __init__(self, panel_path: list[str], recent: list[list[str]] = ()):
        self.windows: list[str] = []
        self.panel = list(panel_path)  # the Save panel's folder chain, innermost first, ending "Macintosh HD"
        self.recent = [list(r) for r in recent]
        self.name = ""
        self.popups = {"Rendered Track Chooser": "All Tracks", "File Type": "AIFF", "Recording Bit Depth": "32",
                       "Sample Rate": "48000"}  # fmt: skip
        self.checks = {desc: "Off" for desc, _ in X._MAIN_OPTIONS} | {"Normalize": "On"}
        self.selection = (0.0, 4.0)
        self.saved: list[Path] = []
        self.on_save = lambda folder, name: None
        self.keys: list[str] = []
        self.clicked = ""

    def folder(self) -> Path:
        return Path("/" + "/".join(reversed(self.panel[:-1])))

    def items(self) -> list[str]:
        out = [*self.panel, "missing value", "Recent Places"]
        return out + [r[0] for r in self.recent]

    def ax(self, body: str, timeout: float = 30) -> str:
        if body == f"return value of {X._WHERE}":
            return self.panel[0]
        if "set out to {}" in body:
            return "|".join(self.items())
        if m := re.search(r"click menu item (\d+) of menu 1 of p$", body):
            k = int(m[1]) - 1
            if k < len(self.panel):
                self.panel = self.panel[k:]
            else:
                self.panel = self.recent[k - len(self.panel) - 2]
            return ""
        if m := re.search(r'set value of nf to "(.*)"', body):
            self.name = m[1]
            return ""
        if body == f"return value of {X._NAME}":
            return self.name
        if body == f'perform action "AXPress" of {X._SAVE}':
            self.windows.remove("Save")
            if "Export Audio/Video" in self.windows:
                self.windows.remove("Export Audio/Video")
            self.on_save(self.folder(), self.name)
            return ""
        if "exists sheet 1" in body:
            return "false"
        if m := re.search(r'pop up button of .* whose description is "(.*)"\)\nreturn v as text', body):
            return self.popups[m[1]]
        if m := re.fullmatch(r'click \(first pop up button of .* whose description is "(.*)"\)', body):
            self.clicked = m[1]
            return ""
        if m := re.search(r'whose name is "(.*)"\)', body):
            self.popups[self.clicked] = m[1]
            return ""
        if m := re.search(r'button of .* whose description is "(.*)"\)\nreturn v as text', body):
            return self.checks[m[1]]
        if m := re.fullmatch(r'click \(first button of .* whose description is "(.*)"\)', body):
            self.checks[m[1]] = "Off" if self.checks[m[1]] == "On" else "On"
            return ""
        if m := re.search(r'slider of .* whose description is "(.*)"\)', body):
            start, length = self.selection
            what = m[1]
            if "Rendered Sample" in what:  # Live 12.4 names them "... Rendered Audio File ..."
                raise ui.UiError("no such slider")
            part = what.split("(")[1].rstrip(")")
            if what.startswith("Length"):
                return str({"Bar": length // 4, "Beat": length % 4, "Sixteenths": 0.0}[part])
            return str({"Bar": start // 4 + 1, "Beat": start % 4 + 1}[part])
        if 'description is "Export")' in body:
            self.windows.append("Save")
            return ""
        if "keystroke" in body or "key code" in body or "frontmost" in body:
            self.keys.append(body)
            return ""
        raise AssertionError(f"unexpected AppleScript: {body!r}")

    def menu(self, menu: str, item: str, tries: int = 6, wait_s: float = 0.4) -> bool:
        if item == "Export Audio/Video...":
            self.windows.append("Export Audio/Video")
        elif item == "Save Live Set As...":
            self.windows.append("Save")
        return True


@pytest.fixture
def gui(monkeypatch, tmp_path):
    g = Gui(["elsewhere", "Users", "Macintosh HD"], recent=[[*reversed(tmp_path.parts[1:]), "Macintosh HD"]])
    monkeypatch.setattr(X, "ax", g.ax)
    monkeypatch.setattr(ui, "osa", lambda script, timeout=None: g.ax(script))
    monkeypatch.setattr(ui, "menu", g.menu)
    monkeypatch.setattr(ui, "windows", lambda: [(w, "AXDialog") for w in g.windows])
    monkeypatch.setattr(ui, "dialogs", lambda: len(g.windows))
    monkeypatch.setattr(ui, "front_title", lambda: "test_set")
    monkeypatch.setattr(ui, "close_dialogs", lambda: g.windows.clear())
    monkeypatch.setattr(ui, "park_cursor", lambda: g.keys.append("parked"))
    monkeypatch.setattr("time.sleep", lambda s: None)

    def select(client, start, length):
        g.selection = (start, length)

    monkeypatch.setattr(timeops, "select", select)
    return g


@pytest.fixture
def live():
    with FakeLive(hw002_like()) as fake:
        yield fake


def test_export_by_menu_sets_the_dialog_stages_the_file_and_moves_it(gui, live, tmp_path):
    staging, out = tmp_path / "staging", tmp_path / "renders" / "take.wav"
    staging.mkdir()
    gui.recent = [[*reversed(staging.parts[1:]), "Macintosh HD"]]  # a folder the panel has reached before
    gui.on_save = lambda folder, name: (folder / name).write_bytes(b"RIFF")
    got = X.export_by_menu(live, out, 8.0, 32.0, staging=staging, bits=24)
    assert got == out and out.read_bytes() == b"RIFF" and not (staging / "take.wav").exists()
    assert gui.popups == {"Rendered Track Chooser": "Main", "File Type": "WAV", "Recording Bit Depth": "24",
                          "Sample Rate": "44100"}  # fmt: skip
    assert gui.checks == {desc: "On" if on else "Off" for desc, on in X._MAIN_OPTIONS}
    assert gui.folder() == staging and gui.keys == ["parked"]  # reached by the Where popup, no keystrokes
    assert [c.code for c in live.calls][-1].startswith("song.loop_start = 0.0")
    with pytest.raises(session.Guard, match="already exists"):
        X.export_by_menu(live, out, 8.0, 32.0, staging=staging)


def test_export_by_menu_stops_on_a_wrong_range_and_closes_the_dialogs(gui, live, tmp_path, monkeypatch):
    monkeypatch.setattr(timeops, "select", lambda client, start, length: None)  # the selection did not take
    with pytest.raises(session.Guard, match=r"the dialog's range is start \(1.0, 1.0\)"):
        X.export_by_menu(live, tmp_path / "x.wav", 8.0, 32.0, staging=tmp_path)
    assert gui.windows == [] and gui.keys == ["parked"]


def test_export_by_menu_runs_the_session_guard_first(gui, live, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "dialogs", lambda: 1)
    with pytest.raises(session.Guard, match=r"export x\.wav: 1 dialog"):
        X.export_by_menu(live, tmp_path / "x.wav", 0.0, 4.0, staging=tmp_path)
    assert live.calls == [] or all("loop_start" not in c.code for c in live.calls)


def test_the_go_to_folder_sheet_types_the_path_unless_the_panel_is_there(gui, tmp_path):
    target = tmp_path / "sets"
    panel = X.SavePanel(reach="go_to_folder")
    gui.panel = ["sets", "Macintosh HD"]
    panel.go_to(target)
    assert gui.keys == []
    gui.panel = ["elsewhere", "Macintosh HD"]
    with pytest.raises(session.Guard, match="the Save panel is in 'elsewhere'"):
        panel.go_to(target)
    assert any(f'keystroke "{target}/"' in k for k in gui.keys)


def test_the_where_popup_climbs_to_a_parent_or_goes_through_recent_places(gui, tmp_path):
    panel = X.SavePanel()
    gui.panel = ["deeper", *reversed(tmp_path.parts[1:]), "Macintosh HD"]
    panel.go_to(tmp_path)
    assert gui.folder() == tmp_path
    gui.panel = ["elsewhere", "Macintosh HD"]
    panel.go_to(tmp_path)  # through the Recent Places entry
    assert gui.folder() == tmp_path
    gui.recent = []
    gui.panel = ["elsewhere", "Macintosh HD"]
    with pytest.raises(session.Guard, match="could not reach"):
        panel.go_to(tmp_path)


def test_save_as_makes_a_project_folder_or_saves_inside_one(gui, tmp_path):
    def save(folder, name):
        (folder / f"{name} Project").mkdir()
        (folder / f"{name} Project" / f"{name}.als").write_bytes(b"als")

    gui.on_save = save
    assert X.save_as(tmp_path, "test_seed") == tmp_path / "test_seed Project" / "test_seed.als"
    gui.on_save = lambda folder, name: (folder / f"{name}.als").write_bytes(b"als")
    gui.panel = ["elsewhere", "Macintosh HD"]
    assert X.save_as(tmp_path, "test_two", project=False) == tmp_path / "test_two.als"
    gui.on_save = lambda folder, name: None
    with pytest.raises(session.Guard, match="did not appear"):
        X.save_as(tmp_path, "test_never", timeout_s=0)


def test_export_chooses_the_method(monkeypatch, tmp_path):
    from zpkt.live import render

    seen = []
    monkeypatch.setattr(render, "export", lambda *a, **k: seen.append(("keys", a, k)) or [tmp_path / "a.wav"])
    monkeypatch.setattr(X, "export_by_menu", lambda *a, **k: seen.append(("menu", a, k)) or tmp_path / "b.wav")
    assert X.export(None, tmp_path / "a.wav", mode="All Individual Tracks") == [tmp_path / "a.wav"]
    assert X.export(None, tmp_path / "b.wav", 0.0, 4.0, method="menu", staging=tmp_path) == [tmp_path / "b.wav"]
    assert seen[1][2]["staging"] == tmp_path and seen[1][2]["bits"] == 32
    with pytest.raises(ValueError, match="needs a range"):
        X.export(None, tmp_path / "c.wav", method="menu", staging=tmp_path)
    with pytest.raises(ValueError, match="renders Main"):
        X.export(None, tmp_path / "c.wav", 0.0, 4.0, method="menu", staging=tmp_path, mode="Kick bus")


# --------------------------------------------------------------------------- LiveOps against FakeLive


def kick_eq(live: FakeLive):
    kick = next(t for t in live.song.tracks if t.name == "Kick bus")
    return {p.name: p for p in next(d for d in kick.devices if d.name == "desk EQ").parameters}


def test_setp_sets_shown_values_and_stops_on_what_the_device_lacks(live):
    from zpkt.live.inlive.tracks import track_expr

    ops = LiveOps(live)
    dev = f"next(d for d in {track_expr('Kick bus')}.devices if d.name == 'desk EQ')"
    ops.setp(dev, {"1 Frequency A": "120 Hz", "1 Gain A": "-3.0 dB", "1 Filter On A": 1})
    eq = kick_eq(live)
    assert str(eq["1 Frequency A"]).startswith("120") and str(eq["1 Gain A"]) == "-3.00 dB"
    with pytest.raises(session.Guard, match=r"\['Nope\?'\]"):
        ops.setp(dev, {"Nope": "1 dB"})
    assert not any(c.readbacks for c in live.calls)


def test_mixer_sets_volume_sends_and_pan_in_one_call(live):
    ops = LiveOps(live)
    n = len(live.calls)
    ops.mixer("song.tracks[0]", vol_db=-6.0, sends=(None, -12.0), pan=0.5)
    assert len(live.calls) == n + 1
    m = live.song.tracks[0].mixer_device
    assert str(m.volume) == "-6.0 dB" and m.sends[0].value == 0.0 and str(m.sends[1]) == "-12.0 dB"
    assert m.panning.value == 0.5


def test_params_devices_and_loading_from_the_browser():
    with FakeLive(fake_set({"tracks": [{"name": "p1", "type": "midi"}]})) as live:
        ops = LiveOps(live)
        ops.load_item("song.tracks[0]", "instruments", None, "Operator")
        assert ops.devices("song.tracks[0]") == ["Operator"]
        rows = ops.params("song.tracks[0].devices[0]", count=3)
        assert len(rows) == 3 and rows[0][0] == "Device On"
        assert ops.params("song.tracks[0].devices[0]", names=["Device On"]) == [rows[0]]


def test_an_export_needs_a_staging_folder(live, tmp_path):
    with pytest.raises(ValueError, match="no staging folder"):
        LiveOps(live).export(tmp_path / "x.wav", 0.0, 4.0)
