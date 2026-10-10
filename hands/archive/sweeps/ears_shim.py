"""ears_shim.py - canonical-key adapter so `--ears-cmd` is a true drop-in.

The real `ears` lab returns `loudness.band_energy["sub"]` (nested) and has NO
crest metric, so `assemble_curve.py --measure-keys crest_db sub_share ...` cannot
consume it directly. This shim normalizes everything to the flat canonical keys
the pipeline already uses:

    sub_share, low_share, mid_share, high_share, air_share, crest_db

It works TODAY (no real `ears` needed): band shares + crest come from
`measure_local`, whose band math is byte-identical to canonical `ears`. When a
real `ears` is on PATH (or via $EARS_CMD), its `loudness.band_energy` is used for
the shares (exact corpus fidelity) and its extra, gain-DEPENDENT metrics
(lufs/true_peak) are attached under `ears_extra` -- clearly flagged, because they
are only meaningful on properly-leveled full mixes, NOT on gain-scaled stems.

Interface (matches assemble_curve's caller):
    ears_shim.py analyze <wav> --json
Env:
    EARS_CMD   command to invoke real ears (default: "ears"); ignored if absent.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

import measure_local  # same directory; canonical band math + crest

_BANDS = ("sub", "low", "mid", "high", "air")


def _try_real_ears(wav: str) -> dict | None:
    """Run real ears if available; return its parsed JSON, else None."""
    ears_cmd = os.environ.get("EARS_CMD", "ears")
    argv = shlex.split(ears_cmd) + ["analyze", wav, "--json"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def analyze(wav: str) -> dict:
    # Canonical baseline (always available, corpus-faithful band math + crest).
    local = measure_local.measure(wav)
    result = {
        "measurer": "ears_shim (canonical band shares + crest_db)",
        "crest_db": local.get("crest_db"),
    }
    for b in _BANDS:
        result[f"{b}_share"] = local.get(f"{b}_share")

    # Upgrade shares to real ears' own numbers when available (exact fidelity),
    # and attach its extra gain-DEPENDENT metrics under a flagged key.
    real = _try_real_ears(wav)
    if real is not None:
        result["measurer"] = "ears_shim (real ears band shares + local crest_db)"
        band_energy = (real.get("loudness") or {}).get("band_energy") or {}
        for b in _BANDS:
            if b in band_energy:
                result[f"{b}_share"] = band_energy[b]
        loud = real.get("loudness") or {}
        extra = {k: loud.get(k) for k in (
            "lufs_integrated", "lufs_short_term_peak", "lufs_momentary_max",
            "true_peak_db", "camelot_key") if k in loud}
        if extra:
            extra["_warning"] = "gain-DEPENDENT; valid on full mixes, NOT on gain-scaled stems"
            result["ears_extra"] = extra
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="Measure one audio file and print canonical JSON.")
    a.add_argument("wav")
    a.add_argument("--json", action="store_true", help="(always JSON; accepted for ears compatibility)")
    args = p.parse_args()
    if args.cmd == "analyze":
        try:
            print(json.dumps(analyze(args.wav)))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"error": str(exc)}))
            sys.exit(1)


if __name__ == "__main__":
    main()
