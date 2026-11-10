"""The real engines (Kokoro, Parakeet), end to end: Kokoro says a turn, Parakeet hears it and the stop word.

They need the models (`uv sync --extra engines`; the first run downloads ~1.5 GB and builds the FluidAudio helper),
so they run only with VOICE_ENGINES=1. The text helpers below them run always."""

import os
import time

import numpy as np
import pytest

from voice.stt import is_stop, split_stop
from voice.tts import pieces

engines = pytest.mark.skipif(os.environ.get("VOICE_ENGINES") != "1", reason="VOICE_ENGINES=1 runs the real models")


def test_sentences_are_cut_for_speaking():
    assert pieces("One. Two!  Three?") == ["One.", "Two!", "Three?"]
    long = "word " * 80
    assert all(len(p) <= 220 for p in pieces(long))
    assert " ".join(pieces(long)).split() == long.split()


@pytest.mark.parametrize("heard", ["tomato", "tomatoes", "tamato", "tomatoe", "tomotto", "tomedo"])
def test_the_stop_word_and_near_misses(heard):
    assert is_stop(heard)


@pytest.mark.parametrize("heard", ["tom", "potato", "to", "mate", "mato", "tomorrow", "tomake", "tomute"])
def test_words_that_are_not_the_stop_word(heard):
    assert not is_stop(heard)


def test_the_stop_word_ends_the_text_and_is_taken_off():
    assert split_stop("Make the kick louder. Tomato.") == (True, "Make the kick louder")
    assert split_stop("make the kick louder, to mato") == (True, "make the kick louder")
    assert split_stop("Make it minus 3. Tomato.") == (True, "Make it minus 3")
    assert split_stop("Tomato.") == (True, "")
    assert split_stop("tomatoes are red and")[0] is False
    assert split_stop("Turn it up. Potato.")[0] is False


@pytest.fixture(scope="module")
def kokoro():
    from voice.tts import Kokoro
    return Kokoro()


@pytest.fixture(scope="module")
def parakeet():
    from voice.stt import Parakeet
    engine = Parakeet()
    engine.warmup()
    return engine


def say(kokoro, text: str) -> tuple[np.ndarray, int]:
    parts = [pcm for pcm, rate in kokoro.stream(text, "am_michael", 1.0)]
    return np.concatenate(parts), kokoro.rate


def feed(turn, pcm: np.ndarray, rate: int, frame_s: float = 0.02):
    """Feed the audio as the phone would (20 ms frames, in real time order), collecting events."""
    events = []
    step = int(rate * frame_s)
    for i in range(0, len(pcm), step):
        events += turn.feed(pcm[i:i + step])
        if any(e["op"] == "stt.final" for e in events):
            break
    return events


@pytest.fixture(scope="module")
def fluid():
    from voice.fluid import KokoroFluid
    engine = KokoroFluid()
    engine.warmup()
    yield engine
    engine.close()


@engines
@pytest.mark.parametrize("build", ["kokoro", "fluid"])
def test_kokoro_speaks_in_pieces(build, request):
    speaker = request.getfixturevalue(build)
    t0 = time.monotonic()
    chunks = list(speaker.stream("First sentence here. And a second one, a little longer.", "af_heart", 1.0))
    assert len(chunks) == 2 and all(rate == 24_000 and pcm.dtype == np.int16 for pcm, rate in chunks)
    seconds = sum(len(p) for p, _ in chunks) / 24_000
    assert 2.0 < seconds < 8.0
    assert time.monotonic() - t0 < seconds, "faster than real time"


@engines
def test_fluidaudio_is_quick_and_heard_right(fluid, parakeet):
    """The first sentence in well under the ONNX build's half second, the voice and speed honoured, and words that
    Parakeet hears back."""
    t0 = time.monotonic()
    stream = fluid.stream("Make the kick drum a little louder. Then brighten the hi hats.", "am_michael", 1.0)
    first, rate = next(stream)
    assert time.monotonic() - t0 < 0.3
    pcm = np.concatenate([first, *(p for p, _ in stream)])
    fast = np.concatenate([p for p, _ in fluid.stream("Make the kick drum a little louder.", "am_michael", 1.5)])
    assert len(fast) < 0.85 * len(first)
    turn = parakeet.turn("tomato", rate)
    feed(turn, np.concatenate([pcm, np.zeros(rate, np.int16)]), rate)
    text = turn.finish()["text"].lower()
    assert all(w in text for w in ("kick", "louder", "hats")), text


@engines
def test_a_spoken_turn_ends_on_tomato(kokoro, parakeet):
    pcm, rate = say(kokoro, "Make the kick drum a little louder and brighten the hi hats. Tomato.")
    silence = np.zeros(int(rate * 1.0), np.int16)
    turn = parakeet.turn("tomato", rate)
    events = feed(turn, np.concatenate([pcm, silence]), rate)
    partials = [e for e in events if e["op"] == "stt.partial"]
    finals = [e for e in events if e["op"] == "stt.final"]
    assert partials, "captions arrive while talking"
    assert len(finals) == 1 and finals[0]["stop_word"] is True
    text = finals[0]["text"].lower()
    assert "tomato" not in text
    assert all(w in text for w in ("kick", "louder", "hats")), text


