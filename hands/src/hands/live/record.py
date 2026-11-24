"""Real-time takes: record Live's output through a resampling track, then copy or encode it.

An audio track with the 'Resampling' input captures the main output inside Live; the take is
copied as WAV, or converted to MP3 with ffmpeg. It runs at 1.56x real time, so offline export
(hands.live.render) is the default; these remain for what export cannot do, such as session clips.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from hands.live.transport import McpTransport

AUDIO_STALLED = (
    "Live's playhead did not move, so its audio engine is not running and nothing can be recorded. "
    "Run `hands rig reset`: it gives Live an audio device again, or restarts Live and macOS audio."
)


def playhead_moves(transport, start_beat: float, seconds: float = 1.5) -> bool:
    """After start_playing(): does the playhead leave start_beat within `seconds`? It cannot when the audio engine is
    stopped (a wedged coreaudiod, no output device), and then a recording waits out its whole length for nothing."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.25)
        try:
            if float(transport.run("song.current_song_time")) > float(start_beat) + 0.01:
                return True
        except Exception:
            return True  # cannot tell: let the recording go ahead as before
    return False


def record_via_resampling(
    transport: McpTransport,
    filename: str,
    duration_beats: float,
    output_dir: str | Path = ".",
    allow_clearing_arrangement: bool = False,
) -> str | None:
    """Create a resampling track, record the session, export as MP3 or WAV.

    This bounces *session* slot-0 clips: it copies them into the arrangement,
    records, then deletes every arrangement clip on the source tracks. On a
    set that already has an arrangement that deletion wipes it, so the call
    refuses unless ``allow_clearing_arrangement`` is set. Use
    ``record_arrangement`` to render an existing arrangement.

    filename's extension picks the format (.wav skips ffmpeg). Returns the absolute path to the exported file, or
    None when nothing was recorded.
    """
    _refuse_to_clear_the_arrangement(transport, allow_clearing_arrangement)
    out_path, want_wav = _target(output_dir, filename)
    _rewind(transport)
    n = transport.run("len(song.tracks)")
    _copy_session_clips_to_the_arrangement(transport, n)
    _loop_the_arrangement(transport, n, duration_beats)
    # trigger_session_record() records on every armed track, so an armed source (Live auto-arms the selected MIDI
    # track) gets a new empty clip that silences it, and the bounce comes out silent.
    armed = _disarm(transport, f"[i for i in range({n}) if song.tracks[i].can_be_armed and song.tracks[i].arm]")
    if armed:
        print(f"  Disarmed source tracks {armed} for the bounce")
    idx = _resampling_track_for_session(transport)
    tempo = _record_session(transport, idx, duration_beats)
    file_path = _session_take(transport, idx)
    if file_path is None:
        print("  No recorded clip found!")
        _cleanup_arrangement_clips(transport, n, armed)
        return None
    result = _export(file_path, out_path, duration_beats, tempo, want_wav)
    transport.run(f"song.delete_track({idx})")
    _cleanup_arrangement_clips(transport, n, armed)
    return result


def _refuse_to_clear_the_arrangement(transport: McpTransport, allowed: bool) -> None:
    existing = (
        transport.run(
            # Group tracks raise on arrangement_clips; only leaf tracks hold clips.
            "sum(len(t.arrangement_clips) for t in song.tracks if not t.is_foldable)",
        )
        or 0
    )
    if existing and not allowed:
        raise RuntimeError(
            f"The set already has {existing} arrangement clip(s); record_via_resampling "
            "would delete them. Use record_arrangement to render the arrangement, or "
            "pass allow_clearing_arrangement=True."
        )


