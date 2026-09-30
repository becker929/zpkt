"""Stateless LOM query and mutation helpers.

Each function takes a McpTransport as its first argument so callers
can inject any transport (live, dry-run, mock) without global state.
"""

from __future__ import annotations

import time
from typing import Any

from hands.transport import McpTransport


def _run(transport: McpTransport, code: str) -> Any:
    """Execute code via transport; return result or raise RuntimeError on error."""
    resp = transport.execute(code)
    if resp.status != "ok":
        raise RuntimeError(f"Ableton error: {resp.error}")
    return resp.result


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------

def get_track_count(transport: McpTransport) -> int:
    """Return the number of tracks in the current Live set."""
    return _run(transport, "len(song.tracks)")


def get_track_names(transport: McpTransport) -> list[str]:
    """Return a list of track names in the current Live set."""
    return _run(transport, "[t.name for t in song.tracks]")


def get_track_info(transport: McpTransport, track_idx: int) -> dict:
    """Get full state of a track: name, volume, pan, mute, solo, arm, devices."""
    return _run(transport, f"""
t = song.tracks[{track_idx}]
result = {{
    "name": t.name,
    "volume": t.mixer_device.volume.value,
    "panning": t.mixer_device.panning.value,
    "mute": t.mute,
    "solo": t.solo,
    "arm": t.arm if t.can_be_armed else False,
    "num_devices": len(t.devices),
    "devices": [d.name for d in t.devices],
    "has_midi_input": t.has_midi_input,
}}
""")


def get_song_state(transport: McpTransport) -> dict:
    """Return a snapshot of key song properties."""
    return _run(transport, """
result = {
    "tempo": song.tempo,
    "signature": f"{song.signature_numerator}/{song.signature_denominator}",
    "is_playing": song.is_playing,
    "num_tracks": len(song.tracks),
    "num_scenes": len(song.scenes),
    "track_names": [t.name for t in song.tracks],
    "loop": song.loop,
    "loop_start": song.loop_start,
    "loop_length": song.loop_length,
}
""")


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def clear_set(transport: McpTransport) -> None:
    """Delete all tracks except one, clear devices and clips from that track."""
    _run(transport, """
song.begin_undo_step()
while len(song.tracks) > 1:
    song.delete_track(len(song.tracks) - 1)
for rt in list(song.return_tracks):
    song.delete_return_track(len(song.return_tracks) - 1)
t = song.tracks[0]
t.name = "Temp"
while len(t.devices) > 0:
    t.delete_device(0)
for cs in t.clip_slots:
    if cs.has_clip:
        cs.delete_clip()
song.end_undo_step()
""")


def create_midi_track(transport: McpTransport, name: str) -> int:
    """Create a new MIDI track at the end. Returns track index."""
    idx = get_track_count(transport)
    _run(transport, "song.create_midi_track(-1)")
    time.sleep(0.2)
    _run(transport, f"song.tracks[{idx}].name = {name!r}")
    return idx


def create_audio_track(transport: McpTransport, name: str) -> int:
    """Create a new audio track at the end. Returns track index."""
    idx = get_track_count(transport)
    _run(transport, "song.create_audio_track(-1)")
    time.sleep(0.2)
    _run(transport, f"song.tracks[{idx}].name = {name!r}")
    return idx
