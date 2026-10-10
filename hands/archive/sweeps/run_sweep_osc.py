"""OSC (Path A) one-knob sweep runner — set + read-back over AbletonOSC.

This is the Path-A counterpart to `run_sweep.py`. It proves the parameter half
of the loop against a *running* Live set without needing the MCP bridge:

    1. capture the parameter's original value (so we can restore it)
    2. for each grid value: set it, settle, read the TRUE value + value_string
    3. write a sidecar params.json per setting (+ a summary CSV)
    4. restore the original value

Optional `--bounce` renders isolated audio per setting via the native Export
dialog driver (`export_audio.applescript`) -- NO MCP bridge needed. It ALWAYS
writes a fresh, unique filename, so Live never hits the "replace existing?"
sheet (that sheet is what wedges the exporter). Run `--bounce` with Live on a
virtual display (see the virtual-display skill) so the GUI automation stays
off your physical screen. Without `--bounce`, each sidecar leaves `measure`
null and the lab (`ears`) fills it once a bounce exists -- keeping the §6 seam
intact: this side emits the exact parameter state + the WAV; measurement is
out-of-band.

Addressing is by (track, device, param) index -- AbletonOSC only reaches
top-level track devices, not nested drum-pad-chain devices (use Path B for
those). NB: the native export renders the master ("Main") mix; for a truly
isolated stem, solo the source track (or set the Export dialog's Rendered
Track Chooser -- not yet parameterized here).

Examples:
    uv run python sweeps/run_sweep_osc.py --sweep sweeps/roar_drive.sweep.json
    uv run python sweeps/run_sweep_osc.py --sweep sweeps/roar_drive.sweep.json --bounce
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

_EXPORTER = os.path.join(_SKILL_SCRIPTS, "export_audio.applescript")


def _bounce_via_export(out_dir: Path, index: int, bars: int) -> str | None:
    """Render the master to a UNIQUE wav via the native Export dialog driver.

    A fresh nonce filename guarantees the "replace existing?" sheet never
    appears (that sheet is what wedges the exporter). Returns the wav filename
    on success, else None.
    """
    nonce = time.strftime("%H%M%S") + f"_{time.time_ns() % 100000:05d}"
    wav_name = f"bounce_{index:03d}_{nonce}.wav"
    wav_path = out_dir / wav_name
    try:
        proc = subprocess.run(
            ["osascript", _EXPORTER, str(wav_path), "WAV", "16", "44100", str(bars)],
            capture_output=True, text=True, timeout=200,
        )
    except subprocess.TimeoutExpired:
        print(f"  bounce timed out at index {index}")
        return None
    if proc.returncode != 0 or not wav_path.exists():
        print(f"  bounce failed at index {index}: {proc.stderr.strip()[-200:]}")
        return None
    return wav_name


def load_spec(path: str) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text())
    for key in ("sweep_id", "track", "device", "param", "start", "stop", "steps"):
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
        bounce: bool, bounce_bars: int) -> None:
    t, d, p = int(spec["track"]), int(spec["device"]), int(spec["param"])
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
            if bounce:
                wav_name = _bounce_via_export(out_dir, i, bounce_bars)
                print(f"     bounce -> {wav_name}")

            sidecar = {
                "sweep_id": spec["sweep_id"],
                "index": i,
                "path": "osc",
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
                "wav": wav_name,  # None unless --bounce; native export of the master
                "bounce_bars": bounce_bars if bounce else None,
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
        writer.writerow(["index", "requested_value", "true_value", "value_string", "measure"])
        for r in rows:
            writer.writerow([r["index"], r["requested_value"], r["true_value"],
                             r["value_string"], r["measure"]])
    print(f"\nWrote {len(rows)} sidecars + {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep", required=True)
    parser.add_argument("--no-restore", action="store_true", help="Leave the swept value at its last setting.")
    parser.add_argument("--bounce", action="store_true", help="Render a WAV per setting via the native Export dialog (run with Live on a virtual display).")
    parser.add_argument("--bounce-bars", type=int, default=None, help="Render length in bars (default from spec 'bounce_bars' or 2).")
    args = parser.parse_args()

    spec = load_spec(args.sweep)
    out_dir = Path(spec.get("output_dir") or f"out/{spec['sweep_id']}")
    if not out_dir.is_absolute():
        out_dir = Path(args.sweep).resolve().parent / out_dir
    settle = float(spec.get("settle_seconds", 0.25))
    do_restore = spec.get("restore", True) and not args.no_restore
    bounce_bars = args.bounce_bars if args.bounce_bars is not None else int(spec.get("bounce_bars", 2))

    run(spec, out_dir, settle=settle, do_restore=do_restore,
        bounce=args.bounce, bounce_bars=bounce_bars)


if __name__ == "__main__":
    main()
