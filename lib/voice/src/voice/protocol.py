"""Frames between the harness and the voice worker, over the worker's stdin and stdout.

    [4-byte big-endian header length][JSON header][4-byte big-endian payload length][payload]

The header always has an "op"; requests carry an "id" that replies echo. Payloads are raw audio
(signed 16-bit little-endian PCM, mono) or empty. This module imports nothing heavy: the harness uses it too.
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

MAX_HEADER = 1 << 20
MAX_PAYLOAD = 64 << 20
_LEN = struct.Struct(">I")


class FrameError(ValueError):
    pass


def encode(header: dict[str, Any], payload: bytes = b"") -> bytes:
    h = json.dumps(header, separators=(",", ":")).encode()
    return _LEN.pack(len(h)) + h + _LEN.pack(len(payload)) + payload


async def read(reader: asyncio.StreamReader) -> tuple[dict[str, Any], bytes] | None:
    """The next frame, or None at the end of the stream."""
    try:
        (n,) = _LEN.unpack(await reader.readexactly(4))
        if n > MAX_HEADER:
            raise FrameError(f"header of {n} bytes")
        header = json.loads(await reader.readexactly(n))
        (m,) = _LEN.unpack(await reader.readexactly(4))
        if m > MAX_PAYLOAD:
            raise FrameError(f"payload of {m} bytes")
        payload = await reader.readexactly(m) if m else b""
    except asyncio.IncompleteReadError:
        return None
    if not isinstance(header, dict) or "op" not in header:
        raise FrameError("a frame needs an op")
    return header, payload
