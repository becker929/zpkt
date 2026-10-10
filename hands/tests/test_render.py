"""hands.live.render.export with the AppleScript, the GUI and the time selection faked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hands.cli import app
from hands.live import render, session, timeops, ui
from hands.live.session import Guard
from hands.live.transport import MockTransport


class FakeExportDialog:
    """Plays export_audio.applescript: per try, write the file or not, then succeed or fail."""

    def __init__(self, monkeypatch, tries, dialogs=()):
        self.tries, self.dialogs, self.calls = list(tries), list(dialogs), []
        self.selected, self.closed, self.parked = [], 0, 0
        monkeypatch.setattr(ui, "osa_file", self.osa_file)
        monkeypatch.setattr(ui, "dialogs", lambda: self.dialogs.pop(0) if self.dialogs else 0)
        monkeypatch.setattr(ui, "close_dialogs", self.close)
        monkeypatch.setattr(ui, "park_cursor", self.park)
        monkeypatch.setattr(timeops, "select", lambda client, start, length: self.selected.append((start, length)))
        monkeypatch.setattr(render.time, "sleep", lambda s: None)
        monkeypatch.setattr(session.time, "sleep", lambda s: None)

    def osa_file(self, path, *args, timeout):
        self.calls.append((path, args))
        writes, fails = self.tries.pop(0)
        if writes:
            Path(args[0]).write_bytes(b"RIFF")
        if fails:
            raise ui.UiError("System Events got an error: Can't get window \"Export Audio/Video\" (-1728)")
        return args[0]

    def close(self):
        self.closed += 1

    def park(self):
        self.parked += 1


def test_export_selects_the_range_runs_the_script_and_parks(monkeypatch, tmp_path):
    fake = FakeExportDialog(monkeypatch, [(True, False)], dialogs=[1, 1, 0])
    out = tmp_path / "renders" / "all.wav"
    assert render.export(MockTransport(), out, 0.0, 40.0) == [out]
    assert fake.selected == [(0.0, 40.0)]
    assert fake.calls == [(render.SCRIPT, (str(out), "WAV", "32", "44100", "0", "Main", "-1"))]
    assert fake.parked == 1 and render.SCRIPT.exists()


def test_without_a_range_live_keeps_its_own(monkeypatch, tmp_path):
    fake = FakeExportDialog(monkeypatch, [(True, False)])
    render.export(MockTransport(), tmp_path / "desk.aif", bits=24)
    assert fake.selected == [] and fake.calls[0][1][1:3] == ("AIFF", "24")


def test_a_script_error_after_the_file_landed_is_a_success(monkeypatch, tmp_path, rig):
    FakeExportDialog(monkeypatch, [(True, True)], dialogs=[1, 0])
    assert render.export(MockTransport(), tmp_path / "all.wav", 0.0, 8.0) == [tmp_path / "all.wav"]
    row = json.loads((rig.data_dir / "bench.jsonl").read_text())
    assert row["step"] == "export_script_error_files_ok" and row["files"] == 1


def test_retries_only_when_nothing_was_written(monkeypatch, tmp_path):
    fake = FakeExportDialog(monkeypatch, [(False, True), (True, False)])
    assert render.export(MockTransport(), tmp_path / "all.wav", 0.0, 8.0) == [tmp_path / "all.wav"]
    assert fake.closed == 1 and len(fake.calls) == 2 and len(fake.selected) == 2


def test_nothing_written_stops_and_still_parks(monkeypatch, tmp_path):
    fake = FakeExportDialog(monkeypatch, [(False, True), (False, True)])
    with pytest.raises(Guard, match="nothing written after 2 tries"):
        render.export(MockTransport(), tmp_path / "all.wav")
    assert fake.parked == 1


def test_a_dialog_left_open_stops(monkeypatch, tmp_path):
    FakeExportDialog(monkeypatch, [(False, True)], dialogs=[1])
    with pytest.raises(Guard, match="dialog stayed open"):
        render.export(MockTransport(), tmp_path / "all.wav")


def test_refuses_an_existing_target_and_bad_arguments(monkeypatch, tmp_path):
    fake = FakeExportDialog(monkeypatch, [])
    (tmp_path / "all Kick.wav").write_bytes(b"old")
    with pytest.raises(Guard, match="target not empty"):
        render.export(MockTransport(), tmp_path / "all.wav")
    with pytest.raises(ValueError, match="writes"):
        render.export(MockTransport(), tmp_path / "x.mp3")
    with pytest.raises(ValueError, match="both"):
        render.export(MockTransport(), tmp_path / "y.wav", 0.0)
    assert fake.calls == []


def test_cli_export_puts_bare_names_in_the_renders_folder(monkeypatch, rig):
    seen = {}

    def export(client, out, start, length, **kw):
        seen.update(out=out, start=start, length=length, **kw)
        return [out]
    monkeypatch.setattr(render, "export", export)
    result = CliRunner().invoke(app, ["live", "export", "take.wav", "--start", "8", "--length", "32", "--bits", "24"])
    assert result.exit_code == 0 and result.stdout.strip() == str(rig.renders_dir / "take.wav")
    assert seen == {"out": rig.renders_dir / "take.wav", "start": 8.0, "length": 32.0, "mode": "Main",
                    "bits": 24, "sample_rate": 44100}
    bad = CliRunner().invoke(app, ["live", "export", "take.wav", "--start", "8"])
    assert bad.exit_code == 2
