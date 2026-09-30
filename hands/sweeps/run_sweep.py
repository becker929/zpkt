"""One-knob sweep driver — the keystone spike (§5 #1/#2, §6 seam).

Reads a `sweep.json` spec, optionally (re)builds the base instrument once, then
for each parameter value:

    1. set the parameter          (one execute() call)
    2. read the TRUE value back   (a SEPARATE execute() call -- LOM Rule 1)
    3. bounce isolated audio      (hands.recorder.record_via_resampling)
    4. write a sidecar params.json next to the WAV

Output per setting is exactly the §6 handshake:
    out/<sweep_id>/bounce_NNN.wav
    out/<sweep_id>/bounce_NNN.params.json

The loop is resumable: an index whose WAV + sidecar already exist is skipped,
and `--resume-from N` skips everything below N. This is what lets an overnight
sweep survive a mid-run Live crash (rerun the same command; done rows are kept).

Requires the MCP bridge (Path B) up on 127.0.0.1:16619. Use `--dry-run` to
validate the plan and the generated LOM snippets without touching Live.

Examples:
    # validate offline (no Ableton needed)
    uv run python sweeps/run_sweep.py --sweep sweeps/kick_pitch.sweep.json --dry-run

    # build the instrument, then sweep for real
    uv run python sweeps/run_sweep.py --sweep sweeps/kick_pitch.sweep.json --build

    # resume a crashed sweep from setting 6 (instrument already built)
    uv run python sweeps/run_sweep.py --sweep sweeps/kick_pitch.sweep.json --resume-from 6
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow importing the sibling base_kick module regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent))

from hands.recorder import record_via_resampling  # noqa: E402
from hands.transport import DryRunTransport, LiveMcpTransport, McpResult  # noqa: E402


# ---------------------------------------------------------------------------
# Spec + value grid
# ---------------------------------------------------------------------------

def load_spec(path: str) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text())
    for key in ("sweep_id", "device_expr", "param_name", "start", "stop", "steps"):
        if key not in spec:
            raise ValueError(f"sweep spec missing required field: {key!r}")
    return spec


def value_grid(spec: dict[str, Any]) -> list[float]:
    start, stop, steps = float(spec["start"]), float(spec["stop"]), int(spec["steps"])
    if steps < 1:
        raise ValueError("steps must be >= 1")
    if steps == 1:
        vals = [start]
    else:
        span = stop - start
        vals = [start + span * i / (steps - 1) for i in range(steps)]
    if spec.get("integer_values"):
        vals = [float(round(v)) for v in vals]
    return vals


# ---------------------------------------------------------------------------
# LOM snippets (kept tiny; obey the crash-avoidance rules)
# ---------------------------------------------------------------------------

def _set_code(device_expr: str, param_name: str, value: float) -> str:
    # Write only. No readback in the same call (LOM Rule 1).
    return (
        f"dev = {device_expr}\n"
        f"_p = next((p for p in dev.parameters if p.name == {param_name!r}), None)\n"
        f"if _p is not None: _p.value = {value}\n"
        f"result = 'set' if _p is not None else 'PARAM_NOT_FOUND'"
    )


def _read_code(device_expr: str, param_name: str) -> str:
    # Separate call: read the true value the engine settled on.
    return (
        f"dev = {device_expr}\n"
        f"result = next((p.value for p in dev.parameters if p.name == {param_name!r}), None)"
    )


def _run(transport: Any, code: str) -> McpResult:
    return transport.execute(code)


# ---------------------------------------------------------------------------
# Build the base instrument once
# ---------------------------------------------------------------------------

def build_instrument(transport: Any) -> None:
    import base_kick
    from hands.builder import ProjectBuilder
    from hands.runner import ManualPolicy, StepRunner

    steps = ProjectBuilder(base_kick.build_config()).build_steps()
    print(f"Building base instrument: {len(steps)} steps")
    runner = StepRunner(transport)
    results = runner.execute(steps, on_manual=ManualPolicy.SKIP)
    failed = [r for r in results if r.status in ("error", "aborted")]
    if failed:
        raise RuntimeError(
            f"Instrument build failed at step {failed[0].index} "
            f"({failed[0].label!r}): {failed[0].error}"
        )


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def run_sweep(
    spec: dict[str, Any],
    transport: Any,
    out_dir: Path,
    resume_from: int,
    dry_run: bool,
) -> None:
    device_expr = spec["device_expr"]
    param_name = spec["param_name"]
    beats = float(spec.get("bounce_beats", 16))
    settle = float(spec.get("settle_seconds", 0.4))
    values = value_grid(spec)

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Sweep {spec['sweep_id']}: {param_name} over {values}")
    print(f"Output: {out_dir}")

    for i, value in enumerate(values):
        wav_name = f"bounce_{i:03d}.wav"
        wav_path = out_dir / wav_name
        sidecar_path = out_dir / f"bounce_{i:03d}.params.json"

        if i < resume_from:
            print(f"[{i:03d}] skip (resume-from {resume_from})")
            continue
        if wav_path.exists() and sidecar_path.exists():
            print(f"[{i:03d}] skip (already have wav + sidecar)")
            continue

        print(f"\n[{i:03d}] {param_name} = {value}")

        set_code = _set_code(device_expr, param_name, value)
        read_code = _read_code(device_expr, param_name)

        if dry_run:
            print("  --- set ---")
            print("  " + set_code.replace("\n", "\n  "))
            print("  --- read ---")
            print("  " + read_code.replace("\n", "\n  "))
            print(f"  --- bounce {beats} beats -> {wav_path} ---")
            continue

        set_res = _run(transport, set_code)
        if set_res.status != "ok" or set_res.result == "PARAM_NOT_FOUND":
            raise RuntimeError(
                f"set failed at index {i}: status={set_res.status} "
                f"result={set_res.result} error={set_res.error}"
            )
        time.sleep(settle)

        read_res = _run(transport, read_code)
        true_value = read_res.result if read_res.status == "ok" else None

        result_path = record_via_resampling(
            transport=transport,
            filename=wav_name,
            duration_beats=beats,
            output_dir=str(out_dir),
        )
        if result_path is None:
            raise RuntimeError(f"bounce failed at index {i} (no audio captured)")

        sidecar = {
            "sweep_id": spec["sweep_id"],
            "index": i,
            "wav": wav_name,
            "instrument": spec.get("instrument", ""),
            "device_expr": device_expr,
            "param_name": param_name,
            "unit": spec.get("unit", ""),
            "requested_value": value,
            "true_value": true_value,
            "bounce_beats": beats,
            "predicted_measure": spec.get("predicted_measure"),
            "predicted_direction": spec.get("predicted_direction"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        sidecar_path.write_text(json.dumps(sidecar, indent=2))
        print(f"  wrote {wav_name} + sidecar (true_value={true_value})")

    print("\nSweep complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep", required=True, help="Path to a sweep.json spec.")
    parser.add_argument("--build", action="store_true", help="(Re)build the base instrument before sweeping.")
    parser.add_argument("--resume-from", type=int, default=0, help="Skip settings below this index.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; never contact Ableton.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=16619)
    args = parser.parse_args()

    spec = load_spec(args.sweep)
    out_dir = Path(spec.get("output_dir") or f"out/{spec['sweep_id']}")
    # Resolve relative to the spec file's directory for stable output location.
    if not out_dir.is_absolute():
        out_dir = Path(args.sweep).resolve().parent / out_dir

    transport = DryRunTransport() if args.dry_run else LiveMcpTransport(host=args.host, port=args.port)

    if args.build:
        if args.dry_run:
            print("(dry-run) would build base instrument here")
        else:
            build_instrument(transport)

    run_sweep(spec, transport, out_dir, resume_from=args.resume_from, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