@engines
def test_pauses_do_not_end_the_turn(kokoro, parakeet):
    a, rate = say(kokoro, "Try the bass at minus two.")
    b, _ = say(kokoro, "Actually make it minus three. Tomato.")
    pause = np.zeros(int(rate * 1.5), np.int16)
    turn = parakeet.turn("tomato", rate)
    events = feed(turn, np.concatenate([a, pause, b, pause]), rate)
    finals = [e for e in events if e["op"] == "stt.final"]
    assert len(finals) == 1 and finals[0]["stop_word"]
    text = finals[0]["text"].lower()
    assert "minus 2" in text or "minus two" in text, text
    assert text.endswith(("minus 3", "minus three")), text


@engines
def test_no_stop_word_no_final_until_told(kokoro, parakeet):
    pcm, rate = say(kokoro, "Tomatoes are red, and the kick is too loud.")
    turn = parakeet.turn("tomato", rate)
    events = feed(turn, np.concatenate([pcm, np.zeros(rate, np.int16)]), rate)
    assert not [e for e in events if e["op"] == "stt.final"]
    final = turn.finish()
    assert final["stop_word"] is False and "loud" in final["text"].lower()


@engines
async def test_the_worker_serves_both_models_over_its_pipe(kokoro):
    """`voice serve` with its default engines, as the harness starts it: ready, speaks, hears a turn."""
    import asyncio
    import sys

    from voice import protocol

    pcm, rate = say(kokoro, "Loop that three times. Tomato.")
    pcm16 = np.interp(np.linspace(0, len(pcm) - 1, int(len(pcm) * 16_000 / rate)), np.arange(len(pcm)), pcm)
    pcm16 = np.concatenate([pcm16.astype(np.int16), np.zeros(16_000, np.int16)])
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "voice.worker", "serve",
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL, limit=protocol.MAX_PAYLOAD)
    try:
        proc.stdin.write(protocol.encode({"op": "ping", "id": "p"}))
        pong, _ = await asyncio.wait_for(protocol.read(proc.stdout), 120)
        assert pong["op"] == "pong" and pong["tts"].startswith("kokoro") and pong["stt"].startswith("parakeet")
        proc.stdin.write(protocol.encode({"op": "tts", "id": "s", "text": "Here it is.", "voice": "af_heart",
                                          "speed": 1.0}))
        proc.stdin.write(protocol.encode({"op": "stt.begin", "id": "u", "rate": 16_000, "stop_word": "tomato"}))
        for i in range(0, len(pcm16), 320):
            proc.stdin.write(protocol.encode({"op": "stt.audio", "id": "u"}, pcm16[i:i + 320].astype("<i2").tobytes()))
        got: dict[str, list] = {"s": [], "u": []}
        while not (got["s"] and got["s"][-1]["op"] == "tts.end" and got["u"] and got["u"][-1]["op"] == "stt.final"):
            header, payload = await asyncio.wait_for(protocol.read(proc.stdout), 60)
            got[header["id"]].append(header)
        assert any(h["op"] == "tts.chunk" for h in got["s"]) and "error" not in got["s"][-1]
        final = got["u"][-1]
        assert final["stop_word"] is True and "three times" in final["text"].lower(), repr(final)
    finally:
        proc.kill()


@engines
@pytest.mark.parametrize("quiet_s", [60, 360])
def test_a_turn_left_listening_for_minutes_still_hears_the_line(kokoro, parakeet, quiet_s):
    """The mic was offered and nobody spoke for minutes (driving, thinking, an app switch), then the line came. The
    long quiet must not cost the words: in the end-to-end test a 357 s turn transcribed in one pass came back empty."""
    pcm, rate = say(kokoro, "Make an A B of the rumble drive, forty against fifty percent. Tomato.")
    rng = np.random.default_rng(1)
    quiet = (rng.standard_normal(int(rate * quiet_s)) * 30).astype(np.int16)        # a room's hiss, about -60 dBFS
    turn = parakeet.turn("tomato", rate)
    t0 = time.monotonic()
    events = feed(turn, np.concatenate([quiet, pcm, np.zeros(rate, np.int16)]), rate)
    finals = [e for e in events if e["op"] == "stt.final"]
    assert len(finals) == 1 and finals[0]["stop_word"], finals
    text = finals[0]["text"].lower()
    assert "rumble" in text and "fifty" in text.replace("50", "fifty"), text
    assert finals[0]["ms"] < 3000, f"the final took {finals[0]['ms']} ms after the stop word"
    assert time.monotonic() - t0 < quiet_s / 4, "the quiet costs little to listen to"
