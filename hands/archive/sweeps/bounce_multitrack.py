"""Path-B multitrack bounce: one isolated stem per surviving Live track.

Implements `research/live-multitrack-bounce.md` / `specs/multitrack_bounce.job.json`,
reusing the tap+record mechanism `run_sweep_stem.py` already proved (see that
file's module docstring). The one deliberate difference: this plays the set's
OWN ARRANGEMENT once per source track (start to `song.last_event_time`), not a
synthetic session-clip loop, because the point is to capture the real
performance.

Per surviving track it writes the seam pair:
    out_dir/<NN>__<slug>.wav
    out_dir/<NN>__<slug>.params.json

`<NN>` is the 0-based `song.tracks[i]` index, zero-padded to 2 digits. `<slug>`
is the track name lowercased with runs of non [a-z0-9] collapsed to one '-'.

Resumable: a track index whose wav + sidecar both already exist is skipped.

Track selection is NOT done by this script -- the caller passes an explicit,
ordered list of track indices to bounce (`--tracks 6,8,11,14,22,23,26`), so the
priority order (kick, bass/rumble, then everything else) is a caller decision,
made once after inspecting `song.tracks` (mute/group/empty), not re-derived
here on every run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hands.transport import LiveMcpTransport, McpResult  # noqa: E402

from run_sweep_stem import (  # noqa: E402  (sibling module, same folder)
    assert_bounce_alive,
    wav_peak_dbfs,
)


def _run(t: LiveMcpTransport, code: str) -> McpResult:
    r = t.execute(code)
    if r.status != "ok":
        raise RuntimeError(f"MCP error running code:\n{code}\n-> {r.error}")
    return r


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "track"


def ensure_capture_track(t: LiveMcpTransport, capture_track: int, source_name: str) -> None:
    """Route the source track's output into the capture track and arm it."""
    _run(t, (
        f"tr = song.tracks[{capture_track}]\n"
        f"_rt = next((rt for rt in tr.available_input_routing_types"
        f" if rt.display_name == {source_name!r}), None)\n"
        f"if _rt is None: raise RuntimeError('capture-input routing not available: '"
        f" + str([x.display_name for x in tr.available_input_routing_types]))\n"
        f"tr.input_routing_type = _rt\n"
        f"tr.arm = 1\n"
        f"tr.current_monitoring_state = 1\n"
        f"result = tr.input_routing_type.display_name"
    ))


def track_meta(t: LiveMcpTransport, idx: int) -> dict[str, Any]:
    """Name/mute/frozen + device chain summary. One call, proven PLAYBOOK pattern."""
    r = _run(t, (
        f"tr = song.tracks[{idx}]\n"
        f"result = {{'name': tr.name, 'mute': bool(tr.mute), 'frozen': bool(tr.is_frozen),"
        f" 'devices': [{{'index': i, 'name': d.name, 'class_name': d.class_name,"
        f" 'on': d.parameters[0].value}} for i, d in enumerate(tr.devices)]}}"
    ))
    return r.result


def bounce_arrangement(
    t: LiveMcpTransport,
    out_wav: Path,
    capture_track: int,
    source_track: int,
    arrangement_beats: float,
    tempo: float,
    settle_seconds: float,
) -> bool:
    """Record the whole arrangement, tapped from `source_track`, into `out_wav`."""
    # Clear any prior recordings on the capture track.
    _run(t, (
        f"tr = song.tracks[{capture_track}]\n"
        f"[tr.delete_clip(c) for c in list(tr.arrangement_clips)]\n"
        f"for s in range(8):\n"
        f"    cs = tr.clip_slots[s]\n"
        f"    if cs.has_clip: cs.delete_clip()\n"
        f"result = 'cleared'"
    ))
    # Play the set's OWN arrangement from the top (not a session-clip loop).
    # Arm record_mode BEFORE start_playing() (one call): some tracks have their
    # only clip sitting at/near beat 0, and a short clip (<1s) can finish
    # playing before a separate later "arm" call reaches Live over MCP. Arming
    # first guarantees the capture starts exactly when the transport does.
    _run(t, (
        f"song.loop = 0\n"
        f"song.back_to_arranger = 0\n"
        f"song.current_song_time = 0.0\n"
        f"song.record_mode = 1\n"
        f"song.start_playing()\n"
        f"result = 'rec+play'"
    ))
    time.sleep(arrangement_beats / tempo * 60.0 + settle_seconds)
    _run(t, "song.record_mode = 0; song.stop_playing(); result = 'stop'")
    time.sleep(0.5)

    fp = _run(t, (
        f"acs = list(song.tracks[{capture_track}].arrangement_clips)\n"
        f"result = acs[0].file_path if acs else None"
    )).result
    if not fp:
        print("  bounce: no recorded clip found")
        return False
    src = Path(fp)
    if not src.exists():
        print(f"  bounce: recorded file missing on disk: {fp}")
        return False
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, out_wav)
    return True


