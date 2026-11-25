"""The song's tempo: set it, or double or halve it. The app calls these with its connection (ZpktMiniLabTempo's job).

One short call each, and no read back in the same call (ableton-guide). The range is what Live takes.
"""

from __future__ import annotations

from zpkt.live.transport import McpTransport

LOWEST_BPM, HIGHEST_BPM = 20.0, 999.0


def clamp(bpm: float) -> float:
    return max(LOWEST_BPM, min(HIGHEST_BPM, float(bpm)))


def set_tempo(live: McpTransport, bpm: float) -> None:
    """Set the tempo in beats per minute."""
    live.run(f"song.tempo = {clamp(bpm)!r}\nresult = 'ok'")


def scale_tempo(live: McpTransport, factor: float) -> None:
    """Multiply the tempo by `factor` (2 doubles it, 0.5 halves it), in one call."""
    live.run(f"song.tempo = max({LOWEST_BPM!r}, min({HIGHEST_BPM!r}, song.tempo * {float(factor)!r}))\nresult = 'ok'")
