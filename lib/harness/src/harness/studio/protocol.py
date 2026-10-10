"""The WebSocket between the page and the Mac (docs/studio.md has the tables).

Text frames are JSON objects with a "type". Binary frames start with a channel byte:

    0x01 mic     page -> Mac   s16le PCM, 16 kHz mono
    0x02 speech  Mac -> page   4-byte big-endian stream id, then s16le PCM at the stream's rate
"""

from __future__ import annotations

import json
from typing import Any

MIC = 0x01
SPEECH = 0x02
MIC_RATE = 16_000

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