def _target(output_dir: str | Path, filename: str) -> tuple[str, bool]:
    """The output path (its folder made) and whether it is a WAV (else ffmpeg encodes it)."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return str(out_dir / filename), filename.lower().endswith(".wav")


def _rewind(transport: McpTransport) -> None:
    transport.run("song.stop_playing()")
    time.sleep(0.3)
    transport.run("song.current_song_time = 0.0")
    time.sleep(0.1)
    current_pos = transport.run("song.current_song_time")
    print(f"  Rewound to beat 0, current_song_time = {current_pos}")


def _copy_session_clips_to_the_arrangement(transport: McpTransport, n: int) -> None:
    """Each source track's session slot-0 clip into the arrangement at beat 0: arrangement playback is
    deterministic, with no clip-triggering races."""
    for i in range(n):
        if not transport.run(f"song.tracks[{i}].clip_slots[0].has_clip"):
            continue
        print(f"  Copying session clip on track {i} to arrangement at beat 0")
        transport.run(f"[song.tracks[{i}].delete_clip(c) for c in list(song.tracks[{i}].arrangement_clips)]")
        time.sleep(0.1)
        transport.run(f"song.tracks[{i}].duplicate_clip_to_arrangement(song.tracks[{i}].clip_slots[0].clip, 0.0)")
        time.sleep(0.2)


def _loop_the_arrangement(transport: McpTransport, n: int, duration_beats: float) -> None:
    """Loop exactly the requested beats, and stop the session so the arrangement drives playback."""
    transport.run("song.loop = True")
    transport.run("song.loop_start = 0.0")
    transport.run(f"song.loop_length = {duration_beats}")
    time.sleep(0.1)
    for i in range(n):
        transport.run(f"song.tracks[{i}].stop_all_clips()")
    time.sleep(0.1)
    # stop_all_clips leaves each track following the (now stopped) session and lights "Back to Arrangement"; clear
    # it so arrangement clips play.
    transport.run("song.back_to_arranger = False")
    time.sleep(0.1)


def _disarm(transport: McpTransport, armed_expr: str) -> list[int]:
    """Disarm the tracks `armed_expr` lists (indices); return them, to arm again afterwards."""
    armed = transport.run(armed_expr) or []
    for i in armed:
        transport.run(f"song.tracks[{i}].arm = 0")
    return armed


def _new_audio_track(transport: McpTransport, name: str) -> int:
    idx = transport.run("len(song.tracks)")
    transport.run("song.create_audio_track(-1)")
    time.sleep(0.3)
    transport.run(f'song.tracks[{idx}].name = "{name}"')
    return idx


def _route_resampling(transport: McpTransport, idx: int) -> str:
    """Set the track's input to Resampling; return the input it shows. The RoutingType object must be found and
    assigned in one LOM call."""
    transport.run(
        f"_rt = next((rt for rt in song.tracks[{idx}].available_input_routing_types"
        f' if "Resampling" in rt.display_name), None);'
        f" song.tracks[{idx}].input_routing_type = _rt",
    )
    time.sleep(0.2)
    return str(transport.run(f"song.tracks[{idx}].input_routing_type.display_name"))


def _resampling_track_for_session(transport: McpTransport) -> int:
    idx = _new_audio_track(transport, "Resample")
    types = _wait_for_resampling(transport, idx)
    print(f"  Available input types: {types}")
    if not types or not any("Resamp" in str(t) for t in types):
        raise RuntimeError(f"Resampling input type not found. Available: {types}")
    routing_type = _route_resampling(transport, idx)
    print(f"  Resampling track input set to: {routing_type}")
    if "Resampling" not in routing_type:
        raise RuntimeError(f"Failed to set Resampling input — got: {routing_type}")
    transport.run(f"song.tracks[{idx}].arm = 1")
    transport.run(f"song.tracks[{idx}].current_monitoring_state = 1")  # Auto (0=In, 1=Auto, 2=Off)
    time.sleep(0.2)
    return idx


def _record_session(transport: McpTransport, idx: int, duration_beats: float) -> float:
    """Record from beat 0 for `duration_beats` (and a second) into the resampling track; return the tempo."""
    transport.run("song.session_record = 0")
    transport.run("song.overdub = 0")
    transport.run("song.current_song_time = 0.0")  # once more, in case track setup nudged the playhead
    time.sleep(0.1)
    transport.run("song.trigger_session_record()")
    time.sleep(0.3)
    if not transport.run("song.is_playing"):
        print("  Transport not started by trigger_session_record — calling start_playing()")
        transport.run("song.start_playing()")
        time.sleep(0.2)
    tempo = transport.run("song.tempo")
    wait_secs = (duration_beats / tempo) * 60 + 1.0
    print(f"  Recording for {wait_secs:.1f}s ({duration_beats} beats at {tempo} BPM)...")
    time.sleep(wait_secs)
    transport.run("song.stop_playing()")
    time.sleep(1.0)
    return tempo


def _session_take(transport: McpTransport, idx: int) -> str | None:
    """The recorded take's file: in slot 0, else the first of slots 0-7 that holds a clip; None if none does."""
    if transport.run(f"song.tracks[{idx}].clip_slots[0].has_clip"):
        file_path = transport.run(f"song.tracks[{idx}].clip_slots[0].clip.file_path")
        print(f"  Recorded audio file: {file_path}")
        return file_path
    for slot in range(8):
        if transport.run(f"song.tracks[{idx}].clip_slots[{slot}].has_clip"):
            file_path = transport.run(f"song.tracks[{idx}].clip_slots[{slot}].clip.file_path")
            print(f"  Found recorded clip in slot {slot}: {file_path}")
            return file_path
    return None


