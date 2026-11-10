"""The worker over its real pipes, with the stand-in engines."""

import asyncio
import os
import sys

import pytest

from voice import protocol


def test_frames_round_trip():
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(protocol.encode({"op": "x", "id": "1"}, b"\x01\x02") + protocol.encode({"op": "y"}))
        reader.feed_eof()
        assert await protocol.read(reader) == ({"op": "x", "id": "1"}, b"\x01\x02")
        assert await protocol.read(reader) == ({"op": "y"}, b"")
        assert await protocol.read(reader) is None
    asyncio.run(go())


def test_a_frame_needs_an_op():
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(protocol.encode({"id": "1"}))   # type: ignore[arg-type]
        reader.feed_eof()
        with pytest.raises(protocol.FrameError):
            await protocol.read(reader)
    asyncio.run(go())


async def worker(**env):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "voice.worker", "--tts", "fake", "--stt", "fake", "serve",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, **env})
    return proc


async def replies(proc, n, timeout=10):
    return [await asyncio.wait_for(protocol.read(proc.stdout), timeout) for _ in range(n)]


async def test_speech_comes_in_chunks_and_can_be_cancelled():
    proc = await worker()
    try:
        proc.stdin.write(protocol.encode({"op": "ping", "id": "p"}))
        proc.stdin.write(protocol.encode({"op": "tts", "id": "a", "text": "x" * 40, "voice": "v", "speed": 1.0}))
        proc.stdin.write(protocol.encode({"op": "tts.cancel", "id": "b"}))
        proc.stdin.write(protocol.encode({"op": "tts", "id": "b", "text": "never said", "voice": "v", "speed": 1.0}))
        [(pong, _)] = await replies(proc, 1)
        assert pong["op"] == "pong" and pong["tts"] == "fake"
        frames = []
        while not frames or frames[-1][0]["op"] != "tts.end" or frames[-1][0]["id"] != "b":
            frames += await replies(proc, 1)
        chunks = [(h, p) for h, p in frames if h["op"] == "tts.chunk"]
        assert chunks and all(h["id"] == "a" and h["rate"] == 24000 and len(p) % 2 == 0 for h, p in chunks)
        assert sum(len(p) for _, p in chunks) == int(40 * 0.03 * 24000) * 2
        assert frames[-1][0] == {"op": "tts.end", "id": "b", "cancelled": True}
    finally:
        proc.kill()


async def test_a_turn_ends_on_the_stop_word_or_when_told():
    proc = await worker(VOICE_FAKE_TEXT="play again", VOICE_FAKE_AFTER_S="0.2")
    try:
        proc.stdin.write(protocol.encode({"op": "stt.begin", "id": "u", "rate": 16000, "stop_word": "tomato"}))
        for _ in range(15):                                   # 0.3 s of audio
            proc.stdin.write(protocol.encode({"op": "stt.audio", "id": "u"}, bytes(640)))
        proc.stdin.write(protocol.encode({"op": "stt.begin", "id": "v", "rate": 16000, "stop_word": "tomato"}))
        proc.stdin.write(protocol.encode({"op": "stt.audio", "id": "v"}, bytes(640)))
        proc.stdin.write(protocol.encode({"op": "stt.end", "id": "v"}))
        seen = {}
        while len(seen) < 2:
            (h, _), = await replies(proc, 1)
            if h["op"] == "stt.final":
                seen[h["id"]] = h
        assert seen["u"]["text"] == "play again" and seen["u"]["stop_word"] is True
        assert seen["v"]["stop_word"] is False
    finally:
        proc.kill()
