"""OSC (Path A) one-knob sweep runner — bounces via the native Export dialog,
with an ISOLATED-TRACK render instead of a realtime record-per-setting pass.

This is the offline-export sibling of `run_sweep_osc.py`. Same parameter loop
(set + read-back over AbletonOSC, no MCP bridge needed), but the bounce step
drives Ableton's own "Export Audio/Video" dialog (Cmd+Shift+R) headlessly via
`export_audio.applescript`, instead of a realtime MIDI-record pass. Offline
export is far faster than realtime record-per-setting, and setting the
dialog's "Rendered Track" chooser to the swept instrument's OWN track name
gives a genuinely isolated stem for free -- no solo/mute juggling, no looped
single-track export per track, no separate multitrack mechanism.

    1. capture the parameter's original value (so we can restore it)
    2. for each grid value: set it, settle, read the TRUE value + value_string
    3. bounce an isolated stem of `track_name` via the Export dialog driver
    4. fail fast on a dead bounce (reuses `run_sweep_stem.assert_bounce_alive`)
    5. write a sidecar params.json per setting (+ a summary CSV)
    6. restore the original value

The sidecar/CSV schema matches `run_sweep_osc.py` field-for-field, with a few
additions this runner needs (`track_mode`, `start_bar`, `wav_kb`, `peak_dbfs`).

Spec requirements beyond `run_sweep_osc.py`'s (`sweep_id`, `track`, `device`,
`param`, `start`, `stop`, `steps`): a `track_name` field giving the EXACT
"Rendered Track" dropdown text for the swept instrument's own track (e.g.
"Kick (G)") -- this is what makes the bounce isolated. Optional `start_bar`
(0-based bar to render from; default 0) matters because the Export dialog's
Render Start otherwise defaults to wherever the arrangement's edit cursor
last sat, NOT bar 0 -- see `export_audio.applescript`'s header comment.

Run with Live on a virtual display (see the virtual-display skill) so the
GUI automation stays off your physical screen.

Examples:
    uv run python sweeps/run_sweep_export.py --sweep sweeps/roar_drive.sweep.json
    uv run python sweeps/run_sweep_export.py --sweep sweeps/roar_drive.sweep.json --allow-silent
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Import the AbletonOSC client shipped with the skill.
_SKILL_SCRIPTS = os.path.expanduser("~/.agents/skills/ableton-live-control/scripts")
sys.path.insert(0, _SKILL_SCRIPTS)
from live import Live  # noqa: E402

# Reuse the proven fail-fast WAV checks instead of reimplementing peak/silence
# detection (sibling module, same folder -- Python auto-adds the script's own
# directory to sys.path[0]).
from run_sweep_stem import assert_bounce_alive  # noqa: E402

_EXPORTER = os.path.join(_SKILL_SCRIPTS, "export_audio.applescript")


def _bounce_via_export(
    out_dir: Path, index: int, bars: int, track_mode: str, start_bar: int,
    timeout_s: float,
) -> Path | None:
    """Render an ISOLATED stem of `track_mode` to a UNIQUE wav via the native
    Export dialog driver. A fresh nonce filename guarantees the "replace
    existing?" sheet never appears (that sheet is what wedges the exporter).

    Returns the actual wav Path on success, else None. The actual path can
    differ from the requested one: any trackMode other than "Main" makes Live
    append " <TrackName>" before the extension (see the exporter's header
    comment) -- the exporter script itself resolves and returns this actual
    path on stdout, so the caller never has to guess it.
    """
    nonce = time.strftime("%H%M%S") + f"_{time.time_ns() % 100000:05d}"
    wav_name = f"bounce_{index:03d}_{nonce}.wav"
    wav_path = out_dir / wav_name
    try:
        proc = subprocess.run(
            ["osascript", _EXPORTER, str(wav_path), "WAV", "16", "44100",
             str(bars), track_mode, str(start_bar)],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        print(f"  bounce timed out at index {index}")
        return None
    if proc.returncode != 0:
        print(f"  bounce failed at index {index}: {proc.stderr.strip()[-300:]}")
        return None
    actual_lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    if not actual_lines:
        print(f"  bounce at index {index} returned no path on stdout")
        return None
    actual_path = Path(actual_lines[-1].strip())
    if not actual_path.exists():
        print(f"  bounce at index {index}: expected file missing: {actual_path}")
        return None
    return actual_path


def load_spec(path: str) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text())
    for key in ("sweep_id", "track", "device", "param", "start", "stop", "steps", "track_name"):
        if key not in spec:
            raise ValueError(f"sweep spec missing required field: {key!r}")
    return spec


def value_grid(spec: dict[str, Any]) -> list[float]:
    start, stop, steps = float(spec["start"]), float(spec["stop"]), int(spec["steps"])
    if steps < 2:
        return [start]
    span = stop - start
    return [start + span * i / (steps - 1) for i in range(steps)]


def _param_value(live: Live, t: int, d: int, p: int) -> float:
    # get replies echo the indices: [track, device, param, value]
    return float(live.get("/live/device/get/parameter/value", t, d, p)[-1])


def _param_value_string(live: Live, t: int, d: int, p: int) -> str:
    return str(live.get("/live/device/get/parameter/value_string", t, d, p)[-1])


def run(spec: dict[str, Any], out_dir: Path, settle: float, do_restore: bool,
        bounce: bool, bounce_bars: int, start_bar: int, bounce_timeout: float,
        min_wav_kb: float, min_peak_dbfs: float, allow_silent: bool) -> None:
    t, d, p = int(spec["track"]), int(spec["device"]), int(spec["param"])
    track_name = spec["track_name"]
    live = Live()
    if not live.ping():
        raise SystemExit("AbletonOSC not reachable — is Live running with the control surface enabled?")

    out_dir.mkdir(parents=True, exist_ok=True)
    original = _param_value(live, t, d, p)
    original_str = _param_value_string(live, t, d, p)
    print(f"Sweep {spec['sweep_id']}: track {t} device {d} param {p} "
          f"({spec.get('param_name', '?')})")
    print(f"Original value = {original} ({original_str}) -- will "
          f"{'restore' if do_restore else 'NOT restore'} afterward")
    if bounce:
        print(f"Bounce: isolated export of track {track_name!r}, "
              f"{bounce_bars} bars from bar {start_bar} (0-based)")

    rows: list[dict[str, Any]] = []
    values = value_grid(spec)
    try:
        for i, value in enumerate(values):
            live.set("/live/device/set/parameter/value", t, d, p, value)
            time.sleep(settle)
            true_value = _param_value(live, t, d, p)
            value_string = _param_value_string(live, t, d, p)
            print(f"[{i:02d}] requested={value:.4f}  true={true_value:.6f}  ({value_string})")

            wav_name = None
            wav_kb = None
            peak_dbfs = None
            if bounce:
                wav_path = _bounce_via_export(
                    out_dir, i, bounce_bars, track_name, start_bar, bounce_timeout,
                )
                if wav_path is None:
                    raise RuntimeError(
                        f"bounce failed at index {i}; check the exporter's stderr above, "
                        "and that Live's Export dialog isn't stuck open"
                    )
                wav_kb, peak_dbfs_val = assert_bounce_alive(
                    wav_path, i, min_wav_kb, min_peak_dbfs, allow_silent,
                )
                peak_dbfs = None if peak_dbfs_val == float("-inf") else round(peak_dbfs_val, 3)
                wav_name = wav_path.name
                peak_txt = "-inf" if peak_dbfs is None else f"{peak_dbfs:.1f}"
                print(f"     bounce -> {wav_name} ({wav_kb:.0f} KB, peak {peak_txt} dBFS)")

            sidecar = {
                "sweep_id": spec["sweep_id"],
                "index": i,
                "path": "export",
                "instrument": spec.get("instrument", ""),
                "track": t, "device": d, "param": p,
                "param_name": spec.get("param_name", ""),
                "unit": spec.get("unit", ""),
                "requested_value": value,
                "true_value": true_value,
                "value_string": value_string,
                "predicted_measure": spec.get("predicted_measure"),
                "predicted_direction": spec.get("predicted_direction"),
                "measure": None,  # filled by the lab (ears) once a bounce exists
                "wav": wav_name,  # None unless --bounce; isolated export of track_mode
                "track_mode": track_name if bounce else None,
                "start_bar": start_bar if bounce else None,
                "bounce_bars": bounce_bars if bounce else None,
                "wav_kb": round(wav_kb, 1) if wav_kb is not None else None,
                "peak_dbfs": peak_dbfs,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            (out_dir / f"setting_{i:03d}.params.json").write_text(json.dumps(sidecar, indent=2))
            rows.append(sidecar)
    finally:
        if do_restore:
            live.set("/live/device/set/parameter/value", t, d, p, original)
            time.sleep(settle)
            restored = _param_value(live, t, d, p)
            print(f"Restored to {restored} ({_param_value_string(live, t, d, p)})")

    csv_path = out_dir / f"{spec['sweep_id']}.curve.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "requested_value", "true_value", "value_string", "wav", "measure"])
        for r in rows:
            writer.writerow([r["index"], r["requested_value"], r["true_value"],
                             r["value_string"], r["wav"], r["measure"]])
    print(f"\nWrote {len(rows)} sidecars + {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep", required=True)
    parser.add_argument("--no-restore", action="store_true", help="Leave the swept value at its last setting.")
    parser.add_argument("--bounce", action="store_true", help="Render an isolated WAV per setting via the native Export dialog (run with Live on a virtual display).")
    parser.add_argument("--bounce-bars", type=int, default=None, help="Render length in bars (default from spec 'bounce_bars' or 2).")
    parser.add_argument("--start-bar", type=int, default=None, help="0-based render start bar (default from spec 'start_bar' or 0). The dialog otherwise defaults to the arrangement's last edit-cursor position, not bar 0.")
    parser.add_argument("--bounce-timeout", type=float, default=200.0, help="Per-setting subprocess timeout (s) for the exporter. Increase for long bounce_bars: the exporter's own internal poll caps at 120s.")
    parser.add_argument("--min-wav-kb", type=float, default=50.0, help="Silent-bounce guard: abort if a bounce wav is smaller than this (KB).")
    parser.add_argument("--min-peak-dbfs", type=float, default=-60.0, help="Silent-bounce guard: abort if a bounce's peak is below this (dBFS).")
    parser.add_argument("--allow-silent", action="store_true", help="Skip the silent-bounce guard (for deliberate silence tests, or a known-quiet project section).")
    args = parser.parse_args()

    spec = load_spec(args.sweep)
    out_dir = Path(spec.get("output_dir") or f"out/{spec['sweep_id']}")
    if not out_dir.is_absolute():
        out_dir = Path(args.sweep).resolve().parent / out_dir
    settle = float(spec.get("settle_seconds", 0.25))
    do_restore = spec.get("restore", True) and not args.no_restore
    bounce_bars = args.bounce_bars if args.bounce_bars is not None else int(spec.get("bounce_bars", 2))
    start_bar = args.start_bar if args.start_bar is not None else int(spec.get("start_bar", 0))

    run(spec, out_dir, settle=settle, do_restore=do_restore,
        bounce=args.bounce, bounce_bars=bounce_bars, start_bar=start_bar,
        bounce_timeout=args.bounce_timeout, min_wav_kb=args.min_wav_kb,
        min_peak_dbfs=args.min_peak_dbfs, allow_silent=args.allow_silent)


if __name__ == "__main__":
    main()
