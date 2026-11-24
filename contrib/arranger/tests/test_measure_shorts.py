"""measure.py sums an arrangement the way the arranger page plays it; shorts.py writes the canonical tab."""

from __future__ import annotations

import json
from pathlib import Path

import measure
import numpy as np
import pytest
import shorts
import soundfile as sf

RATE = 100  # a tiny rate keeps the made-up audio small: one bar is 150 samples
BAR = 150


def stereo(values: list[float], n: int) -> np.ndarray:
    """`n` samples per value, both channels."""
    x = np.repeat(np.array(values, dtype="float32"), n)
    return np.stack([x, x], 1)


@pytest.fixture
def loops(tmp_path: Path) -> measure.Loops:
    (tmp_path / "audio").mkdir()
    sf.write(tmp_path / "audio" / "loop.wav", stereo([0.1, 0.2], BAR), RATE, subtype="FLOAT")  # bar 1: 0.1, bar 2: 0.2
    sf.write(tmp_path / "audio" / "tail.wav", stereo([0.05], BAR * 2), RATE, subtype="FLOAT")
    sf.write(tmp_path / "audio" / "hit.wav", stereo([0.5], BAR // 2), RATE, subtype="FLOAT")
    index = {"rate": RATE, "barSeconds": 1.5, "clips": [
        {"id": "l", "lane": "a", "kind": "loop", "bars": 2, "file": "loop.wav", "tail": "tail.wav"},
        {"id": "h", "lane": "b", "kind": "once", "bars": 1, "file": "hit.wav"}]}
    (tmp_path / "loops.json").write_text(json.dumps(index))
    return measure.Loops(tmp_path)


def test_render_sums_as_the_page_plays(loops):
    arr = {"bars": 4, "regions": [{"lane": "a", "clip": "l", "start": 0, "len": 3, "off": 1},
                                  {"lane": "b", "clip": "h", "start": 2, "len": 1}]}
    x = measure.render(arr, loops)[:, 0]
    bars = [x[i * BAR : (i + 1) * BAR] for i in range(4)]
    assert np.allclose(bars[0], 0.2 + 0.05)  # entered one bar in; the tail of bar 3 has come round from the end
    assert np.allclose(bars[1], 0.1)
    assert np.allclose(bars[2][: BAR // 2], 0.2 + 0.5) and np.allclose(bars[2][BAR // 2 :], 0.2)
    assert np.allclose(bars[3], 0.05)  # nothing follows the loop on its lane: its tail plays


def test_render_mutes_and_follow(loops):
    arr = {"bars": 4, "mutes": ["b"], "regions": [{"lane": "a", "clip": "l", "start": 0, "len": 2},
                                                  {"lane": "a", "clip": "l", "start": 2, "len": 2},
                                                  {"lane": "b", "clip": "h", "start": 0, "len": 1}]}
    x = measure.render(arr, loops)[:, 0]
    assert np.allclose(x[:BAR], 0.1)  # the hit is muted; the last region is followed by the first (the page loops)
    assert np.allclose(x[2 * BAR : 3 * BAR], 0.1)  # the first region is followed by the second: no tail


def test_reports(loops):
    assert loops.bar == BAR
    assert len(measure.clip_report(loops)) == 2
    arr = {"name": "Try", "bars": 4, "regions": [{"lane": "a", "clip": "l", "start": 0, "len": 4}]}
    lines = measure.arrangement_report(arr, loops)
    assert lines[0].startswith("Try   peak 0.20") and lines[1] == "  bars         1-4 "


def test_write_shorts(tmp_path, capsys):
    clips = [{"id": clip, "lane": lane} for lane, clip, *_ in shorts.SHORTS["8d2a2"][1]]
    (tmp_path / "loops.json").write_text(json.dumps({"clips": clips}))
    shorts.write_shorts(tmp_path, [])
    got = json.loads((tmp_path / "arrangements" / "short-8d2a2.json").read_text())
    assert set(got) == {"name", "bars", "regions", "mutes", "saved"}
    assert got["bars"] == 40 and got["mutes"] == [] and got["name"] == "8d2a2 Fast build, slow peak"
    assert got["regions"][0] == {"lane": "break-horn", "clip": "break-horn-a", "start": 0, "len": 8, "off": 0}
    assert "short-8d2a2:" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no such short"):
        shorts.write_shorts(tmp_path, ["9z"])