def run(args: argparse.Namespace) -> None:
    t = LiveMcpTransport(host=args.host, port=args.port)
    ping = t.execute("result = 1 + 1")
    if ping.status != "ok" or ping.result != 2:
        raise SystemExit(f"MCP bridge not reachable on {args.host}:{args.port} ({ping.error})")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tempo = float(_run(t, "result = song.tempo").result)
    arrangement_beats = float(_run(t, "result = song.last_event_time").result)
    print(f"tempo={tempo} BPM, arrangement_beats={arrangement_beats} "
          f"({arrangement_beats / tempo * 60.0:.1f}s per pass)")

    track_indices = [int(x) for x in args.tracks.split(",") if x.strip() != ""]

    try:
        _bounce_all(t, track_indices, out_dir, tempo, arrangement_beats, args)
    finally:
        # Disarm the capture track no matter how the batch ends (success,
        # early stop, or exception) so a failed run never leaves Live armed.
        t.execute(f"song.tracks[{args.capture_track}].arm = 0; result = 'disarmed'")
        print("Capture track disarmed.")


def _bounce_all(
    t: LiveMcpTransport,
    track_indices: list[int],
    out_dir: Path,
    tempo: float,
    arrangement_beats: float,
    args: argparse.Namespace,
) -> None:
    for idx in track_indices:
        meta = track_meta(t, idx)
        name = meta["name"]
        slug = slugify(name)
        stem = f"{idx:02d}__{slug}"
        wav_path = out_dir / f"{stem}.wav"
        sidecar_path = out_dir / f"{stem}.params.json"

        if wav_path.exists() and sidecar_path.exists():
            print(f"[{idx:02d}] {name!r}: skip (already have wav + sidecar)")
            continue

        if meta["mute"]:
            print(f"[{idx:02d}] {name!r}: SKIP requested track is muted (not bounced)")
            continue

        print(f"[{idx:02d}] {name!r}: taps capture track {args.capture_track}, recording...")
        ensure_capture_track(t, args.capture_track, name)

        ok = False
        for attempt in (1, 2):
            ok = bounce_arrangement(
                t, wav_path, args.capture_track, idx,
                arrangement_beats, tempo, args.settle_seconds,
            )
            if ok:
                try:
                    assert_bounce_alive(
                        wav_path, idx, args.min_wav_kb, args.min_peak_dbfs, args.allow_silent,
                    )
                    break
                except RuntimeError as exc:
                    ok = False
                    print(f"  attempt {attempt} looked dead: {exc}")
                    if attempt == 1:
                        print("  known-failure-mode retry (arrangement playback silence)...")
                        continue
            else:
                if attempt == 1:
                    print("  attempt 1 produced no clip; retrying once...")
                    continue
        if not ok:
            raise RuntimeError(
                f"track {idx} ({name!r}) bounce failed twice; stopping so a re-run can resume here"
            )

        with wave.open(str(wav_path), "rb") as wf:
            sample_rate = wf.getframerate()

        sidecar = {
            "track_index": idx,
            "track_name": name,
            "device_chain": meta["devices"],
            "tempo": tempo,
            "frozen": meta["frozen"],
            "muted": meta["mute"],
            "sample_rate": sample_rate,
            "wav": wav_path.name,
            "source_set": args.source_set,
            "capture_track": args.capture_track,
            "arrangement_length_beats": arrangement_beats,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        sidecar_path.write_text(json.dumps(sidecar, indent=2))
        size_kb = wav_path.stat().st_size / 1024.0
        peak = wav_peak_dbfs(wav_path)
        peak_txt = "-inf" if peak == float("-inf") else f"{peak:.1f}"
        print(f"  -> {wav_path.name} ({size_kb:.0f} KB, peak {peak_txt} dBFS, {sample_rate} Hz)")
    print("Batch done.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tracks", required=True, help="Comma-separated 0-based song.tracks indices, in bounce order.")
    p.add_argument("--capture-track", type=int, required=True, help="Empty/reusable audio track index used to tap+record.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--source-set", required=True, help="Path to the clone .als, recorded in each sidecar for provenance.")
    p.add_argument("--settle-seconds", type=float, default=0.5)
    p.add_argument("--min-wav-kb", type=float, default=50.0)
    p.add_argument("--min-peak-dbfs", type=float, default=-60.0)
    p.add_argument("--allow-silent", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=16619)
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
