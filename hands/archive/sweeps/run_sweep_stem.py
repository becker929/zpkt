"""Path-B one-knob sweep with an ISOLATED-STEM bounce (built-set variant).

This is the sibling of `run_sweep.py`. It targets a set that was *built from
plugins* by `hands execute --config base_kick.json` (Drum Rack + Simpler kick +
4-on-4 clip on track 1, with an empty audio track 0 as the reference slot).

Why a separate runner? On this machine Live's `Resampling` input capture and
freshly-created audio tracks return silent / empty routing after heavy track
churn, so `hands.recorder.record_via_resampling` bounces pure silence
(peak ~ -91 dB). The robust route that works here is:

    * tap the SOURCE track's output directly into the existing audio track 0
      (input routing = the source track name, e.g. "3-Kick") -> an isolated stem
    * play the kick from its SESSION clip (session playback is reliable here;
      arrangement playback intermittently renders silent)
    * arm track 0 + `song.record_mode = 1` to arrangement-record that stem
    * read the recorded clip's `file_path` and copy it out as `bounce_NNN.wav`

Per setting it writes the §6 handshake pair:
    out/<sweep_id>/bounce_NNN.wav
    out/<sweep_id>/bounce_NNN.params.json      (requested + read-back true value)

The loop is resumable: a setting whose wav + sidecar already exist is skipped.
`measure` stays null (filled out-of-band by the lab / `ears`).

Two ways to say *which* settings to bounce:

    * `start` / `stop` / `steps`  -> a linear grid (the original mode)
    * `values: [0.75, 0.782]`     -> an explicit list, used VERBATIM

The explicit list wins when present. It is not deduped and not rounded (so
`integer_values` is ignored for it): repeated values are meaningful, they give
the run-to-run bounce noise floor.

Every bounce is checked for life before its sidecar is written: too-small file
or a near-silent peak aborts the run (see `--min-wav-kb` / `--min-peak-dbfs`
and the `--allow-silent` escape hatch).

Examples:
    uv run python sweeps/run_sweep_stem.py --sweep sweeps/kick_pitch.sweep.json

    uv run python sweeps/run_sweep_stem.py \\
        --sweep sweeps/snts_kick_clip_values_demo.sweep.json \\
        --capture-track 44 --source-track 6 --source-input "Kick (G)"
"""
from __future__ import annotations

import argparse
import array
import csv
import json
import math
import shutil
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hands.transport import LiveMcpTransport, McpResult  # noqa: E402


# ---------------------------------------------------------------------------
# Spec + value grid  (kick_pitch.sweep.json compatible)
# ---------------------------------------------------------------------------

def load_spec(path: str) -> dict[str, Any]:
    """Read a sweep spec, requiring either an explicit `values` list or start/stop/steps."""
    spec = json.loads(Path(path).read_text())
    for key in ("sweep_id", "device_expr", "param_name"):
        if key not in spec:
            raise ValueError(f"sweep spec missing required field: {key!r}")
    if not has_explicit_values(spec):
        for key in ("start", "stop", "steps"):
            if key not in spec:
                raise ValueError(
                    f"sweep spec missing required field: {key!r}"
                    " (required unless the spec carries a non-empty 'values' list)"
                )
    return spec


def has_explicit_values(spec: dict[str, Any]) -> bool:
    """True when the spec pins the settings itself instead of describing a grid."""
    values = spec.get("values")
    return isinstance(values, (list, tuple)) and len(values) > 0


def grid_mode(spec: dict[str, Any]) -> str:
    """Short label for which value source the spec selects. For logging."""
    return "values" if has_explicit_values(spec) else "start_stop_steps"


def value_grid(spec: dict[str, Any]) -> list[float]:
    """The settings to bounce, in order.

    An explicit `values` list is used verbatim: order kept, duplicates kept,
    `integer_values` NOT applied (the caller already said exactly what it wants).
    """
    if has_explicit_values(spec):
        return [float(v) for v in spec["values"]]
    start, stop, steps = float(spec["start"]), float(spec["stop"]), int(spec["steps"])
    if steps < 2:
        return [start]
    span = stop - start
    vals = [start + span * i / (steps - 1) for i in range(steps)]
    if spec.get("integer_values"):
        vals = [float(round(v)) for v in vals]
    return vals


