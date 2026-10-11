"""The WebSocket between the page and the Mac (docs/studio.md has the tables).

Text frames are JSON objects with a "type". Binary frames start with a channel byte:

    0x01 mic     page -> Mac   s16le PCM, 16 kHz mono
    0x02 speech  Mac -> page   4-byte big-endian stream id, then s16le PCM at the stream's rate
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

MIC = 0x01
SPEECH = 0x02
MIC_RATE = 16_000
SPEECH_FRAME_S = 0.1    # speech goes out in frames this long, so the phone starts on the first one, not a sentence's end

# What a page may send, with the fields each message needs and their types.
CLIENT = {
    "hello": {},
    "prefs": {"prefs": dict},
    "start": {},
    "pause": {},
    "mic": {"state": str},
    "say": {"text": str},
    "end_turn": {},
    "interrupt": {},
    "playback": {"state": str},
    "mark": {"name": str},
    "log": {"text": str},
    "ping": {},
}
MAX_TEXT = 8000


class BadMessage(ValueError):
    pass


def parse_text(raw: str) -> dict[str, Any]:
    try:
        msg = json.loads(raw)
    except ValueError as exc:
        raise BadMessage("not JSON") from exc
    if not isinstance(msg, dict) or msg.get("type") not in CLIENT:
        raise BadMessage(f"unknown message type {msg.get('type') if isinstance(msg, dict) else None!r}")
    for name, kind in CLIENT[msg["type"]].items():
        if not isinstance(msg.get(name), kind):
            raise BadMessage(f"{msg['type']} needs {name!r}")
    if msg["type"] == "say" and not (0 < len(msg["text"].strip()) <= MAX_TEXT):
        raise BadMessage("say needs some text")
    return msg


def parse_binary(data: bytes) -> tuple[int, bytes]:
    if not data:
        raise BadMessage("empty binary frame")
    return data[0], data[1:]


def speech_frame(stream: int, pcm: bytes) -> bytes:
    return bytes([SPEECH]) + stream.to_bytes(4, "big") + pcm


def speech_frames(stream: int, pcm: bytes, rate: int) -> Iterator[bytes]:
    """`pcm` cut into frames of SPEECH_FRAME_S. A WebSocket message arrives whole: one sentence of speech in one
    frame (Kokoro makes a sentence at a time, ~150 KB) would take most of a second to reach a phone on a slow link
    before any of it could play."""
    step = max(2, int(rate * SPEECH_FRAME_S) * 2)
    for i in range(0, len(pcm), step):
        yield speech_frame(stream, pcm[i:i + step])