def record_arrangement(
    transport: McpTransport,
    filename: str,
    duration_beats: float,
    output_dir: str | Path = ".",
    tail_beats: float = 4.0,
    start_beat: float = 0.0,
    keep_take: bool = True,
) -> str | None:
    """Render the set's arrangement from ``start_beat`` (beat 0 by default) via a resampling track.

    Leaves the source tracks' arrangement clips alone. Records
    ``duration_beats + tail_beats`` in arrangement record mode, exports the
    take untrimmed, then removes the temporary track and restores the source
    tracks' arm state.

    The first ~0.9 s of the take is NOT on the song timeline: Live's recorded
    clip starts ~2.4 beats into its own file, and the file's head holds
    misplaced audio (heard as "plays a bar, then restarts"). After that the
    file time matches song time within a few 512-sample buffers. So render
    two or more bars of lead-in before the material you need and trim them:
    the take's ``.timing.json`` says where song beat 0 is in the file, and
    hands.audio.trim_take cuts there. With a ``start_beat`` the take's first
    clip sits at about that beat: ``clip_start`` in the timing file is the
    song beat that ``song_zero_seconds`` belongs to. ``keep_take=False`` removes
    Live's own take file from the project once the export is written.
    """
    out_path, want_wav = _target(output_dir, filename)
    transport.run("song.stop_playing()")
    time.sleep(0.3)
    transport.run("song.loop = False")
    # Same silent-take causes as record_via_resampling: armed sources get recorded over, and a lit "Back to
    # Arrangement" ignores arrangement clips.
    armed = _disarm(transport, "[i for i, t in enumerate(song.tracks) if t.can_be_armed and t.arm]")
    transport.run("song.back_to_arranger = False")
    idx = _resampling_track_for_arrangement(transport, armed)
    tempo = _record_arrangement_take(transport, idx, armed, start_beat, duration_beats, tail_beats)
    file_path = transport.run(f"[c.file_path for c in song.tracks[{idx}].arrangement_clips][:1]")
    timing = _take_timing(transport, idx) if file_path else None
    result = None
    if file_path:
        print(f"  Recorded audio file: {file_path[0]}")
        result = _export(file_path[0], out_path, duration_beats + tail_beats, tempo, want_wav)
        if result and timing:
            _write_timing(result, timing, tempo)
    else:
        print("  No recorded clip found!")
    transport.run(f"song.delete_track({idx})")
    _restore_arm(transport, armed)
    if result and not keep_take:
        # Live's own take file in the project's Samples/Recorded: the export is a copy of it
        for leftover in (file_path[0], file_path[0] + ".asd"):
            if os.path.exists(leftover):
                os.remove(leftover)
    return result


