"""zpkt.live.monitor_tracks on FakeLive: the monitor tracks are added, one is heard, Main's desk devices are bypassed
and put back."""

from __future__ import annotations

import wave
from pathlib import Path

from zpkt.live import monitor_tracks as M
from zpkt.live.testing import FakeLive, fake_set, hw002_like


def wavs(tmp_path: Path) -> dict[str, tuple[Path, float]]:
    want = {}
    for name, beat in (("mon A", 0.0), ("mon B", 0.0), ("mon C1", 64.0)):
        f = tmp_path / f"{name[4:]}.wav"
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(b"\x00\x00" * 441)
        want[name] = (f, beat)
    return want


def devices_on(live: FakeLive) -> dict[str, float]:
    return {d.name: d.parameters[0].value for d in live.song.master_track.devices if d.name in M.MAIN_DEVICES}


def bare_set():
    return fake_set(
        {"tracks": [{"name": "kick"}], "main": {"devices": [{"device": "Utility", "name": "desk Utility"}]}}
    )


def test_ensure_adds_the_tracks_and_clips_once(tmp_path):
    with FakeLive(bare_set()) as live:
        want = wavs(tmp_path)
        assert M.missing(live, want) == list(want)
        M.ensure(live, want, log=lambda *a: None, pause=lambda s: None)
        assert M.missing(live, want) == []
        again = len(live.song.tracks)
        M.ensure(live, want, log=lambda *a: None, pause=lambda s: None)
        assert len(live.song.tracks) == again
        names = {t.name: t for t in live.song.tracks}
        assert names["mon A"].mute is True and len(list(names["mon C1"].arrangement_clips)) == 1
        assert [row[0] for row in M.status(live)] == list(want)


def test_ensure_says_which_file_is_missing(tmp_path):
    import pytest

    with FakeLive(hw002_like()) as live, pytest.raises(FileNotFoundError, match="run analyze.py"):
        M.ensure(live, {"mon A": (tmp_path / "nope.wav", 0.0)}, log=lambda *a: None, pause=lambda s: None)


def test_hearing_a_track_solos_it_and_bypasses_main_then_w_puts_main_back(tmp_path):
    with FakeLive(hw002_like()) as live:
        want = wavs(tmp_path)
        M.ensure(live, want, log=lambda *a: None, pause=lambda s: None)
        before = devices_on(live)
        assert before and all(v == 1.0 for v in before.values())
        out = M.switch(live, "A", "C1", -1.5, None)
        assert "error" not in out and out["main_saved"] == before
        tracks = {t.name: t for t in live.song.tracks}
        assert tracks["mon A"].solo and not tracks["mon A"].mute and tracks["mon B"].mute
        assert set(devices_on(live).values()) == {0.0}
        out = M.switch(live, "C", "C1", 0.0, out["main_saved"])  # a reference: another track, same bypass
        tracks = {t.name: t for t in live.song.tracks}
        assert tracks["mon C1"].solo and tracks["mon A"].mute and not tracks["mon A"].solo
        out = M.switch(live, "W", "C1", 0.0, out["main_saved"])
        assert out == {"main_saved": None}
        assert devices_on(live) == before
        assert not any(t.solo or not t.mute for t in live.song.tracks if t.name.startswith("mon "))


def test_a_missing_monitor_track_is_an_error_not_a_change(tmp_path):
    with FakeLive(bare_set()) as live:
        before = devices_on(live)
        out = M.switch(live, "B", "C1", 0.0, None)
        assert out["error"] == M.MISSING and out["main_saved"] is None
        assert devices_on(live) == before


def test_the_monitor_track_for_a_slot():
    assert (
        M.track_name("A", "C2") == "mon A" and M.track_name("C", "C2") == "mon C2" and M.track_name("W", "C2") is None
    )


def test_remove_deletes_every_monitor_track(tmp_path):
    with FakeLive(hw002_like()) as live:
        M.ensure(live, wavs(tmp_path), log=lambda *a: None, pause=lambda s: None)
        M.remove(live, pause=lambda s: None)
        assert not [t for t in live.song.tracks if t.name.startswith("mon ")]
