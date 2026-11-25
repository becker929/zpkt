"""mixset.py (the mix set and mix-2 batches) and spectral.py's set state: the LOM steps they send, pinned as goldens
recorded from a stand-in for LiveOps, and the pure parts (channels, grid points, the page's catalog)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from samples import ARRANGEMENT, LOOPS, RecordingLive, assert_golden, relative, write_data

import mixset
import spectral


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = write_data(tmp_path / "arranger")
    monkeypatch.setattr(mixset, "DATA", d)
    monkeypatch.setattr(mixset, "MIX2", d / "mix2")
    return d


def test_channels():
    assert mixset.channels(LOOPS, ARRANGEMENT) == [
        {"id": "kick", "title": "Kick", "group": "kick"},
        {"id": "p1-oh", "title": "P1 open", "group": "hats"},
        {"id": "splash", "title": "Splash", "group": "sfx"},
        {"id": "chord", "title": "Chord", "group": "sfx"},
        {"id": "fx-riser", "title": "Risers", "group": "fx"},
    ]


def test_points():
    req = {
        "params": [
            {"name": "Drive", "min": 0, "max": 12, "steps": 3, "unit": "dB"},
            {"name": "Type", "values": ["Analog Clip", "Soft Sine"]},
        ]
    }
    assert mixset.points(req) == [
        {"Drive": "0.0 dB", "Type": "Analog Clip"},
        {"Drive": "0.0 dB", "Type": "Soft Sine"},
        {"Drive": "6.0 dB", "Type": "Analog Clip"},
        {"Drive": "6.0 dB", "Type": "Soft Sine"},
        {"Drive": "12.0 dB", "Type": "Analog Clip"},
        {"Drive": "12.0 dB", "Type": "Soft Sine"},
    ]
    hz = mixset.points({"params": [{"name": "4 Frequency A", "min": 100, "max": 10000, "steps": 3, "unit": "Hz"}]})
    assert hz == [{"4 Frequency A": "100.0 Hz"}, {"4 Frequency A": "1000.0 Hz"}, {"4 Frequency A": "10000.0 Hz"}]
    ratio = mixset.points({"params": [{"name": "Ratio", "min": 1, "max": 4, "steps": 9, "unit": ":1"}]})
    assert [p["Ratio"] for p in ratio] == ["1.0", "1.6", "2.2", "2.8", "3.4", "4.0"]  # steps capped at 6
    assert len(mixset.points({"params": [{"name": "Q", "min": 0, "max": 1, "steps": 1}]})) == 2


def test_catalog(data):
    assert_golden("mixset-catalog", mixset.catalog())


def test_build(data, monkeypatch):
    live = RecordingLive()
    monkeypatch.setattr(mixset, "lo", lambda: live)
    mixset.build()
    assert_golden("mixset-build", relative(live.calls, data))


def test_apply_mix(data):
    live = RecordingLive(
        tracks=[
            "Kick bus",
            "Hats bus",
            "Chord and splash bus",
            "Transitions bus",
            "kick",
            "p1-oh",
            "splash",
            "chord",
            "fx-riser",
        ]
    )
    mixset.apply_mix(live, ARRANGEMENT, mixset.channels(LOOPS, ARRANGEMENT))
    assert_golden("mixset-apply-mix", relative(live.calls, data))


def test_run_request(data, monkeypatch):
    live = RecordingLive(
        tracks=[
            "Kick bus",
            "Hats bus",
            "Chord and splash bus",
            "Transitions bus",
            "kick",
            "p1-oh",
            "splash",
            "chord",
            "fx-riser",
        ]
    )
    louder = iter([-14.0, -12.0, -13.5])
    monkeypatch.setattr(mixset, "to_flac", lambda wav, flac, skip=0.0: (flac.write_bytes(b"flac"), wav.unlink()))
    monkeypatch.setattr(mixset, "lufs", lambda path: next(louder))
    req = {
        "id": "b1114-101010",
        "status": "queued",
        "made": 5.0,
        "target": "bus-kick",
        "device": "Saturator",
        "params": [{"name": "Drive", "min": 0, "max": 12, "steps": 2, "unit": "dB"}],
        "bars": [17, 24],
    }
    f = data / "mix2" / "requests" / "b1114-101010.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(req))
    mixset.run_request(live, f)
    got = json.loads(f.read_text())
    assert got["started"] > 0 and got["finished"] >= got["started"]
    got["started"] = got["finished"] = 0
    assert_golden("mixset-run-request-status", got)
    assert_golden("mixset-run-request", relative(live.calls, data))


def test_worker_marks_a_failed_batch(data, monkeypatch):
    live = RecordingLive()
    monkeypatch.setattr(mixset, "lo", lambda: live)

    def boom(L, path):
        raise RuntimeError("Live said no")

    monkeypatch.setattr(mixset, "run_request", boom)
    folder = data / "mix2" / "requests"
    folder.mkdir(parents=True)
    (folder / "b2.json").write_text(json.dumps({"id": "b2", "status": "queued", "made": 2}))
    (folder / "b1.json").write_text(json.dumps({"id": "b1", "status": "ready", "made": 1}))
    with pytest.raises(RuntimeError):
        mixset.worker()
    assert json.loads((folder / "b2.json").read_text()) == {
        "id": "b2",
        "status": "failed",
        "made": 2,
        "error": "Live said no",
    }


def test_worker_stops_when_queue_is_empty(data, monkeypatch, capsys):
    monkeypatch.setattr(mixset, "lo", lambda: RecordingLive())
    (data / "mix2" / "requests").mkdir(parents=True)
    mixset.worker()
    assert "queue empty" in capsys.readouterr().out


def test_worker_refuses_another_set(data, monkeypatch):
    monkeypatch.setattr(mixset, "lo", lambda: RecordingLive(front="HW002_121_pp_loops"))
    with pytest.raises(SystemExit, match="HW002_121_pp_mix is not in front"):
        mixset.worker()


def test_spectral_state(data):
    live = RecordingLive(
        tracks=[
            "Kick bus",
            "Hats bus",
            "Chord and splash bus",
            "Transitions bus",
            "kick",
            "p1-oh",
            "splash",
            "chord",
            "fx-riser",
        ]
    )
    fixes = [
        {
            "id": "b",
            "parts": [
                {"target": "kick", "device": "gain", "values": {"dB": 1.0}},
                {"target": "bus-sfx", "device": "EQ Eight", "values": {"2 Gain A": "-2.0 dB"}},
            ],
        },
        {"id": "c", "target": "main", "device": "Glue Compressor", "values": {"Threshold": "-10.0 dB"}},
    ]
    spectral.state(live, ARRANGEMENT, mixset.channels(LOOPS, ARRANGEMENT), fixes)
    assert_golden("spectral-state", relative(live.calls, data))
    assert ARRANGEMENT["spectral"][0]["id"] == "a"  # the arrangement given is not changed


def test_spectral_windows():
    assert spectral.windows(24.0, 1.5) == {"build": (0.0, 24.0), "drop": (24.0, 48.0), "drop2": (48.0, 60.0)}
    assert spectral.region_of(50) == "sub" and spectral.region_of(8000) == "air"
    assert len(spectral.CENTRES) == 48 and spectral.BARS == (1, 40)