def _resampling_track_for_arrangement(transport: McpTransport, armed: list[int]) -> int:
    idx = _new_audio_track(transport, "Render")
    _wait_for_resampling(transport, idx)
    routing = _route_resampling(transport, idx)
    if "Resampling" not in routing:
        transport.run(f"song.delete_track({idx})")
        _restore_arm(transport, armed)
        raise RuntimeError(f"Failed to set Resampling input — got: {routing}")
    transport.run(f"song.tracks[{idx}].arm = 1")
    time.sleep(0.2)
    return idx


def _record_arrangement_take(
    transport: McpTransport, idx: int, armed: list[int], start_beat: float, duration_beats: float, tail_beats: float
) -> float:
    """Play from start_beat in arrangement record mode for the beats and the tail; return the tempo. If the playhead
    does not move (Live's audio engine is stopped), take the track away and raise with what to do."""
    if start_beat:
        # start_playing() plays from the start marker, not from current_song_time
        transport.run(f"song.start_time = {float(start_beat)!r}")
    transport.run(f"song.current_song_time = {float(start_beat)!r}")
    time.sleep(0.1)
    transport.run("song.record_mode = True")
    transport.run("song.start_playing()")
    if not playhead_moves(transport, float(start_beat or 0.0)):
        transport.run("song.stop_playing()")
        transport.run("song.record_mode = False")
        transport.run(f"song.delete_track({idx})")
        _restore_arm(transport, armed)
        raise RuntimeError(AUDIO_STALLED)
    tempo = transport.run("song.tempo")
    wait_secs = (duration_beats + tail_beats) / tempo * 60 + 0.5
    print(f"  Recording arrangement for {wait_secs:.1f}s ({duration_beats}+{tail_beats} beats at {tempo} BPM)...")
    time.sleep(wait_secs)
    transport.run("song.stop_playing()")
    transport.run("song.record_mode = False")
    time.sleep(1.5)
    return tempo


def _take_timing(transport: McpTransport, idx: int) -> dict[str, Any]:
    """Where song beat 0 sits in the take: the clip starts at its start_marker (clip beats), which its warp markers
    map to seconds in the file."""
    return transport.run(
        f"c = song.tracks[{idx}].arrangement_clips[0]; result = {{'start_marker': c.start_marker, "
        f"'warp_markers': [[w.beat_time, w.sample_time] for w in c.warp_markers], 'clip_start': c.start_time}}",
    )


def _write_timing(result: str, timing: dict[str, Any], tempo: float) -> None:
    timing["song_zero_seconds"] = _beat_to_seconds(timing["warp_markers"], timing["start_marker"])
    timing["tempo"] = tempo
    with open(result + ".timing.json", "w") as f:
        json.dump(timing, f)
    print(f"  Song beat 0 is at {timing['song_zero_seconds']:.3f} s in the take")


def _wait_for_resampling(transport: McpTransport, idx: int, attempts: int = 10) -> list:
    """Return the track's input types once "Resampling" is among them.

    A freshly created track can report empty routing types for a moment, so
    setting the input straight away sometimes silently fails. Retry with a
    short settle (from the September 2026 untracked recorder).
    """
    types: list = []
    for _ in range(attempts):
        types = (
            transport.run(
                f"[t.display_name for t in song.tracks[{idx}].available_input_routing_types]",
            )
            or []
        )
        if any("Resamp" in str(t) for t in types):
            break
        time.sleep(0.3)
    return types


def _restore_arm(transport: McpTransport, armed: list[int]) -> None:
    for i in armed:
        transport.run(f"song.tracks[{i}].arm = 1")


