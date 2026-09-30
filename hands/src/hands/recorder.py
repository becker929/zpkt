# Recorder module
"""Record session clips via Ableton's resampling, then export as MP3 or WAV.

Uses an audio track set to 'Resampling' input to capture the master output
directly inside Ableton, then retrieves the audio file and optionally converts
to MP3 via ffmpeg (skipped when output filename ends with .wav).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from hands.transport import McpTransport


def _run(transport: McpTransport, code: str) -> Any:
    """Execute code via transport; return result or raise RuntimeError on error."""
    resp = transport.execute(code)
    if resp.status != "ok":
        raise RuntimeError(f"Ableton error: {resp.error}")
    return resp.result


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

    Args:
        transport: Live MCP transport to execute LOM code.
        filename: Output filename (with extension). Use .wav to skip ffmpeg.
        duration_beats: How many beats to record.
        output_dir: Directory to write the output file into.
        allow_clearing_arrangement: Proceed even if source tracks already
            have arrangement clips (they will be deleted).

    Returns:
        Absolute path to the exported file, or None on failure.
    """
    existing = _run(
        transport,
        # Group tracks raise on arrangement_clips; only leaf tracks hold clips.
        "sum(len(t.arrangement_clips) for t in song.tracks if not t.is_foldable)",
    ) or 0
    if existing and not allow_clearing_arrangement:
        raise RuntimeError(
            f"The set already has {existing} arrangement clip(s); record_via_resampling "
            "would delete them. Use record_arrangement to render the arrangement, or "
            "pass allow_clearing_arrangement=True."
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / filename)
    want_wav = filename.lower().endswith(".wav")

    _run(transport, "song.stop_playing()")
    time.sleep(0.3)

    _run(transport, "song.current_song_time = 0.0")
    time.sleep(0.1)
    current_pos = _run(transport, "song.current_song_time")
    print(f"  Rewound to beat 0, current_song_time = {current_pos}")

    # Copy session slot 0 clips into arrangement at beat 0 on every source
    # track. Arrangement playback is deterministic — no clip-triggering races.
    num_tracks_now = _run(transport, "len(song.tracks)")
    for i in range(num_tracks_now):
        has_clip = _run(transport, f"song.tracks[{i}].clip_slots[0].has_clip")
        if not has_clip:
            continue
        print(f"  Copying session clip on track {i} to arrangement at beat 0")
        # Clear any existing arrangement clips on this track first.
        _run(
            transport,
            f"[song.tracks[{i}].delete_clip(c) for c in list(song.tracks[{i}].arrangement_clips)]",
        )
        time.sleep(0.1)
        _run(
            transport,
            f"song.tracks[{i}].duplicate_clip_to_arrangement("
            f"song.tracks[{i}].clip_slots[0].clip, 0.0)",
        )
        time.sleep(0.2)

    # Set arrangement loop to exactly the requested duration.
    _run(transport, "song.loop = True")
    _run(transport, "song.loop_start = 0.0")
    _run(transport, f"song.loop_length = {duration_beats}")
    time.sleep(0.1)

    # Stop session clips so the arrangement (not session) drives playback.
    for i in range(num_tracks_now):
        _run(transport, f"song.tracks[{i}].stop_all_clips()")
    time.sleep(0.1)
    # stop_all_clips leaves each track following the (now stopped) session
    # and lights "Back to Arrangement"; clear it so arrangement clips play.
    _run(transport, "song.back_to_arranger = False")
    time.sleep(0.1)

    # Disarm source tracks. trigger_session_record() records on every armed
    # track, so an armed source (Live auto-arms the selected MIDI track) gets a
    # new empty clip that silences it, and the bounce comes out silent.
    armed = _run(
        transport,
        f"[i for i in range({num_tracks_now}) if song.tracks[i].can_be_armed and song.tracks[i].arm]",
    ) or []
    for i in armed:
        _run(transport, f"song.tracks[{i}].arm = 0")
    if armed:
        print(f"  Disarmed source tracks {armed} for the bounce")

    # Create and configure the resampling track.
    resample_idx = _run(transport, "len(song.tracks)")
    _run(transport, "song.create_audio_track(-1)")
    time.sleep(0.3)
    _run(transport, f'song.tracks[{resample_idx}].name = "Resample"')

    types = _run(
        transport,
        f"[t.display_name for t in song.tracks[{resample_idx}].available_input_routing_types]",
    )
    print(f"  Available input types: {types}")
    if not types or not any("Resamp" in str(t) for t in types):
        raise RuntimeError(f"Resampling input type not found. Available: {types}")

    # Must find and assign the actual RoutingType object in a single LOM call.
    _run(
        transport,
        f'_rt = next((rt for rt in song.tracks[{resample_idx}].available_input_routing_types'
        f' if "Resampling" in rt.display_name), None);'
        f' song.tracks[{resample_idx}].input_routing_type = _rt',
    )
    time.sleep(0.2)

    routing_type = _run(
        transport,
        f"song.tracks[{resample_idx}].input_routing_type.display_name",
    )
    print(f"  Resampling track input set to: {routing_type}")
    if "Resampling" not in str(routing_type):
        raise RuntimeError(f"Failed to set Resampling input — got: {routing_type}")

    _run(transport, f"song.tracks[{resample_idx}].arm = 1")
    _run(transport, f"song.tracks[{resample_idx}].current_monitoring_state = 1")  # Auto (0=In, 1=Auto, 2=Off)
    time.sleep(0.2)

    _run(transport, "song.session_record = 0")
    _run(transport, "song.overdub = 0")

    # Rewind once more in case track setup nudged the playhead.
    _run(transport, "song.current_song_time = 0.0")
    time.sleep(0.1)

    _run(transport, "song.trigger_session_record()")
    time.sleep(0.3)

    is_playing = _run(transport, "song.is_playing")
    if not is_playing:
        print("  Transport not started by trigger_session_record — calling start_playing()")
        _run(transport, "song.start_playing()")
        time.sleep(0.2)

    tempo = _run(transport, "song.tempo")
    wait_secs = (duration_beats / tempo) * 60 + 1.0
    print(f"  Recording for {wait_secs:.1f}s ({duration_beats} beats at {tempo} BPM)...")
    time.sleep(wait_secs)

    _run(transport, "song.stop_playing()")
    time.sleep(1.0)

    has_clip = _run(transport, f"song.tracks[{resample_idx}].clip_slots[0].has_clip")
    if not has_clip:
        for slot in range(8):
            has_clip = _run(
                transport,
                f"song.tracks[{resample_idx}].clip_slots[{slot}].has_clip",
            )
            if has_clip:
                file_path = _run(
                    transport,
                    f"song.tracks[{resample_idx}].clip_slots[{slot}].clip.file_path",
                )
                print(f"  Found recorded clip in slot {slot}: {file_path}")
                result = _export(file_path, out_path, duration_beats, tempo, want_wav)
                _run(transport, f"song.delete_track({resample_idx})")
                _cleanup_arrangement_clips(transport, num_tracks_now, armed)
                return result
        print("  No recorded clip found!")
        _cleanup_arrangement_clips(transport, num_tracks_now, armed)
        return None

    file_path = _run(
        transport,
        f"song.tracks[{resample_idx}].clip_slots[0].clip.file_path",
    )
    print(f"  Recorded audio file: {file_path}")

    result = _export(file_path, out_path, duration_beats, tempo, want_wav)
    _run(transport, f"song.delete_track({resample_idx})")
    _cleanup_arrangement_clips(transport, num_tracks_now, armed)
    return result


