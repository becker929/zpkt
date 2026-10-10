"""Kokoro on FluidAudio through its pipe, with a stand-in helper (fake_fluid.py); and the fallback to ONNX.
The real helper is in test_engines.py (VOICE_ENGINES=1)."""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pytest

from voice import engines, fluid, tts

FAKE = Path(__file__).with_name("fake_fluid.py")


def helper(tmp_path: Path, mode: str = "ok") -> list[str]:
    return [sys.executable, str(FAKE), str(tmp_path / "requests.jsonl"), mode]


def requests(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]


@pytest.fixture
def engine(tmp_path):
    e = fluid.KokoroFluid(helper(tmp_path), models=tmp_path)
    yield e
    e.close()


def test_a_sentence_at_a_time_with_the_voice_and_speed(engine, tmp_path):
    chunks = list(engine.stream("First sentence here. And a second one!", "am_michael", 1.5))
    assert len(chunks) == 2 and all(rate == 24_000 and pcm.dtype == np.int16 for pcm, rate in chunks)
    sent = requests(tmp_path)
    assert [r["text"] for r in sent] == ["First sentence here.", "And a second one!"]
    assert all(r["op"] == "say" and r["voice"] == "am_michael" and r["speed"] == 1.5 for r in sent)
    # the padding (0.3 s before, 0.5 s after) is cut to 40 and 100 ms around the tone
    tone = int(len("First sentence here.") * 0.03 / 1.5 * 24_000)
    assert abs(len(chunks[0][0]) - (tone + int(0.14 * 24_000))) <= 240


def test_speed_is_kept_in_range(engine, tmp_path):
    list(engine.stream("Fast.", "af_heart", 9.0))
    assert requests(tmp_path)[-1]["speed"] == 2.0


def test_an_unspeakable_piece_is_skipped(engine):
    chunks = list(engine.stream("Hello there. ###. Bye now.", "af_heart", 1.0))
    assert len(chunks) == 2


def test_a_dropped_stream_leaves_nothing_in_the_pipe(engine, tmp_path):
    stream = engine.stream("One. Two. Three.", "af_heart", 1.0)
    next(stream)
    stream.close()
    assert len(list(engine.stream("Four.", "af_heart", 1.0))) == 1
    assert [r["text"] for r in requests(tmp_path)] == ["One.", "Four."]


def test_a_helper_that_dies_mid_reply_is_started_again(tmp_path):
    e = fluid.KokoroFluid(helper(tmp_path, "die-after-1"), models=tmp_path)
    try:
        with pytest.raises(RuntimeError, match="mid-sentence"):
            list(e.stream("One. Two.", "af_heart", 1.0))
        assert len(list(e.stream("Three.", "af_heart", 1.0))) == 1
    finally:
        e.close()


def test_a_helper_that_never_starts_is_unavailable(tmp_path):
    with pytest.raises(fluid.FluidUnavailable, match="did not start"):
        fluid.KokoroFluid(helper(tmp_path, "dead"), models=tmp_path)


def test_no_swift_no_build(tmp_path, monkeypatch):
    monkeypatch.setattr(fluid, "find_swift", lambda: None)
    with pytest.raises(fluid.FluidUnavailable, match="no swift"):
        fluid.build(tmp_path)


def test_the_build_is_named_for_its_sources(tmp_path):
    assert fluid.build_dir(tmp_path) == fluid.build_dir(tmp_path)
    assert fluid.build_dir(tmp_path).name.startswith("build-") and fluid.build_dir(tmp_path).parent == tmp_path


def test_trim_keeps_a_silent_piece_whole():
    silent = np.zeros(24_000, np.int16)
    assert len(fluid.trim(silent, 24_000)) == 24_000


class StubOnnx:
    def __init__(self, variant=None):
        self.name = f"kokoro ({variant})"


def test_fluid_is_the_default(monkeypatch):
    monkeypatch.delenv("VOICE_TTS_MODEL", raising=False)
    monkeypatch.setattr(fluid.KokoroFluid, "__init__", lambda self: None)
    assert engines.load("tts", "kokoro").name == "kokoro (fluid)"


def test_onnx_takes_over_when_fluid_is_unavailable(monkeypatch, caplog):
    def unavailable(self):
        raise fluid.FluidUnavailable("no swift: the Xcode command line tools are not installed")

    monkeypatch.delenv("VOICE_TTS_MODEL", raising=False)
    monkeypatch.setattr(fluid.KokoroFluid, "__init__", unavailable)
    monkeypatch.setattr(tts, "Kokoro", StubOnnx)
    with caplog.at_level(logging.WARNING, logger="voice.tts"):
        assert engines.load("tts", "kokoro").name == "kokoro (fp32)"
    assert "no swift" in caplog.text


@pytest.mark.parametrize("variant", ["fp32", "int8"])
def test_onnx_on_request(monkeypatch, variant):
    monkeypatch.setenv("VOICE_TTS_MODEL", variant)
    monkeypatch.setattr(tts, "Kokoro", StubOnnx)
    assert engines.load("tts", "kokoro").name == f"kokoro ({variant})"
