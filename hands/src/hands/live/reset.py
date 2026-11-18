"""Atomic LOM set reset: cleans arrangement, devices, and extra tracks in one call."""

from __future__ import annotations

from typing import Any

from hands.live.transport import McpTransport


def reset_set(
    client: McpTransport,
    track_name: str = "Operator",
    tempo: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Reset the running Live set to a clean slate with a single named MIDI track.

    This deletes every other track and every clip of the open set, so it refuses a set that has an
    arrangement or more than two tracks unless `force` is given. To add one instrument to a set that
    is in use, `hands panel make` does it without touching the rest.
    """
    if not force:
        tracks, clips = client.run(
            "result = [len(song.tracks), sum(len(t.arrangement_clips) for t in song.tracks if not t.is_foldable)]")
        if tracks > 2 or clips:
            raise RuntimeError(f"the open set has {tracks} tracks and {clips} arrangement clips; a reset would delete them. "
                               "Use `hands panel make` to add an instrument beside them, or pass --force.")
    code = f'''
song.stop_playing()
song.loop = False
song.start_time = 0.0
song.current_song_time = 0.0
if {tempo!r} is not None:
    song.tempo = float({tempo!r})

if not song.tracks:
    song.create_midi_track(0)
elif not song.tracks[0].has_midi_input:
    song.create_midi_track(0)

_t = song.tracks[0]
_t.name = {track_name!r}

for _c in list(_t.arrangement_clips):
    _t.delete_clip(_c)

while len(_t.devices):
    _t.delete_device(0)

while len(song.tracks) > 1:
    song.delete_track(1)

while len(song.return_tracks):
    song.delete_return_track(0)

_t.arm = True
song.view.selected_track = _t

result = {{
    "status": "ok",
    "track": _t.name,
    "tempo": song.tempo,
    "tracks_count": len(song.tracks),
    "clips_count": len(_t.arrangement_clips),
    "devices_count": len(_t.devices),
}}
'''
    return client.run(code)