# ---------------------------------------------------------------------------
# Silent-bounce guard  (stdlib only: the bounces are 44.1k PCM wavs)
# ---------------------------------------------------------------------------

RIG_HINT = (
    "a dead bounce almost always means the rig is wrong: check the capture-track "
    "input routing (--source-input must be the source track's display name), that "
    "the source session clip actually fires, and that the source track is not "
    "muted / soloed out / at -inf"
)


def wav_peak_dbfs(path: Path) -> float:
    """Peak sample of a PCM wav in dBFS. `-inf` for digital silence.

    Raises ValueError if the file cannot be parsed as PCM (unreadable == dead).
    """
    try:
        with wave.open(str(path), "rb") as wf:
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError) as exc:
        raise ValueError(f"cannot read {path.name} as a PCM wav: {exc}") from exc
    if not frames:
        return -math.inf

    if width == 1:  # 8-bit wav is unsigned, centred on 128
        peak = max(abs(b - 128) for b in frames) / 128.0
    elif width in (2, 4):
        samples = array.array("h" if width == 2 else "i")
        samples.frombytes(frames[: len(frames) - len(frames) % width])
        full = float(1 << (8 * width - 1))
        peak = max(abs(min(samples)), abs(max(samples))) / full
    elif width == 3:
        full = float(1 << 23)
        worst = 0
        for off in range(0, len(frames) - 2, 3):
            worst = max(worst, abs(int.from_bytes(frames[off:off + 3], "little", signed=True)))
        peak = worst / full
    else:
        raise ValueError(f"unsupported sample width {width} bytes in {path.name}")

    return 20.0 * math.log10(peak) if peak > 0 else -math.inf


def assert_bounce_alive(
    wav_path: Path, index: int, min_kb: float, min_peak_dbfs: float, allow_silent: bool,
) -> tuple[float, float]:
    """Fail fast on a dead bounce. Returns (size_kb, peak_dbfs).

    A failure deletes the wav so a later resume retries that index, and writes no
    sidecar, so `out/` never gains a dead row.
    """
    size_kb = wav_path.stat().st_size / 1024.0
    try:
        peak_dbfs = wav_peak_dbfs(wav_path)
    except ValueError as exc:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"bounce {index:03d} is unreadable ({exc}); {RIG_HINT}") from exc

    if allow_silent:
        return size_kb, peak_dbfs

    peak_txt = "-inf" if peak_dbfs == -math.inf else f"{peak_dbfs:.1f}"
    problems: list[str] = []
    if size_kb < min_kb:
        problems.append(f"file is only {size_kb:.1f} KB (min {min_kb:.0f} KB)")
    if peak_dbfs < min_peak_dbfs:
        problems.append(f"peak is {peak_txt} dBFS (min {min_peak_dbfs:.0f} dBFS)")
    if problems:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"bounce {index:03d} looks dead: " + "; ".join(problems) + ".\n"
            f"Deleted {wav_path.name} and wrote no sidecar, so a re-run retries it.\n"
            f"{RIG_HINT}.\n"
            "If the silence is deliberate, re-run with --allow-silent."
        )
    return size_kb, peak_dbfs


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------

def _run(t: LiveMcpTransport, code: str) -> McpResult:
    r = t.execute(code)
    if r.status != "ok":
        raise RuntimeError(f"MCP error running code:\n{code}\n-> {r.error}")
    return r


def set_param(t: LiveMcpTransport, device_expr: str, param_name: str, value: float) -> None:
    # Write only — no readback in the same call (LOM Rule 1).
    _run(t, (
        f"dev = {device_expr}\n"
        f"_p = next((p for p in dev.parameters if p.name == {param_name!r}), None)\n"
        f"if _p is not None: _p.value = {value}\n"
        f"result = 'set' if _p is not None else 'PARAM_NOT_FOUND'"
    ))