def record_arrangement(
    transport: McpTransport,
    filename: str,
    duration_beats: float,
    output_dir: str | Path = ".",
    tail_beats: float = 4.0,
) -> str | None:
    """Render the set's arrangement from beat 0 via a resampling track.

    Leaves the source tracks' arrangement clips alone. Records
    ``duration_beats + tail_beats`` in arrangement record mode, exports the
    take untrimmed, then removes the temporary track and restores the source
    tracks' arm state. The take starts at beat 0 to within ~10-20 ms (two
    takes of the same set differed by 12 ms), fine for cutting sections but
    not for sample-accurate nulling between takes.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / filename)
    want_wav = filename.lower().endswith(".wav")

    _run(transport, "song.stop_playing()")
    time.sleep(0.3)
    _run(transport, "song.loop = False")

    # Same silent-take causes as record_via_resampling: armed sources get
    # recorded over, and a lit "Back to Arrangement" ignores arrangement clips.
    armed = _run(
        transport,
        "[i for i, t in enumerate(song.tracks) if t.can_be_armed and t.arm]",
    ) or []
    for i in armed:
        _run(transport, f"song.tracks[{i}].arm = 0")
    _run(transport, "song.back_to_arranger = False")

    idx = _run(transport, "len(song.tracks)")
    _run(transport, "song.create_audio_track(-1)")
    time.sleep(0.3)
    _run(transport, f'song.tracks[{idx}].name = "Render"')
    _run(
        transport,
        f'_rt = next((rt for rt in song.tracks[{idx}].available_input_routing_types'
        f' if "Resampling" in rt.display_name), None);'
        f' song.tracks[{idx}].input_routing_type = _rt',
    )
    time.sleep(0.2)
    routing = _run(transport, f"song.tracks[{idx}].input_routing_type.display_name")
    if "Resampling" not in str(routing):
        _run(transport, f"song.delete_track({idx})")
        _restore_arm(transport, armed)
        raise RuntimeError(f"Failed to set Resampling input — got: {routing}")
    _run(transport, f"song.tracks[{idx}].arm = 1")
    time.sleep(0.2)

    _run(transport, "song.current_song_time = 0.0")
    time.sleep(0.1)
    _run(transport, "song.record_mode = True")
    _run(transport, "song.start_playing()")
    tempo = _run(transport, "song.tempo")
    wait_secs = (duration_beats + tail_beats) / tempo * 60 + 0.5
    print(f"  Recording arrangement for {wait_secs:.1f}s ({duration_beats}+{tail_beats} beats at {tempo} BPM)...")
    time.sleep(wait_secs)
    _run(transport, "song.stop_playing()")
    _run(transport, "song.record_mode = False")
    time.sleep(1.5)

    file_path = _run(
        transport,
        f"[c.file_path for c in song.tracks[{idx}].arrangement_clips][:1]",
    )
    result = None
    if file_path:
        print(f"  Recorded audio file: {file_path[0]}")
        result = _export(file_path[0], out_path, duration_beats + tail_beats, tempo, want_wav)
    else:
        print("  No recorded clip found!")
    _run(transport, f"song.delete_track({idx})")
    _restore_arm(transport, armed)
    return result


def _restore_arm(transport: McpTransport, armed: list[int]) -> None:
    for i in armed:
        _run(transport, f"song.tracks[{i}].arm = 1")


def _cleanup_arrangement_clips(
    transport: McpTransport, num_tracks: int, armed: list[int] = ()
) -> None:
    """Remove arrangement clips placed by record_via_resampling on source tracks,
    and re-arm the source tracks that were disarmed for the bounce."""
    for i in range(num_tracks):
        _run(
            transport,
            f"[song.tracks[{i}].delete_clip(c) for c in list(song.tracks[{i}].arrangement_clips)]",
        )
    for i in armed:
        _run(transport, f"song.tracks[{i}].arm = 1")


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
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                path,
            ],
            capture_output=True, text=True, timeout=15,
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
            capture_output=True, text=True, timeout=30,
        )
        peak_line = next(
            (ln for ln in peak_result.stderr.splitlines() if "max_volume" in ln), ""
        )
        peak_db = peak_line.split("max_volume:")[-1].strip() if peak_line else "unknown"

        print(
            f"  Audio: {codec} {channels}ch {rate}Hz {duration:.1f}s {size_kb:.0f}KB"
            f" — peak {peak_db}"
        )
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
            "ffmpeg", "-y",
            "-i", source_path,
            "-t", str(duration_secs),
            "-b:a", "192k",
            "-ar", "44100",
            out_path,
        ],
        capture_output=True,
        check=True,
    )
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Exported: {out_path} ({size_kb:.0f} KB, {duration_secs:.1f}s)")
    return out_path
