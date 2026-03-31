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
) -> str | None:
    """Create a resampling track, record the session, export as MP3 or WAV.

    Args:
        transport: Live MCP transport to execute LOM code.
        filename: Output filename (with extension). Use .wav to skip ffmpeg.
        duration_beats: How many beats to record.
        output_dir: Directory to write the output file into.

    Returns:
        Absolute path to the exported file, or None on failure.
    """
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
    _run(transport, f"song.tracks[{resample_idx}].current_monitoring_state = 1")  # In
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
                _cleanup_arrangement_clips(transport, num_tracks_now)
                return result
        print("  No recorded clip found!")
        _cleanup_arrangement_clips(transport, num_tracks_now)
        return None

    file_path = _run(
        transport,
        f"song.tracks[{resample_idx}].clip_slots[0].clip.file_path",
    )
    print(f"  Recorded audio file: {file_path}")

    result = _export(file_path, out_path, duration_beats, tempo, want_wav)
    _run(transport, f"song.delete_track({resample_idx})")
    _cleanup_arrangement_clips(transport, num_tracks_now)
    return result


def _cleanup_arrangement_clips(transport: McpTransport, num_tracks: int) -> None:
    """Remove arrangement clips placed by record_via_resampling on source tracks."""
    for i in range(num_tracks):
        _run(
            transport,
            f"[song.tracks[{i}].delete_clip(c) for c in list(song.tracks[{i}].arrangement_clips)]",
        )


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
        print(f"  Exported WAV: {out_path} ({size_kb:.0f} KB, {duration_secs:.1f}s)")
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
