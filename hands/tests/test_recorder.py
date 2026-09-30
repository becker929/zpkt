"""Recorder tests against a small fake Live — offline, no Ableton required."""
from __future__ import annotations

import wave

import pytest

import hands.recorder as recorder
from hands.transport import McpResult


class FakeLive:
    """Answers the recorder's LOM snippets by pattern; records every call."""

    def __init__(self, arrangement_clips: int = 0, armed: list[int] | None = None,
                 take_path: str | None = None) -> None:
        self.arrangement_clips = arrangement_clips
        self.armed = armed or []
        self.take_path = take_path
        self.calls: list[str] = []

    def execute(self, code: str) -> McpResult:
        self.calls.append(code)
        if "sum(len(t.arrangement_clips)" in code:
            return McpResult(status="ok", result=self.arrangement_clips)
        if "t.can_be_armed and t.arm" in code:
            return McpResult(status="ok", result=self.armed)
        if code == "len(song.tracks)":
            return McpResult(status="ok", result=5)
        if "input_routing_type.display_name" in code:
            return McpResult(status="ok", result="Resampling")
        if code == "song.tempo":
            return McpResult(status="ok", result=160.0)
        if "c.file_path for c in song.tracks[5].arrangement_clips" in code:
            return McpResult(status="ok", result=[self.take_path] if self.take_path else [])
        return McpResult(status="ok", result=None)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(recorder.time, "sleep", lambda s: None)


def _write_wav(path, seconds: float, rate: int = 44100) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(rate)
        w.writeframes(b"\x00" * 6 * int(seconds * rate))


def test_resampling_refuses_to_wipe_an_existing_arrangement(tmp_path) -> None:
    live = FakeLive(arrangement_clips=12)
    with pytest.raises(RuntimeError, match="record_arrangement"):
        recorder.record_via_resampling(live, "x.wav", 8.0, tmp_path)
    # It checked, then stopped: nothing was deleted or even played.
    assert not any("delete_clip" in c or "start_playing" in c for c in live.calls)


def test_record_arrangement_leaves_source_clips_and_restores_arm(tmp_path) -> None:
    take = tmp_path / "take.wav"
    _write_wav(take, 2.0)
    live = FakeLive(arrangement_clips=12, armed=[2], take_path=str(take))

    out = recorder.record_arrangement(live, "render.wav", 4.0, tmp_path / "out", tail_beats=0.0)

    assert out == str(tmp_path / "out" / "render.wav")
    assert (tmp_path / "out" / "render.wav").exists()
    assert not any("delete_clip" in c for c in live.calls)
    disarm = live.calls.index("song.tracks[2].arm = 0")
    record = live.calls.index("song.record_mode = True")
    assert disarm < record
    assert "song.back_to_arranger = False" in live.calls[:record]
    assert live.calls.index("song.delete_track(5)") > record
    assert live.calls[-1] == "song.tracks[2].arm = 1"


def test_record_arrangement_without_a_take_still_cleans_up(tmp_path) -> None:
    live = FakeLive(armed=[1], take_path=None)
    assert recorder.record_arrangement(live, "render.wav", 4.0, tmp_path) is None
    assert "song.delete_track(5)" in live.calls
    assert live.calls[-1] == "song.tracks[1].arm = 1"


def test_wav_export_reports_real_length(tmp_path, capsys) -> None:
    src = tmp_path / "take.wav"
    _write_wav(src, 6.7)
    recorder._export(str(src), str(tmp_path / "out.wav"), beats=8.0, tempo=130.0, want_wav=True)
    printed = capsys.readouterr().out
    assert "6.7s" in printed and "requested 3.7s" in printed
