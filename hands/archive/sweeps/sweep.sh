#!/usr/bin/env bash
# sweep.sh - one command for the whole loop: run the isolated-stem sweep, assert
# the bounces are non-silent, then assemble + measure the acceptance curve with
# the full canonical band set, and show the aligned view.
#
# Usage:
#   bash sweeps/sweep.sh --sweep sweeps/foo.sweep.json \
#        --source-track 6 --source-input "Kick (G)" --capture-track 44 [--no-restore]
#
# Any extra args after the known ones are passed through to run_sweep_stem.py.
# Env: MEASURER (default "uv run python sweeps/measure_local.py"; use ears_shim.py
#      to auto-upgrade to real ears when present), MIN_WAV_KB (default 400).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANDS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$HANDS_ROOT"

MEASURER="${MEASURER:-uv run python sweeps/measure_local.py}"
MIN_WAV_KB="${MIN_WAV_KB:-400}"

SWEEP=""
PASS_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --sweep) SWEEP="$2"; PASS_ARGS+=("$1" "$2"); shift 2 ;;
    *) PASS_ARGS+=("$1"); shift ;;
  esac
done
[ -n "$SWEEP" ] || { echo "ERROR: --sweep <spec.json> is required"; exit 2; }

# output_dir is relative to the hands root, per the spec.
OUT_DIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["output_dir"])' "$SWEEP")"

echo "== 1/3 run isolated-stem sweep =="
uv run python sweeps/run_sweep_stem.py "${PASS_ARGS[@]}"

echo "== 2/3 assert non-silent bounces (>= ${MIN_WAV_KB} KB) =="
silent=0; total=0
for wav in "$OUT_DIR"/bounce_*.wav; do
  [ -e "$wav" ] || continue
  total=$((total + 1))
  kb=$(du -k "$wav" | cut -f1)
  if [ "$kb" -lt "$MIN_WAV_KB" ]; then
    echo "  SILENT? $(basename "$wav") = ${kb} KB"
    silent=$((silent + 1))
  fi
done
if [ "$total" -eq 0 ]; then
  echo "ERROR: no bounces found in $OUT_DIR"; exit 1
fi
if [ "$silent" -gt 0 ]; then
  echo "ERROR: $silent/$total bounces look silent -- check the rig routing / session clip."
  echo "       (build/repair the rig: uv run python sweeps/build_rig.py --source <track>)"
  exit 1
fi
echo "  ok: $total/$total bounces non-silent"

echo "== 3/3 assemble + measure the curve (full canonical bands) =="
uv run python sweeps/assemble_curve.py --dir "$OUT_DIR" \
  --ears-cmd "$MEASURER" \
  --measure-keys crest_db sub_share low_share mid_share high_share air_share

TXT="$OUT_DIR/$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sweep_id"])' "$SWEEP").acceptance.txt"
echo
echo "== aligned view: $TXT =="
[ -f "$TXT" ] && cat "$TXT"