def _cleanup_arrangement_clips(transport: McpTransport, num_tracks: int, armed: list[int] = ()) -> None:
    """Remove arrangement clips placed by record_via_resampling on source tracks,
    and re-arm the source tracks that were disarmed for the bounce."""
    for i in range(num_tracks):
        transport.run(
            f"[song.tracks[{i}].delete_clip(c) for c in list(song.tracks[{i}].arrangement_clips)]",
        )
    for i in armed:
        transport.run(f"song.tracks[{i}].arm = 1")


def _log_audio_stats(path: str) -> None:
    """Log codec, channels, sample rate, duration and peak dBFS via ffprobe."""
    import json as _json
    import shutil

    if not shutil.which("ffprobe"):
        size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
        print(f"  Audio: {Path(path).name} ({size_kb:.0f} KB) — ffprobe unavailable")
        return
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        info = _json.loads(probe.stdout)
        stream: dict[str, Any] = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
        fmt = info.get("format", {})
        codec = stream.get("codec_name", "?")
        channels = stream.get("channels", "?")
        rate = stream.get("sample_rate", "?")
        duration = float(fmt.get("duration") or stream.get("duration") or 0)
        size_kb = int(fmt.get("size", 0)) / 1024

        # Peak dBFS via volumedetect filter
        peak_result = subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-af", "volumedetect", "-f", "null", "/dev/null"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        peak_line = next((ln for ln in peak_result.stderr.splitlines() if "max_volume" in ln), "")
        peak_db = peak_line.split("max_volume:")[-1].strip() if peak_line else "unknown"

        print(f"  Audio: {codec} {channels}ch {rate}Hz {duration:.1f}s {size_kb:.0f}KB — peak {peak_db}")
    except Exception as exc:
        print(f"  Audio stats: could not probe {path}: {exc}")


def _wav_seconds(path: str) -> float | None:
    """Duration of a PCM WAV via the stdlib; None for formats wave can't read."""
    import wave

    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return None


def _beat_to_seconds(markers: list, beat: float) -> float | None:
    """Interpolate a clip beat to file seconds through its warp markers."""
    if not markers:
        return None
    pts = sorted((float(b), float(t)) for b, t in markers)
    if len(pts) == 1:
        return pts[0][1]
    pairs = list(zip(pts, pts[1:]))
    for k, ((b0, s0), (b1, s1)) in enumerate(pairs):
        if beat <= b1 or k == len(pairs) - 1:  # past the last marker: extrapolate the last segment
            return s0 + (beat - b0) * (s1 - s0) / (b1 - b0)
    return None


def _export(
    source_path: str,
    out_path: str,
    beats: float,
    tempo: float,
    want_wav: bool,
) -> str | None:
    """Copy WAV as-is or convert to MP3 trimmed to exact duration."""
    if not source_path or not os.path.exists(source_path):
        print(f"  Source file not found: {source_path}")
        return None

    _log_audio_stats(source_path)

    duration_secs = (beats / tempo) * 60

    if want_wav:
        import shutil

        shutil.copy2(source_path, out_path)
        size_kb = os.path.getsize(out_path) / 1024
        # The WAV is copied untrimmed, so report its real length, not the
        # requested one (the take includes pre-roll and tail).
        actual = _wav_seconds(out_path)
        length = f"{actual:.1f}s" if actual is not None else "length unknown"
        print(f"  Exported WAV: {out_path} ({size_kb:.0f} KB, {length}; requested {duration_secs:.1f}s)")
        return out_path

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            source_path,
            "-t",
            str(duration_secs),
            "-b:a",
            "192k",
            "-ar",
            "44100",
            out_path,
        ],
        capture_output=True,
        check=True,
    )
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Exported: {out_path} ({size_kb:.0f} KB, {duration_secs:.1f}s)")
    return out_path
