"""Listen: what Live is playing, streamed to the browser.

The sound comes from one of two captures. `device.py` reads the "zpkt listen" Max for Live device on Main (the first
choice: Live's own samples at Live's sample rate, about 12 ms late, no macOS permission). `capture.py` builds and runs
the small Swift tool (`capture.swift`) that records Live's output through macOS (the fallback, 48 kHz), and holds the
chain that tries the one and then the other. `hub.py` runs a capture only while somebody listens and hands each
listener the newest sound. `routes.py` is the mount at /app/listen: the status, the stream and the page's script.
Nothing here changes the sound, and nothing here sends Live a command.

The sample rate is not fixed: it is whatever the open capture says, and it travels with the stream.
"""

from __future__ import annotations

PREFIX = "/app/listen"
ENCODING = "s16le"
CHANNELS = 2
FRAME = 2 * CHANNELS  # bytes in one frame of 16-bit stereo
SOURCES = ("auto", "device", "screen")  # ZPKT_LISTEN_SOURCE


def audio_format(rate: int) -> dict[str, object]:
    """The stream's format as the status gives it."""
    return {"encoding": ENCODING, "rate": rate, "channels": CHANNELS}


def format_header(rate: int) -> str:
    """The same as the X-Audio-Format header of a stream."""
    return f"{ENCODING};rate={rate};channels={CHANNELS}"