def read_param(t: LiveMcpTransport, device_expr: str, param_name: str) -> Any:
    r = _run(t, (
        f"dev = {device_expr}\n"
        f"result = next((p.value for p in dev.parameters if p.name == {param_name!r}), None)"
    ))
    return r.result


# ---------------------------------------------------------------------------
# Isolated-stem bounce
# ---------------------------------------------------------------------------

def ensure_capture_track(t: LiveMcpTransport, capture_track: int, source_input: str) -> None:
    """Route the source track's output into the capture track and arm it."""
    _run(t, (
        f"tr = song.tracks[{capture_track}]\n"
        f"_rt = next((rt for rt in tr.available_input_routing_types"
        f" if rt.display_name == {source_input!r}), None)\n"
        f"if _rt is None: raise RuntimeError('capture-input routing not available: '"
        f" + str([x.display_name for x in tr.available_input_routing_types]))\n"
        f"tr.input_routing_type = _rt\n"
        f"tr.arm = 1\n"
        f"tr.current_monitoring_state = 1\n"
        f"result = tr.input_routing_type.display_name"
    ))


def bounce_stem(
    t: LiveMcpTransport, out_wav: Path, capture_track: int, source_track: int,
    beats: float, tempo: float,
) -> bool:
    """Record an isolated stem of `source_track` into `out_wav`. Returns success."""
    # Clear any prior recordings on the capture track.
    _run(t, (
        f"tr = song.tracks[{capture_track}]\n"
        f"[tr.delete_clip(c) for c in list(tr.arrangement_clips)]\n"
        f"for s in range(8):\n"
        f"    cs = tr.clip_slots[s]\n"
        f"    if cs.has_clip: cs.delete_clip()\n"
        f"result = 'cleared'"
    ))
    # Fire the source SESSION clip (session playback is reliable here).
    _run(t, (
        f"song.stop_all_clips()\n"
        f"song.current_song_time = 0.0\n"
        f"song.tracks[{source_track}].clip_slots[0].fire()\n"
        f"result = 'fired'"
    ))
    _run(t, "song.start_playing(); result = 'play'")
    time.sleep(0.4)
    # Arrangement-record the tapped stem for the requested number of beats.
    _run(t, "song.record_mode = 1; result = 'rec'")
    time.sleep(beats / tempo * 60.0 + 0.4)
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
    shutil.copy2(src, out_wav)
    return True


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def run(spec: dict[str, Any], out_dir: Path, args: argparse.Namespace) -> None:
    t = LiveMcpTransport(host=args.host, port=args.port)
    ping = t.execute("result = 1 + 1")
    if ping.status != "ok" or ping.result != 2:
        raise SystemExit(f"MCP bridge not reachable on {args.host}:{args.port} ({ping.error})")

    device_expr = spec["device_expr"]
    param_name = spec["param_name"]
    tempo = float(_run(t, "result = song.tempo").result)
    beats = float(args.beats if args.beats is not None else spec.get("bounce_beats", 8))
    settle = float(spec.get("settle_seconds", 0.4))
    values = value_grid(spec)
    mode = grid_mode(spec)

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Sweep {spec['sweep_id']}: {param_name} over {values}")
    if mode == "values":
        print(f"Value mode: EXPLICIT 'values' list ({len(values)} settings, used "
              f"verbatim; duplicates kept, integer_values ignored)")
    else:
        print(f"Value mode: start/stop/steps grid "
              f"({spec['start']} -> {spec['stop']}, {spec['steps']} steps"
              f"{', rounded to integers' if spec.get('integer_values') else ''})")
    print(f"Capture track {args.capture_track} <- input {args.source_input!r}; "
          f"source track {args.source_track}; {beats} beats @ {tempo} BPM")
    guard = ("DISABLED (--allow-silent)" if args.allow_silent else
             f"wav >= {args.min_wav_kb:.0f} KB and peak >= {args.min_peak_dbfs:.0f} dBFS")
    print(f"Silent-bounce guard: {guard}")
    print(f"Output: {out_dir}")

    original = read_param(t, device_expr, param_name)
    ensure_capture_track(t, args.capture_track, args.source_input)

    rows: list[dict[str, Any]] = []
    try:
        for i, value in enumerate(values):
            wav_name = f"bounce_{i:03d}.wav"
            wav_path = out_dir / wav_name
            sidecar_path = out_dir / f"bounce_{i:03d}.params.json"
            if wav_path.exists() and sidecar_path.exists():
                print(f"[{i:03d}] skip (already have wav + sidecar)")
                rows.append(json.loads(sidecar_path.read_text()))
                continue

            set_param(t, device_expr, param_name, value)
            time.sleep(settle)
            true_value = read_param(t, device_expr, param_name)
            print(f"[{i:03d}] {param_name} req={value}  true={true_value}")

            ok = bounce_stem(t, wav_path, args.capture_track, args.source_track, beats, tempo)
            if not ok:
                raise RuntimeError(f"bounce failed at index {i}; {RIG_HINT}")
            size_kb, peak_dbfs = assert_bounce_alive(
                wav_path, i, args.min_wav_kb, args.min_peak_dbfs, args.allow_silent,
            )
            peak_txt = "-inf" if peak_dbfs == -math.inf else f"{peak_dbfs:.1f}"
            print(f"     bounce -> {wav_name} ({size_kb:.0f} KB, peak {peak_txt} dBFS)")

            sidecar = {
                "sweep_id": spec["sweep_id"],
                "index": i,
                "path": "mcp-stem",
                "wav": wav_name,
                "instrument": spec.get("instrument", ""),
                "device_expr": device_expr,
                "param_name": param_name,
                "unit": spec.get("unit", ""),
                "value_source": mode,
                "requested_value": value,
                "true_value": true_value,
                "bounce_beats": beats,
                "tempo": tempo,
                "wav_kb": round(size_kb, 1),
                "peak_dbfs": None if peak_dbfs == -math.inf else round(peak_dbfs, 3),
                "capture_track": args.capture_track,
                "source_track": args.source_track,
                "source_input": args.source_input,
                "predicted_measure": spec.get("predicted_measure"),
                "predicted_direction": spec.get("predicted_direction"),
                "measure": None,  # filled out-of-band by the lab (ears)
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            sidecar_path.write_text(json.dumps(sidecar, indent=2))
            rows.append(sidecar)
    finally:
        if spec.get("restore", True) and original is not None and not args.no_restore:
            set_param(t, device_expr, param_name, float(original))
            print(f"Restored {param_name} to {original}")
        # Disarm the capture track so it stops monitoring input.
        t.execute(f"song.tracks[{args.capture_track}].arm = 0; result = 'disarmed'")

    csv_path = out_dir / f"{spec['sweep_id']}.curve.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "requested_value", "true_value", "wav", "measure"])
        for r in rows:
            w.writerow([r["index"], r["requested_value"], r["true_value"], r["wav"], r["measure"]])
    print(f"\nWrote {len(rows)} sidecars + {csv_path}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sweep", required=True)
    p.add_argument("--capture-track", type=int, default=0, help="Empty audio track used to record the stem.")
    p.add_argument("--source-track", type=int, default=1, help="Track whose session clip 0 plays the instrument.")
    p.add_argument("--source-input", default="3-Kick", help="Capture track input routing name (the source track).")
    p.add_argument("--beats", type=int, default=None, help="Bounce length in beats (default: spec bounce_beats or 8).")
    p.add_argument("--min-wav-kb", type=float, default=50.0,
                   help="Silent-bounce guard: abort if a bounce wav is smaller than this (KB).")
    p.add_argument("--min-peak-dbfs", type=float, default=-60.0,
                   help="Silent-bounce guard: abort if a bounce's peak is below this (dBFS).")
    p.add_argument("--allow-silent", action="store_true",
                   help="Skip the silent-bounce guard (for deliberate silence tests).")
    p.add_argument("--no-restore", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=16619)
    args = p.parse_args()

    spec = load_spec(args.sweep)
    out_dir = Path(spec.get("output_dir") or f"out/{spec['sweep_id']}")
    if not out_dir.is_absolute():
        out_dir = Path(args.sweep).resolve().parent / out_dir
    run(spec, out_dir, args)


if __name__ == "__main__":
    main()
