"""Listen: what Live is playing, streamed to the browser.

`capture.py` builds and runs the small Swift tool (`capture.swift`) that records Live's own output. `hub.py` runs it
only while somebody listens and hands each listener the newest sound. `routes.py` is the mount at /app/listen: the
status, the stream and the page's script. Nothing here changes the sound, and nothing here talks to Live.
"""

from __future__ import annotations

PREFIX = "/app/listen"
RATE = 48_000
CHANNELS = 2
FRAME = 2 * CHANNELS  # bytes in one frame of 16-bit stereo
FORMAT = {"encoding": "s16le", "rate": RATE, "channels": CHANNELS}
